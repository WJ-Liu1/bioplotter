"""Preview-colour QA shots: home page (light/dark) + a 6-up sheet of previews.

    .venv\\Scripts\\python.exe scripts/preview_shots.py
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
    find_browser,
    set_viewport,
    switch_theme,
    wait_for_server,
)

APP_URL = f"http://127.0.0.1:{PORT}/"
OUT_DIR = PROJECT_ROOT / "scripts" / "_preview_shots"
PREVIEW_DIR = PROJECT_ROOT / "app" / "assets" / "previews"

# 抽 6 张对比内页主色
SHEET = [
    ("volcano", "Volcano Plot"),
    ("heatmap", "Heatmap"),
    ("circleviz", "CircleViz"),
    ("gmp", "Grouped Matrix Plotting"),
    ("genvar", "Genomic Variation Viewer"),
    ("raincloud", "Raincloud Plot"),
]


def screenshot(cdp: CDP, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = cdp.call("Page.captureScreenshot", {"format": "png"})["data"]
    path = OUT_DIR / name
    path.write_bytes(base64.b64decode(data))
    return path


def build_sheet() -> Path:
    """生成 6 张预览的对照页（每张 400×240，2 行 3 列）。"""
    cells = []
    for stem, title in SHEET:
        svg = (PREVIEW_DIR / f"{stem}.svg").read_text(encoding="utf-8")
        svg = svg.replace('width="100%"', 'width="400" height="240"')
        cells.append(
            f'<figure><div class="card">{svg}</div><figcaption>{title}</figcaption></figure>'
        )
    html = f"""<!doctype html>
<meta charset="utf-8">
<style>
  body {{ margin:0; padding:24px; background:#f5f7fb;
         font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }}
  .grid {{ display:grid; grid-template-columns:repeat(3,400px); gap:20px; }}
  figure {{ margin:0; }}
  .card {{ border:1px solid rgba(15,23,42,.08); border-radius:14px; overflow:hidden;
           background:#f8fafc; }}
  figcaption {{ margin-top:6px; font-size:13px; color:#0f172a; }}
</style>
<div class="grid">{''.join(cells)}</div>
"""
    path = OUT_DIR / "_sheet.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    browser = find_browser()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sheet = build_sheet()

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

        # ---- 6-up sheet ----
        set_viewport(cdp, 1320, 620)
        cdp.call("Page.navigate", {"url": sheet.resolve().as_uri()})
        time.sleep(2.0)
        shots.append(screenshot(cdp, "previews_6up.png"))

        # ---- home light ----
        set_viewport(cdp, 1440, 900)
        cdp.call("Page.navigate", {"url": APP_URL})
        time.sleep(2.5)
        for _ in range(40):
            if (cdp.eval("document.querySelectorAll('.gallery-card').length") or 0) >= 23:
                break
            time.sleep(1.0)
        time.sleep(1.2)
        shots.append(screenshot(cdp, "1440-light-home.png"))

        # ---- home dark ----
        # switch_theme 依赖顶栏 selectbox 的坐标，页面刚渲染完可能还没稳定 → 失败重试一次
        switched = switch_theme(cdp, "Dark")
        if not switched:
            time.sleep(2.0)
            switched = switch_theme(cdp, "Dark")
        if switched:
            cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; })()")
            time.sleep(2.0)
            shots.append(screenshot(cdp, "1440-dark-home.png"))
            switch_theme(cdp, "Light")

        for path in shots:
            print(f"screenshot: {path.relative_to(PROJECT_ROOT)}")
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
