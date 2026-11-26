"""Browser-level UI acceptance probe (dev-only).

Launches the Streamlit app, drives headless Chrome over the DevTools Protocol
(no extra dependency: a ~60-line WebSocket client is inlined), and measures the
things AppTest cannot see:

* sticky topbar: after scrolling 800px, ``.st-key-topbar`` has ``top == 0``
* gallery grid: 4 / 3 / 2 columns at 1440 / 1024 / 768 viewport widths
* no horizontal scroll: ``document.scrollWidth <= innerWidth + 1``
* sidebar collapse control exists at 1024
* screenshots for light + dark at 1440, plus 1024 / 768

    .venv\\Scripts\\python.exe scripts/ui_probe.py
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "scripts" / "_ui_shots"
PORT = 8899
DEBUG_PORT = 9223
APP_URL = f"http://127.0.0.1:{PORT}/"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


# ---------------------------------------------------------------------------
# Minimal WebSocket client (RFC 6455, text frames only)
# ---------------------------------------------------------------------------
class WebSocket:
    def __init__(self, url: str) -> None:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        self.sock = socket.create_connection((host, port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            buffer += self.sock.recv(4096)
        if b"101" not in buffer.split(b"\r\n")[0]:
            raise RuntimeError(f"websocket handshake failed: {buffer[:120]!r}")
        self._buffer = buffer.split(b"\r\n\r\n", 1)[1]

    def send(self, payload: str) -> None:
        data = payload.encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def _read(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("websocket closed")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def recv(self) -> str:
        payload = b""
        while True:
            first, second = self._read(2)
            fin = first & 0x80
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            payload += self._read(length)
            if fin:
                break
        return payload.decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


class CDP:
    def __init__(self, ws_url: str) -> None:
        self.ws = WebSocket(ws_url)
        self.counter = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self.counter += 1
        message_id = self.counter
        self.ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = json.loads(self.ws.recv())
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})
        raise TimeoutError(method)

    def eval(self, expression: str, timeout: float = 30.0):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
        )
        return result.get("result", {}).get("value")

    def close(self) -> None:
        self.ws.close()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
def find_browser() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("no Chrome/Edge found")


def wait_for_server(timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"{APP_URL}_stcore/health", timeout=2).text.strip() == "ok":
                return
        except Exception:
            pass
        time.sleep(1.0)
    raise SystemExit("streamlit server did not start")


def wait_for_app(cdp: CDP, expected_cards: int = 23, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        cards = cdp.eval("document.querySelectorAll('.gallery-card').length") or 0
        if cards >= expected_cards:
            time.sleep(1.5)  # let preview SVG + fonts settle
            return
        time.sleep(1.0)
    raise SystemExit(f"app did not render {expected_cards} gallery cards")


GRID_PROBE = """
(() => {
  const main = document.querySelector('section[data-testid="stMain"]');
  if (main) main.scrollTop = 0;
  window.scrollTo(0, 0);
  const cards = [...document.querySelectorAll('.gallery-card')];
  const rows = {};
  cards.forEach(c => {
    const top = Math.round(c.getBoundingClientRect().top);
    rows[top] = (rows[top] || 0) + 1;
  });
  const rowCounts = Object.values(rows);
  return {
    cards: cards.length,
    firstRow: rowCounts.length ? Math.max(...rowCounts) : 0,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    hasCollapseCtrl: !!document.querySelector('[data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarCollapseButton"]'),
  };
})()
"""

STICKY_PROBE = """
(() => {
  const bar = document.querySelector('.st-key-topbar');
  const main = document.querySelector('section[data-testid="stMain"]') || document.scrollingElement;
  main.scrollTop = 800;
  const rect = bar.getBoundingClientRect();
  const style = getComputedStyle(bar);
  return {
    top: Math.round(rect.top),
    position: style.position,
    scrollTop: Math.round(main.scrollTop),
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  };
})()
"""


def set_viewport(cdp: CDP, width: int, height: int) -> None:
    cdp.call(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
    )


def screenshot(cdp: CDP, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = cdp.call("Page.captureScreenshot", {"format": "png"})["data"]
    path = OUT_DIR / name
    path.write_bytes(base64.b64decode(data))
    return path


def _hover_at(cdp: CDP, x: float, y: float) -> None:
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    time.sleep(0.4)


def _click_at(cdp: CDP, x: float, y: float) -> None:
    """Real mouse event via CDP (BaseWeb ignores synthetic MouseEvent clicks)."""
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    for event_type in ("mousePressed", "mouseReleased"):
        cdp.call(
            "Input.dispatchMouseEvent",
            {"type": event_type, "x": x, "y": y, "button": "left", "clickCount": 1},
        )


def switch_theme(cdp: CDP, label: str) -> bool:
    """Open the topbar theme selectbox and pick ``label`` with real input events."""
    rect = cdp.eval(
        """
        (() => {
          const box = document.querySelector('.st-key-topbar [data-testid="stSelectbox"]');
          const select = box && box.querySelector('[data-baseweb="select"]');
          if (!select) return null;
          const r = select.getBoundingClientRect();
          return {x: r.x + r.width / 2, y: r.y + r.height / 2};
        })()
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
          const target = items.find(e => {{
            const text = e.textContent.trim();
            return text === {label!r} || text.startsWith({label!r}) || text.toLowerCase().startsWith({label!r}.toLowerCase());
          }});
          if (!target) return null;
          const r = target.getBoundingClientRect();
          return {{x: r.x + r.width / 2, y: r.y + r.height / 2}};
        }})()
        """
    )
    if not hit:
        return False
    _click_at(cdp, hit["x"], hit["y"])
    time.sleep(3.5)
    return bool(cdp.eval("!!document.querySelector('.st-key-topbar')"))


def main() -> int:
    browser = find_browser()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.headless=true",
            f"--server.port={PORT}",
            "--browser.gatherUsageStats=false",
        ],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    chrome = subprocess.Popen(
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={DEBUG_PORT}",
            "--user-data-dir=" + str(OUT_DIR / "_profile"),
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    results: list[str] = []
    failures = 0
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
            raise SystemExit("could not reach the Chrome devtools endpoint")

        cdp = CDP(ws_url)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")

        checks: list[tuple[str, bool, str]] = []

        # ---------- 1440 light ----------
        set_viewport(cdp, 1440, 900)
        cdp.call("Page.navigate", {"url": APP_URL})
        time.sleep(2.0)
        wait_for_app(cdp)

        grid = cdp.eval(GRID_PROBE)
        checks.append(("1440 卡片数=24", grid["cards"] == 24, f"cards={grid['cards']}"))
        checks.append(("1440 首行 4 列", grid["firstRow"] == 4, f"row={grid['firstRow']}"))
        checks.append(
            ("1440 无横向滚动",
             grid["scrollWidth"] <= grid["innerWidth"] + 1,
             f"{grid['scrollWidth']} <= {grid['innerWidth']}"),
        )

        shot = screenshot(cdp, "1440-light-home.png")
        results.append(f"screenshot: {shot.relative_to(PROJECT_ROOT)}")

        sticky = cdp.eval(STICKY_PROBE)
        checks.append(("顶栏 sticky top=0（滚 800px 后）", sticky["top"] == 0, f"top={sticky['top']} scrollTop={sticky['scrollTop']}"))
        checks.append(("顶栏 position=sticky", sticky["position"] == "sticky", sticky["position"]))
        shot = screenshot(cdp, "1440-light-scrolled.png")
        results.append(f"screenshot: {shot.relative_to(PROJECT_ROOT)}")

        # ---------- 1440 dark (top + scrolled) ----------
        if switch_theme(cdp, "Dark"):
            cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; window.scrollTo(0,0); })()")
            time.sleep(1.0)
            shot_dark_top = screenshot(cdp, "1440-dark-home.png")
            results.append(f"screenshot: {shot_dark_top.relative_to(PROJECT_ROOT)}")
            cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 800; })()")
            time.sleep(0.8)
            shot_dark_scrolled = screenshot(cdp, "1440-dark-scrolled.png")
            results.append(f"screenshot: {shot_dark_scrolled.relative_to(PROJECT_ROOT)}")
            cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; })()")
            cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; window.scrollTo(0,0); })()")
            time.sleep(1.0)
            shot = screenshot(cdp, "1440-dark-home.png")
            results.append(f"screenshot: {shot.relative_to(PROJECT_ROOT)}")
            dark_ok = cdp.eval("!!document.querySelector('.st-key-topbar')")
            checks.append(("1440 暗色渲染", bool(dark_ok), "ok" if dark_ok else "topbar missing"))
            switch_theme(cdp, "Light")
            cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; window.scrollTo(0,0); })()")
            time.sleep(1.5)
        else:
            checks.append(("1440 暗色渲染", False, "theme selectbox 自动化点击失败（需人工确认）"))

        # ---------- 1024 ----------
        set_viewport(cdp, 1024, 768)
        time.sleep(2.5)
        cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; window.scrollTo(0,0); })()")
        time.sleep(0.8)
        grid = cdp.eval(GRID_PROBE)
        checks.append(("1024 首行 3 列", grid["firstRow"] == 3, f"row={grid['firstRow']}"))
        checks.append(
            ("1024 无横向滚动",
             grid["scrollWidth"] <= grid["innerWidth"] + 1,
             f"{grid['scrollWidth']} <= {grid['innerWidth']}"),
        )
        checks.append(("1024 侧栏折叠控件存在", grid["hasCollapseCtrl"], "ok" if grid["hasCollapseCtrl"] else "missing"))
        shot = screenshot(cdp, "1024-light-home.png")
        results.append(f"screenshot: {shot.relative_to(PROJECT_ROOT)}")

        # collapse / expand must really work at 1024 (AC-19)
        SIDEBAR_STATE = """
        (() => {
          const s = document.querySelector('[data-testid="stSidebar"]');
          if (!s) return {w: 0, right: -1};
          const r = s.getBoundingClientRect();
          return {w: Math.round(r.width), right: Math.round(r.right)};
        })()
        """
        VISIBLE_TOGGLE = """
        (() => {
          const sels = [
            '[data-testid="stSidebarCollapseButton"] button',
            '[data-testid="stSidebarCollapseButton"]',
            '[data-testid="stSidebarCollapsedControl"] button',
            '[data-testid="stSidebarCollapsedControl"]'
          ];
          for (const sel of sels) {
            for (const el of document.querySelectorAll(sel)) {
              const r = el.getBoundingClientRect();
              if (r.width > 6 && r.height > 6 && r.right > 0 && r.left >= 0) {
                return {x: r.x + r.width / 2, y: r.y + r.height / 2, sel: sel};
              }
            }
          }
          return null;
        })()
        """

        before = cdp.eval(SIDEBAR_STATE)
        toggle = cdp.eval(VISIBLE_TOGGLE)
        collapsed = before
        restored = before
        if toggle:
            _hover_at(cdp, toggle["x"], toggle["y"])
            _click_at(cdp, toggle["x"], toggle["y"])
            time.sleep(1.6)
            collapsed = cdp.eval(SIDEBAR_STATE)
            if collapsed["right"] > 1 and collapsed["w"] >= before["w"] * 0.5:
                # 某些 Streamlit 版本首次点击只做悬停显形，再点一次
                _click_at(cdp, toggle["x"], toggle["y"])
                time.sleep(1.6)
                collapsed = cdp.eval(SIDEBAR_STATE)

            reopen = cdp.eval(VISIBLE_TOGGLE)
            if reopen:
                _click_at(cdp, reopen["x"], reopen["y"])
                time.sleep(1.6)
                restored = cdp.eval(SIDEBAR_STATE)

        went_away = collapsed["right"] <= 1 or collapsed["w"] < before["w"] * 0.5
        came_back = restored["w"] >= before["w"] * 0.9 and restored["right"] > 1
        checks.append(
            ("1024 侧栏可折叠/可恢复",
             bool(toggle) and went_away and came_back,
             f"{toggle['sel'] if toggle else 'no-visible-toggle'} | w: {before['w']}→{collapsed['w']}→{restored['w']} | right: {before['right']}→{collapsed['right']}→{restored['right']}"),
        )

        # ---------- 768 ----------
        set_viewport(cdp, 768, 1024)
        time.sleep(2.5)
        cdp.eval("(() => { const m = document.querySelector('section[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; window.scrollTo(0,0); })()")
        time.sleep(0.8)
        grid = cdp.eval(GRID_PROBE)
        checks.append(("768 首行 2 列", grid["firstRow"] == 2, f"row={grid['firstRow']}"))
        checks.append(
            ("768 无横向滚动",
             grid["scrollWidth"] <= grid["innerWidth"] + 1,
             f"{grid['scrollWidth']} <= {grid['innerWidth']}"),
        )
        shot = screenshot(cdp, "768-light-home.png")
        results.append(f"screenshot: {shot.relative_to(PROJECT_ROOT)}")

        # ---------- plot page ----------
        set_viewport(cdp, 1440, 900)
        cdp.call("Page.navigate", {"url": APP_URL + "?page=plot&plot=Volcano%20Plot"})
        time.sleep(3.0)
        deadline = time.time() + 45
        has_plot = False
        while time.time() < deadline:
            if cdp.eval("!!document.querySelector('.js-plotly-plot')"):
                has_plot = True
                break
            time.sleep(1.5)
        tabs = cdp.eval("[...document.querySelectorAll('[data-testid=\"stTabs\"] [role=\"tab\"]')].map(e=>e.textContent.trim())")
        checks.append(("绘图页渲染 Plotly 图", has_plot, "ok" if has_plot else "no .js-plotly-plot"))
        checks.append(("绘图页 3 个 Tab", tabs == ["图形", "数据预览", "使用说明"], str(tabs)))
        time.sleep(1.0)
        shot = screenshot(cdp, "1440-light-plot-volcano.png")
        results.append(f"screenshot: {shot.relative_to(PROJECT_ROOT)}")

        # export popover must open and expose the format radio
        trigger = cdp.eval(
            """
            (() => {
              const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('导出结果'));
              if (!btn) return null;
              const r = btn.getBoundingClientRect();
              return {x: r.x + r.width / 2, y: r.y + r.height / 2};
            })()
            """
        )
        if trigger:
            _click_at(cdp, trigger["x"], trigger["y"])
            time.sleep(1.5)
            body = cdp.eval(
                "(() => { const b = document.querySelector('[data-testid=\"stPopoverBody\"]'); return b ? b.textContent : ''; })()"
            ) or ""
            checks.append(("导出弹层可打开", len(body) > 0, f"len={len(body)}"))
            checks.append(
                ("导出格式含 HTML/JSON（无 kaleido）",
                 "HTML" in body and "JSON" in body,
                 body[:60].replace("\n", " ")),
            )
            shot = screenshot(cdp, "1440-light-export-popover.png")
            results.append(f"screenshot: {shot.relative_to(PROJECT_ROOT)}")
            cdp.eval("document.body.click()")
            time.sleep(0.5)

        print()
        for label, ok, detail in checks:
            print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
            if not ok:
                failures += 1
        print()
        for line in results:
            print(line)
        print()
        print(f"ui-probe: {len(checks) - failures}/{len(checks)} passed")
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
