"""把首页预览 SVG 的硬编码配色收敛到 Paper 主题（可重复执行）。

规则：
* 只替换 fill="#xxxxxx" / stroke="#xxxxxx"，不动结构、viewBox 与 opacity；
* 中性色（白 / 纸 / 墨 / 线）直接映射到 Paper 的对应值；
* 彩色保留色相差异，但压低饱和度、把明度收进印刷色带，并向墨绿轻微偏移，
  这样整套缩略图读起来像同一本图册，而不是 24 种风格。

    .venv\\Scripts\\python.exe scripts/paper_previews.py          # 预览映射
    .venv\\Scripts\\python.exe scripts/paper_previews.py --write  # 写入文件
"""

from __future__ import annotations

import colorsys
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREVIEW_DIR = PROJECT_ROOT / "app" / "assets" / "previews"

COLOR_RE = re.compile(r'(fill|stroke)="(#[0-9A-Fa-f]{6})"')

# Paper 中性色：纸底 / 墨 / 次级文字 / 线
NEUTRALS = {
    "#FFFFFF": "#FFFFFF",
    "#F8FAFC": "#FCFDFC",
    "#0F172A": "#16211D",
    "#2E3A4A": "#2B3733",
    "#64748B": "#6B7873",
    "#94A3B8": "#93A09A",
    "#E2E8F0": "#E3E7E4",
    "#BFDBFE": "#DCE6E1",
    "#DBEAFE": "#EBF1EE",
    "#BEDDE6": "#DEE9E4",
    "#F3F3D8": "#F1F2EC",
}

TEAL_HUE = 168 / 360


def _to_hex(red: float, green: float, blue: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, round(red * 255))),
        max(0, min(255, round(green * 255))),
        max(0, min(255, round(blue * 255))),
    )


def paperize(hex_color: str) -> str:
    key = hex_color.upper()
    if key in NEUTRALS:
        return NEUTRALS[key]

    raw = key.lstrip("#")
    red, green, blue = (int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)

    drift = ((TEAL_HUE - hue + 0.5) % 1.0) - 0.5
    hue = (hue + drift * 0.34) % 1.0
    saturation = min(saturation * 0.72, 0.30)
    lightness = min(max(lightness, 0.34), 0.74)

    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return _to_hex(red, green, blue)


def convert(svg: str) -> str:
    def swap(match: re.Match[str]) -> str:
        return f'{match.group(1)}="{paperize(match.group(2))}"'

    return COLOR_RE.sub(swap, svg)


def main() -> int:
    write = "--write" in sys.argv
    files = sorted(PREVIEW_DIR.glob("*.svg"))
    for path in files:
        source = path.read_text(encoding="utf-8")
        updated = convert(source)
        if write and updated != source:
            path.write_text(updated, encoding="utf-8")
        if not write:
            count = len(COLOR_RE.findall(source))
            print(f"{path.name}: {count} colors")
    print(f"{len(files)} previews {'written' if write else 'scanned'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
