"""P2 QA shots: palette switching on home / plot page + GO labels + Arc density.

    .venv\\Scripts\\python.exe scripts/p2_shots.py
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
    switch_theme,
    wait_for_server,
)

APP_URL = f"http://127.0.0.1:{PORT}/"
OUT_DIR = PROJECT_ROOT / "scripts" / "_p2_shots"


def screenshot(cdp: CDP, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = cdp.call("Page.captureScreenshot", {"format": "png"})["data"]
    path = OUT_DIR / name
    path.write_bytes(base64.b64decode(data))
    return path


def _press(cdp: CDP, key: str, code: str, windows_key: int) -> None:
    for event_type in ("keyDown", "keyUp"):
        cdp.call(
            "Input.dispatchKeyEvent",
            {
                "type": event_type,
                "key": key,
                "code": code,
                "windowsVirtualKeyCode": windows_key,
                "nativeVirtualKeyCode": windows_key,
            },
        )


def pick_by_keyboard(cdp: CDP, container_js: str, index: int) -> bool:
    """打开下拉后用方向键定位第 index 项并回车（比点坐标更稳）。"""
    rect = cdp.eval(
        f"""
        (() => {{
          const box = {container_js};
          if (!box) return null;
          const select = box.querySelector('[data-baseweb="select"]');
          if (!select) return null;
          const r = select.getBoundingClientRect();
          return {{x: r.x + r.width / 2, y: r.y + r.height / 2}};
        }})()
        """
    )
    if not rect:
        return False
    _click_at(cdp, rect["x"], rect["y"])
    time.sleep(1.2)
    _press(cdp, "Home", "Home", 36)
    time.sleep(0.2)
    for _ in range(index):
        _press(cdp, "ArrowDown", "ArrowDown", 40)
        time.sleep(0.15)
    _press(cdp, "Enter", "Enter", 13)
    time.sleep(3.0)
    return True


def pick_from_selectbox(cdp: CDP, container_js: str, label: str) -> bool:
    """点开指定容器里的第一个 selectbox，再按前缀选中 option。"""
    rect = cdp.eval(
        f"""
        (() => {{
          const box = {container_js};
          if (!box) return null;
          const select = box.querySelector('[data-baseweb="select"]');
          if (!select) return null;
          const r = select.getBoundingClientRect();
          return {{x: r.x + r.width / 2, y: r.y + r.height / 2}};
        }})()
        """
    )
    if not rect:
        return False
    _click_at(cdp, rect["x"], rect["y"])
    time.sleep(1.2)

    hit = cdp.eval(
        f"""
        (() => {{
          const items = [...document.querySelectorAll('li[role="option"], [role="option"]')];
          const target = items.find(e => e.textContent.trim().startsWith({label!r}));
          if (!target) return null;
          const r = target.getBoundingClientRect();
          return {{x: r.x + r.width / 2, y: r.y + r.height / 2}};
        }})()
        """
    )
    if not hit:
        return False
    _click_at(cdp, hit["x"], hit["y"])
    time.sleep(3.0)
    return True


PALETTE_ORDER = [
    "Auto", "No.001", "No.002", "No.003", "No.005",
    "No.009", "No.012", "No.013", "No.015", "No.018", "No.021",
]

PALETTE_SELECT = (
    "document.querySelector('.st-key-sci_palette') "
    "|| document.querySelector('[data-testid=\"stSidebar\"] [data-testid=\"stSelectbox\"]')"
)


def switch_palette(cdp: CDP, label: str) -> bool:
    """侧栏「SCI 配色」下拉（key=sci_palette），用方向键定位，避免点选漂移。"""
    if label not in PALETTE_ORDER:
        return False
    ok = pick_by_keyboard(cdp, PALETTE_SELECT, PALETTE_ORDER.index(label))
    if not ok:
        return False
    displayed = cdp.eval(
        "document.querySelector('.st-key-sci_palette')?.textContent?.trim() || ''"
    ) or ""
    return label in displayed


def wait_home(cdp: CDP, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if (cdp.eval("document.querySelectorAll('.gallery-card').length") or 0) >= 23:
            time.sleep(1.2)
            return
        time.sleep(1.0)
    raise SystemExit("home not ready")


def wait_plot(cdp: CDP, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cdp.eval("!!document.querySelector('.js-plotly-plot')"):
            time.sleep(1.2)
            return
        time.sleep(1.0)
    raise SystemExit("plot not ready")


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
         f"--remote-debugging-port={DEBUG_PORT}", "--user-data-dir=" + str(OUT_DIR / "_profile"),
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    shots: list[Path] = []
    notes: list[str] = []
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

        # ---------- 首页：Auto / No.018 / No.013（预览 SVG 是静态图，仅选择器变化） ----------
        set_viewport(cdp, 1440, 1100)
        cdp.call("Page.navigate", {"url": APP_URL})
        time.sleep(2.5)
        wait_home(cdp)
        shots.append(screenshot(cdp, "home-auto.png"))

        for label, name in (("No.018", "home-palette-018.png"), ("No.013", "home-palette-013.png")):
            if switch_palette(cdp, label):
                cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; })()")
                time.sleep(1.5)
                shots.append(screenshot(cdp, name))
            else:
                notes.append(f"palette {label} switch failed")
        switch_palette(cdp, "Auto")

        # ---------- 首页：Ocean 主题 ----------
        if switch_theme(cdp, "Ocean"):
            time.sleep(1.8)
            shots.append(screenshot(cdp, "home-theme-ocean.png"))
        else:
            notes.append("theme Ocean switch failed")
        switch_theme(cdp, "Light")
        time.sleep(1.5)

        # ---------- 绘图页：Volcano 三种色板（真实体现配色差异） ----------
        cdp.call("Page.navigate", {"url": APP_URL + "?page=plot&plot=Volcano%20Plot"})
        time.sleep(3.0)
        wait_plot(cdp)
        shots.append(screenshot(cdp, "plot-volcano-auto.png"))

        for label, name in (("No.018", "plot-volcano-018.png"), ("No.003", "plot-volcano-003.png")):
            if switch_palette(cdp, label):
                time.sleep(1.0)
                wait_plot(cdp)
                shots.append(screenshot(cdp, name))
            else:
                notes.append(f"plot palette {label} switch failed")
        switch_palette(cdp, "Auto")
        time.sleep(1.0)

        # ---------- 绘图页：PCA 三种色板（分组色随色板变化，火山图语义色固定） ----------
        cdp.call("Page.navigate", {"url": APP_URL + "?page=plot&plot=PCA"})
        time.sleep(3.0)
        wait_plot(cdp)
        shots.append(screenshot(cdp, "plot-pca-auto.png"))
        for label, name in (("No.018", "plot-pca-018.png"), ("No.003", "plot-pca-003.png")):
            if switch_palette(cdp, label):
                time.sleep(1.0)
                wait_plot(cdp)
                shots.append(screenshot(cdp, name))
            else:
                notes.append(f"pca palette {label} switch failed")
        switch_palette(cdp, "Auto")
        time.sleep(1.0)

        # ---------- 绘图页：PCA 三种色板（分组色随色板变化，火山图语义色固定） ----------
        cdp.call("Page.navigate", {"url": APP_URL + "?page=plot&plot=PCA"})
        time.sleep(3.0)
        wait_plot(cdp)
        shots.append(screenshot(cdp, "plot-pca-auto.png"))
        for label, name in (("No.018", "plot-pca-018.png"), ("No.003", "plot-pca-003.png")):
            if switch_palette(cdp, label):
                time.sleep(1.0)
                wait_plot(cdp)
                shots.append(screenshot(cdp, name))
            else:
                notes.append(f"pca palette {label} switch failed")
        switch_palette(cdp, "Auto")
        time.sleep(1.0)

        # ---------- GO Enrichment ----------
        cdp.call("Page.navigate", {"url": APP_URL + "?page=plot&plot=GO%20Enrichment"})
        time.sleep(3.0)
        wait_plot(cdp)
        shots.append(screenshot(cdp, "plot-go-labels.png"))

        # ---------- Arc Diagram ----------
        cdp.call("Page.navigate", {"url": APP_URL + "?page=plot&plot=Arc%20Diagram"})
        time.sleep(3.0)
        wait_plot(cdp)
        shots.append(screenshot(cdp, "plot-arc-density.png"))

        for path in shots:
            print(f"screenshot: {path.relative_to(PROJECT_ROOT)}")
        for note in notes:
            print(f"note: {note}")
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
