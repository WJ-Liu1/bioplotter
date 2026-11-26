"""只截 GO Enrichment 的图（横向条形复核用）。

    .venv\\Scripts\\python.exe scripts/go_shot.py
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
    wait_for_server,
)

APP_URL = f"http://127.0.0.1:{PORT}/"
OUT_DIR = PROJECT_ROOT / "scripts" / "_p2_shots"


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
         f"--remote-debugging-port={DEBUG_PORT}", "--user-data-dir=" + str(OUT_DIR / "_go_profile"),
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

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

        set_viewport(cdp, 1440, 1200)
        cdp.call("Page.navigate", {"url": APP_URL + "?page=plot&plot=GO%20Enrichment"})
        time.sleep(3.0)
        for _ in range(60):
            if cdp.eval("!!document.querySelector('.js-plotly-plot')"):
                break
            time.sleep(1.0)
        time.sleep(2.0)

        # 断言图表确实是横向的（读 SVG 里第一根柱子的宽高比）
        orientation = cdp.eval(
            """
            (() => {
              const bars = [...document.querySelectorAll('.js-plotly-plot .bars .point path')];
              if (!bars.length) return null;
              const r = bars[0].getBoundingClientRect();
              return {w: Math.round(r.width), h: Math.round(r.height)};
            })()
            """
        )
        print("first bar box:", orientation)

        data = cdp.call("Page.captureScreenshot", {"format": "png"})["data"]
        path = OUT_DIR / "plot-go-labels.png"
        path.write_bytes(base64.b64decode(data))
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
