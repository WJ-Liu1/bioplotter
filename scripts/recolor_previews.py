"""把首页 23 张预览 SVG 的硬编码配色同步到 SCI 色板（一次性脚本，可重复执行）。

规则：
* 只替换 ``fill="#xxxxxx"`` / ``stroke="#xxxxxx"`` 里的十六进制色值，
  不动 ``var(--...)``、``opacity``、``stroke-width``、``d``、viewBox 等结构。
* 语义色优先：volcano / heatmap / km / manhattan / pca / upset 等模块按语义键映射。
* 其余模块：按颜色出现频次从 ``palette_for(module)`` 依次取色（同色去重）。

    .venv\\Scripts\\python.exe scripts/recolor_previews.py            # 预览映射，不写文件
    .venv\\Scripts\\python.exe scripts/recolor_previews.py --write    # 实际写入
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core import catalog  # noqa: E402
from app.core.palettes import (  # noqa: E402
    GMP_GROUP_COLORS,
    SCI_DIST_COLORS,
    SCI_NETWORK_COLORS,
    palette_for,
)
from app.core.theme import THEMES  # noqa: E402

PREVIEW_DIR = PROJECT_ROOT / "app" / "assets" / "previews"
THEME = THEMES["Light"]  # 首页默认亮色主题的语义色
MAX_BYTES = 4096

COLOR_RE = re.compile(r'(fill|stroke)="(#[0-9A-Fa-f]{3,6})"')

# 语义色覆盖：旧色 → 语义键（只列该预览确实用到的旧色）
SEMANTIC_OVERRIDES: dict[str, dict[str, str]] = {
    "volcano": {
        "#E64B35": "volcano_up",
        "#4DBBD5": "volcano_down",
        "#B0B0B0": "volcano_ns",
        "#94a3b8": "volcano_thr",
    },
    "heatmap": {
        "#D73027": "heatmap_high",
        "#e8836f": "heatmap_high_mid",
        "#f3f3d8": "heatmap_mid",
        "#7fa8cd": "heatmap_low_mid",
        "#4575B4": "heatmap_low",
    },
    "km": {
        "#E64B35": "km_g1",
        "#4DBBD5": "km_g2",
    },
    "manhattan": {
        "#E64B35": "manhattan_sig",
        "#3C5488": "manhattan_odd",
        "#8491B4": "manhattan_even",
    },
    "pca": {
        "#E64B35": "pca_group1",
        "#3C5488": "pca_group2",
        "#00A087": "pca_group3",
    },
    "upset": {
        "#E64B35": "upset_active",
        "#3C5488": "upset_bar",
        "#8491B4": "upset_setbar",
        "#C8CDD4": "upset_inactive",
    },
    "circleviz": {
        "#14b8a6": "circle_cat1",
        "#f59e0b": "circle_cat2",
        "#3b82f6": "circle_cat3",
        "#24a26a": "circle_cat4",
    },
    "circularbar": {
        "#3b82f6": "cbar_pos",
        "#ef4444": "cbar_neg",
    },
    "genvar": {
        "#3b82f6": "genvar_feature",
        "#14b8a6": "genvar_upper",
        "#8b5cf6": "genvar_lower",
    },
}


NETWORK_PREVIEWS = {"arc", "heb", "chord", "nodelink", "sankey"}
DIST_PREVIEWS = {"raincloud", "beeswarm", "splitviolin", "scaboxden", "pirate"}


def _luminance(value: str) -> float:
    r, g, b = (channel / 255 for channel in hex_to_rgb(value))
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _saturation(value: str) -> float:
    r, g, b = hex_to_rgb(value)
    high, low = max(r, g, b), min(r, g, b)
    return 0.0 if high == 0 else (high - low) / high


def _mix(color_a: str, color_b: str, ratio: float) -> str:
    """在两个颜色之间线性插值（ratio=0 → a，1 → b）。"""
    a_rgb, b_rgb = hex_to_rgb(color_a), hex_to_rgb(color_b)
    blended = [round(a + (b - a) * ratio) for a, b in zip(a_rgb, b_rgb)]
    return "#" + "".join(f"{channel:02X}" for channel in blended)


def _mid_tone(colors) -> list[str]:
    """只保留「既不太白也不太黑」的颜色，白/黑留给背景与墨色。"""
    picked = [c for c in colors if 0.13 <= _luminance(c) <= 0.86]
    return picked or [c for c in SCI_DIST_COLORS if 0.13 <= _luminance(c) <= 0.86]


def _extend(pool: list[str]) -> list[str]:
    """补足到至少 8 个互不相同的中间调色，供多色预览不重复。"""
    extras = _mid_tone(list(SCI_DIST_COLORS) + list(SCI_NETWORK_COLORS) + list(GMP_GROUP_COLORS))
    merged = list(dict.fromkeys(pool))
    for color in extras:
        if len(merged) >= 8:
            break
        if color.lower() not in {c.lower() for c in merged}:
            merged.append(color)
    return merged


def color_pool(preview_stem: str, module: str) -> list[str]:
    """每个模块的候选颜色池：优先用它自己的 SCI 色，保证与内页主色一致。"""
    if preview_stem in NETWORK_PREVIEWS:
        return _extend(_mid_tone(SCI_NETWORK_COLORS))
    if preview_stem in DIST_PREVIEWS:
        return _extend(_mid_tone(SCI_DIST_COLORS))
    if preview_stem == "gmp":
        return _extend(_mid_tone(GMP_GROUP_COLORS))
    if preview_stem == "mantel":
        return _mid_tone([THEME["sci_mantel_low"], THEME["sci_mantel_high"], THEME["sci_mantel_mid"]])
    if preview_stem == "go":
        return _mid_tone([THEME["sci_go_1"], THEME["sci_go_2"], THEME["sci_go_3"]])
    if preview_stem == "bubbleviz":
        return _extend(_mid_tone([THEME["bubble_low"], THEME["bubble_point"], THEME["bubble_high"], THEME["manhattan_sig"]]))
    return _extend(_mid_tone(palette_for(module)) or _mid_tone(SCI_DIST_COLORS))


def module_name_for(preview_stem: str) -> str | None:
    for meta in catalog.PLOTS.values():
        if meta.preview == preview_stem:
            return meta.name
    return None


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def is_neutral(value: str) -> bool:
    """灰阶、极黑、极白、以及低饱和度的结构色（轴/网格）都不参与替换。"""
    r, g, b = hex_to_rgb(value)
    if (max(r, g, b) - min(r, g, b)) <= 14:
        return True
    if _luminance(value) < 0.05 or _luminance(value) > 0.96:
        return True
    # 轴/网格常是低饱和蓝灰，替换成数据色会让预览脏掉
    return _saturation(value) < 0.30 and _luminance(value) > 0.30


def color_counts(text: str) -> collections.Counter:
    counter: collections.Counter = collections.Counter()
    for _, color in COLOR_RE.findall(text):
        counter[color.lower()] += 1
        counter[color] += 1
    # 同一颜色的大小写形式会各记一次，只保留原始写法里出现过的
    merged: collections.Counter = collections.Counter()
    seen: set[str] = set()
    for color, count in counter.most_common():
        key = color.lower()
        if key in seen:
            continue
        seen.add(key)
        merged[color] = count
    return merged


def _semantic_color(key: str) -> str:
    """取主题语义色；以 # 开头视为直接指定的颜色。"""
    if key.startswith("#"):
        return key
    if key == "heatmap_low_mid":
        return _mix(THEME["heatmap_low"], THEME["heatmap_mid"], 0.5)
    if key == "heatmap_high_mid":
        return _mix(THEME["heatmap_high"], THEME["heatmap_mid"], 0.5)
    return THEME.get(key, "#8A8F98")


def build_mapping(preview_stem: str, text: str) -> dict[str, str]:
    module = module_name_for(preview_stem) or ""
    palette = color_pool(preview_stem, module)
    overrides = SEMANTIC_OVERRIDES.get(preview_stem, {})

    mapping: dict[str, str] = {}
    used: set[str] = set()

    # 允许的目标色集合：语义色 + 色池；已是目标色的原样保留，保证脚本可重复执行
    allowed = {_semantic_color(key).lower() for key in overrides.values()}
    allowed.discard("")
    allowed.update(color.lower() for color in palette)

    # 1) 显式语义覆盖（大小写不敏感匹配）
    overrides_lower = {key.lower(): value for key, value in overrides.items()}
    for color in color_counts(text):
        key = color.lower()
        if key in overrides_lower:
            target = _semantic_color(overrides_lower[key])
            mapping[color] = target
            used.add(target.lower())

    # 2) 其余非中性色：按频次依次取色板颜色（跳过已用过的）
    index = 0
    for color in color_counts(text):
        if color in mapping or is_neutral(color):
            continue
        if color.lower() in allowed:
            # 已经是 SCI 目标色（脚本第二次运行时）
            used.add(color.lower())
            continue
        while index < len(palette) and palette[index].lower() in used:
            index += 1
        if index < len(palette):
            target = palette[index]
        else:
            # 色池用尽：基于已有色生成更浅/更深的变体，避免相邻重复
            overflow = index - len(palette)
            base = palette[overflow % len(palette)] if palette else "#8A8F98"
            target = _mix(base, "#FFFFFF", 0.42) if overflow < len(palette) else _mix(base, "#000000", 0.28)
        index += 1
        mapping[color] = target
        used.add(target.lower())

    return mapping


def apply_mapping(text: str, mapping: dict[str, str]) -> str:
    def replace(match: re.Match) -> str:
        attribute, color = match.group(1), match.group(2)
        for old, new in mapping.items():
            if color.lower() == old.lower():
                return f'{attribute}="{new}"'
        return match.group(0)

    return COLOR_RE.sub(replace, text)


# GMP 浅色底纹 → SCI 分组色的浅色调（在 _mix 定义之后追加）
SEMANTIC_OVERRIDES.setdefault("gmp", {})
SEMANTIC_OVERRIDES["gmp"].update(
    {
        "#fef3c7": _mix("#EBCB97", "#FFFFFF", 0.55),
        "#ede9fe": _mix("#B28F87", "#FFFFFF", 0.62),
        "#dbeafe": _mix("#669DBC", "#FFFFFF", 0.68),
        "#ccfbf1": _mix("#5BA790", "#FFFFFF", 0.70),
        "#c4b5fd": _mix("#93707B", "#FFFFFF", 0.58),
    }
)


def main() -> int:
    write = "--write" in sys.argv
    svg_files = sorted(PREVIEW_DIR.glob("*.svg"))
    if not svg_files:
        raise SystemExit(f"no svg under {PREVIEW_DIR}")

    problems: list[str] = []
    for path in svg_files:
        stem = path.stem
        original = path.read_text(encoding="utf-8")
        mapping = build_mapping(stem, original)
        updated = apply_mapping(original, mapping)

        # 结构校验：这些标记必须原样保留
        for marker in ('viewBox="0 0 400 240"', 'width="100%"', 'role="img"', "aria-label=", "var(--preview-bg"):
            if marker not in updated:
                problems.append(f"{path.name}: 丢失 {marker}")

        size = len(updated.encode("utf-8"))
        if size > MAX_BYTES:
            problems.append(f"{path.name}: {size} 字节 > {MAX_BYTES}")

        if write:
            path.write_text(updated, encoding="utf-8")

        module = module_name_for(stem) or "?"
        pairs = ", ".join(f"{old}→{new}" for old, new in list(mapping.items())[:6])
        print(f"{'WRITE' if write else 'DRY  '} {path.name:18s} {len(updated):5d}B  [{module}]  {pairs}")

    print()
    if problems:
        print("问题：")
        for item in problems:
            print(" -", item)
        return 1
    print(f"ok: {len(svg_files)} 个预览{'已写入' if write else '校验通过（未写入）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
