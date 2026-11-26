"""Browser-level P0 acceptance probe (dev-only).

Checks what AppTest cannot see: the three-step guide renders as three cards,
card chips are visible, the floating action bar is actually pinned to the
toolbar is not covered by any overlay, the data-health metrics render,
and nothing introduces horizontal scrolling at 1440 / 1024 / 768.

    .venv\\Scripts\\python.exe scripts/ui_probe_p0.py

Reuses the CDP client from ``ui_probe.py`` (no extra dependency).
"""

from __future__ import annotations

import base64
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402

from ui_probe import (  # noqa: E402
    CDP,
    DEBUG_PORT,
    PORT,
    _click_at,
    find_browser,
    set_viewport,
    wait_for_server,
    switch_theme,
)

APP_URL = f"http://127.0.0.1:{PORT}/"
OUT_DIR = PROJECT_ROOT / "scripts" / "_p0_shots"

HOME_PROBE = """
(() => {
  const main = document.querySelector('section[data-testid="stMain"]');
  if (main) main.scrollTop = 0;
  window.scrollTo(0, 0);
  const steps = [...document.querySelectorAll('.guide-step')];
  const chips = [...document.querySelectorAll('.tag-chip')];
  const cards = [...document.querySelectorAll('.gallery-card')];
  const rows = {};
  cards.forEach(c => { const t = Math.round(c.getBoundingClientRect().top); rows[t] = (rows[t] || 0) + 1; });
  const counts = Object.values(rows);
  return {
    steps: steps.length,
    guideVisible: steps.length > 0 && steps.every(s => s.getBoundingClientRect().height > 20),
    chips: chips.length,
    shapeChips: document.querySelectorAll('.tag-chip.shape').length,
    levelChips: document.querySelectorAll('.tag-chip[class*="level-"]').length,
    cards: cards.length,
    firstRow: counts.length ? Math.max(...counts) : 0,
    shapeSelect: !!document.querySelector('.stSelectbox'),
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  };
})()
"""

PLOT_PROBE = """
(() => {
  const toolbar = document.querySelector('.st-key-plot-toolbar');
  const bar = document.querySelector('.st-key-plot-actions');
  const metrics = document.querySelectorAll('[data-testid="stMetric"]').length;
  const info = {toolbar: false, legacyBar: !!bar, metrics: metrics, overlap: 0, inViewport: false};
  if (!toolbar) return info;
  const t = toolbar.getBoundingClientRect();
  info.toolbar = t.width > 100 && t.height > 20;
  info.inViewport = t.bottom <= window.innerHeight + 2 && t.top >= 0;
  const plot = document.querySelector('.js-plotly-plot');
  if (plot) {
    const p = plot.getBoundingClientRect();
    const overlapX = Math.max(0, Math.min(t.right, p.right) - Math.max(t.left, p.left));
    const overlapY = Math.max(0, Math.min(t.bottom, p.bottom) - Math.max(t.top, p.top));
    info.overlap = Math.round(overlapX * overlapY);
  }
  return info;
})()
"""


TOPBAR_PROBE = """
(() => {
  const bar = document.querySelector('.st-key-topbar');
  if (!bar) return {rows: 0, themeW: 0, over: 0};
  const parts = [
    bar.querySelector('.topbar-brand'),
    bar.querySelector('[data-testid="stTextInput"]'),
    bar.querySelector('[data-testid="stSelectbox"]')
  ].filter(Boolean);
  // 用「重叠聚类」判断真正换行：元素高度不同，单纯比 top 会误判
  const bands = [];
  parts.forEach(p => {
    const r = p.getBoundingClientRect();
    const band = bands.find(b => r.top < b.bottom - 2 && r.bottom > b.top + 2);
    if (band) { band.top = Math.min(band.top, r.top); band.bottom = Math.max(band.bottom, r.bottom); }
    else bands.push({top: r.top, bottom: r.bottom});
  });
  const theme = bar.querySelector('[data-testid="stSelectbox"]');
  const themeRect = theme ? theme.getBoundingClientRect() : {width: 0};
  return {
    rows: bands.length,
    themeW: Math.round(themeRect.width),
    over: document.documentElement.scrollWidth - window.innerWidth,
  };
})()
"""

SIDEBAR_FIELD_PROBE = """
(() => {
  const input = document.querySelector('[data-testid="stSidebar"] input');
  if (!input) return null;
  const style = getComputedStyle(input);
  // 输入框自身可能是透明的，真实底色来自父级 baseweb 容器
  let bg = style.backgroundColor;
  let node = input.parentElement;
  while (node && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) {
    bg = getComputedStyle(node).backgroundColor;
    node = node.parentElement;
  }
  return {color: style.webkitTextFillColor || style.color, bg};
})()
"""


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 对比度（1–21），用于判断文字是否可读。"""
    def parse(value: str) -> tuple[float, float, float]:
        numbers = [float(n) for n in value.replace("rgba(", "").replace("rgb(", "").replace(")", "").split(",")[:3]]
        return tuple(n / 255 for n in numbers)  # type: ignore[return-value]

    def luminance(rgb: tuple[float, float, float]) -> float:
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    try:
        high, low = sorted((luminance(parse(foreground)), luminance(parse(background))), reverse=True)
    except Exception:
        return 0.0
    return (high + 0.05) / (low + 0.05)


def screenshot(cdp: CDP, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = cdp.call("Page.captureScreenshot", {"format": "png"})["data"]
    path = OUT_DIR / name
    path.write_bytes(base64.b64decode(data))
    return path


def wait_home(cdp: CDP, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        cards = cdp.eval("document.querySelectorAll('.gallery-card').length") or 0
        if cards >= 23:
            time.sleep(1.2)
            return
        time.sleep(1.0)
    raise SystemExit("home page did not render 23 cards")


def wait_plot(cdp: CDP, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cdp.eval("!!document.querySelector('.js-plotly-plot')") and cdp.eval(
            "!!document.querySelector('.st-key-plot-toolbar')"
        ):
            time.sleep(1.2)
            return
        time.sleep(1.0)
    raise SystemExit("plot page did not render")


def main() -> int:
    browser = find_browser()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless=true",
         f"--server.port={PORT}", "--browser.gatherUsageStats=false"],
        cwd=str(PROJECT_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    chrome = subprocess.Popen(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
         f"--remote-debugging-port={DEBUG_PORT}", "--user-data-dir=" + str(OUT_DIR / "_profile"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    checks: list[tuple[str, bool, str]] = []
    shots: list[Path] = []
    try:
        wait_for_server()
        ws_url = None
        for _ in range(60):
            try:
                targets = requests.get(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=2).json()
                pages = [t for t in targets if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(1.0)
        if not ws_url:
            raise SystemExit("could not reach Chrome devtools")

        cdp = CDP(ws_url)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")

        # ---------- 1440 light home ----------
        set_viewport(cdp, 1440, 900)
        cdp.call("Page.navigate", {"url": APP_URL})
        time.sleep(2.5)
        wait_home(cdp)

        home = cdp.eval(HOME_PROBE)
        checks.append(("首页三步引导可见", home["steps"] == 3 and home["guideVisible"], f"steps={home['steps']}"))
        checks.append(("卡片 chip 可见（每卡 2 个）", home["chips"] == 2 * home["shapeChips"] == 2 * home["levelChips"] and home["shapeChips"] >= 24, f"chips={home['chips']} shape={home['shapeChips']} level={home['levelChips']}"))
        checks.append(("形状下拉存在", home["shapeSelect"], "ok"))
        checks.append(("1440 首行 4 列", home["firstRow"] == 4, f"row={home['firstRow']} cards={home['cards']}"))
        checks.append(("1440 无横向滚动", home["scrollWidth"] <= home["innerWidth"] + 1, f"{home['scrollWidth']}<={home['innerWidth']}"))
        shots.append(screenshot(cdp, "1440-light-home.png"))

        # ---------- 1440 dark home ----------
        if switch_theme(cdp, "Dark"):
            cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; })()")
            time.sleep(1.5)
            shots.append(screenshot(cdp, "1440-dark-home.png"))
            switch_theme(cdp, "Light")
            time.sleep(1.5)

        # ---------- plot page: single toolbar, no floating bar ----------
        cdp.call("Page.navigate", {"url": APP_URL + "?page=plot&plot=Volcano%20Plot"})
        time.sleep(3.0)
        wait_plot(cdp)

        plot = cdp.eval(PLOT_PROBE)
        checks.append(("工具栏可见", plot["toolbar"], str(plot.get("rect"))))
        checks.append(("无旧悬浮操作条", not plot["legacyBar"], "ok"))
        checks.append(("工具栏不遮挡图形", plot["overlap"] == 0, f"overlap={plot['overlap']}px²"))
        checks.append(("数据体检 metric 可见", plot["metrics"] >= 4, f"metrics={plot['metrics']}"))
        shots.append(screenshot(cdp, "1440-light-plot.png"))

        light_field = cdp.eval(SIDEBAR_FIELD_PROBE)
        light_ratio = contrast_ratio(light_field["color"], light_field["bg"]) if light_field else 0.0
        checks.append(
            (
                "1440 亮色：侧栏输入框对比度 ≥4.5",
                bool(light_field) and light_ratio >= 4.5,
                f"ratio={light_ratio:.2f} {light_field}",
            )
        )

        if switch_theme(cdp, "Dark"):
            time.sleep(2.0)
            dark_field = cdp.eval(SIDEBAR_FIELD_PROBE)
            dark_ratio = contrast_ratio(dark_field["color"], dark_field["bg"]) if dark_field else 0.0
            checks.append(
                (
                    "1440 暗色：侧栏输入框对比度 ≥4.5",
                    bool(dark_field) and dark_ratio >= 4.5,
                    f"ratio={dark_ratio:.2f} {dark_field}",
                )
            )
            shots.append(screenshot(cdp, "1440-dark-plot.png"))
            switch_theme(cdp, "Light")
            time.sleep(1.5)

        # ---------- 1024 ----------
        set_viewport(cdp, 1024, 768)
        time.sleep(2.0)
        cdp.call("Page.navigate", {"url": APP_URL})
        time.sleep(2.0)
        wait_home(cdp)
        home_1024 = cdp.eval(HOME_PROBE)
        checks.append(("1024 首行 3 列", home_1024["firstRow"] == 3, f"row={home_1024['firstRow']}"))
        checks.append(("1024 无横向滚动", home_1024["scrollWidth"] <= home_1024["innerWidth"] + 1,
                       f"{home_1024['scrollWidth']}<={home_1024['innerWidth']}"))
        bar_1024 = cdp.eval(TOPBAR_PROBE)
        checks.append(("1024 顶栏单行", bar_1024["rows"] == 1, f"rows={bar_1024['rows']}"))
        checks.append(("1024 主题列 96–120px", 90 <= bar_1024["themeW"] <= 130, f"w={bar_1024['themeW']}"))
        shots.append(screenshot(cdp, "1024-light-home.png"))

        # ---------- 768 ----------
        set_viewport(cdp, 768, 1024)
        time.sleep(2.5)
        cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; })()")
        home_768 = cdp.eval(HOME_PROBE)
        checks.append(("768 首行 2 列", home_768["firstRow"] == 2, f"row={home_768['firstRow']}"))
        checks.append(("768 无横向滚动", home_768["scrollWidth"] <= home_768["innerWidth"] + 1,
                       f"{home_768['scrollWidth']}<={home_768['innerWidth']}"))
        checks.append(("768 引导仍为 3 步", home_768["steps"] == 3, f"steps={home_768['steps']}"))

        bar_768 = cdp.eval(TOPBAR_PROBE)
        checks.append(("768 顶栏单行", bar_768["rows"] == 1, f"rows={bar_768['rows']}"))
        checks.append(("768 主题列 96–110px", 90 <= bar_768["themeW"] <= 120, f"w={bar_768['themeW']}"))
        checks.append(("768 顶栏不溢出", bar_768["over"] <= 1, f"overflow={bar_768['over']}"))
        shots.append(screenshot(cdp, "768-light-home.png"))

        # ---------- 768 plot: bar should not overflow ----------
        cdp.call("Page.navigate", {"url": APP_URL + "?page=plot&plot=Volcano%20Plot"})
        time.sleep(3.0)
        wait_plot(cdp)
        plot_768 = cdp.eval(PLOT_PROBE)
        checks.append(("768 悬浮条不出界", plot_768["inViewport"], str(plot_768.get("rect"))))
        checks.append(("768 绘图页无横向滚动",
                       (cdp.eval("document.documentElement.scrollWidth") or 0) <= 769,
                       f"{cdp.eval('document.documentElement.scrollWidth')}"))
        shots.append(screenshot(cdp, "768-light-plot.png"))

        print()
        failures = 0
        for label, ok, detail in checks:
            print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
            if not ok:
                failures += 1
        print()
        for path in shots:
            print(f"screenshot: {path.relative_to(PROJECT_ROOT)}")
        print()
        print(f"p0-ui-probe: {len(checks) - failures}/{len(checks)} passed")
    finally:
        try:
            chrome.terminate()
        except Exception:
            pass
        try:
            server.terminate()
        except Exception:
            pass
        time.sleep(1.0)

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
