"""Paired Tree Comparison — two phylogenetic trees facing each other.

实现要点（原生 Plotly 实现）：
  - Newick / Nexus 解析（纯 Python，无 biopython 依赖）
  - ``branch.length = "none"`` 的等长枝矩形树（cladogram）布局
  - Tree 2 沿 X 轴镜像，两棵树的叶尖相对，中间留 ``tree_gap`` 间隙
  - 配对连线：直线或 S 形曲线
  - 分支 / 叶标签 / 叶节点点 / 内部节点编号的独立配色与尺寸
  - 可选分组文件（label, group[, color]）→ 按分组给分支与连线着色
  - 内部节点高亮（等价矩形）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES

HELP_TEXT = """
Paired Tree Comparison（双树比较）

输入：
  1. Tree 1 / Tree 2：Newick（.nwk / .newick）或 Nexus（.nexus / .nex）文件
  2. 配对表（可选）：CSV / TSV / XLSX，需含 tree1_label、tree2_label 两列
     - 不提供时按「两棵树中标签完全相同」的叶自动配对
  3. 分组表（可选）：CSV，需含 label、group 两列，可选 color 列
     - 也可勾选「启用示例分组」直接使用内置 A/B/C 三组

布局参数：
  - 等长枝矩形树（branch.length = "none"）：x = 祖先到该节点的边数
  - 叶节点自上而下按 Newick 中出现顺序排列，内部节点 y = 子节点均值
  - Tree 2 镜像：x' = 2 + gap - x，叶尖朝向 Tree 1，根在右侧
  - 两树垂直对齐可选「居中」或「顶部」
  - 「叶尖对齐」默认开启：等长枝布局下叶尖深度可能不一致，
    开启后把末端枝补到同一深度，叶尖与配对连线端点严格对齐（可关闭以保留原始深度）

连线样式：
  - 直线：两点一线
  - 曲线：x 方向余弦缓动 + y 方向线性，形成平滑的 S 形
  - 颜色优先级：Tree 2 分组色 → Tree 1 分组色 → 默认连线色

可配置项：
  - 两树间隙、两侧连线偏移、连线线型 / 颜色 / 粗细、标签对齐方式
  - 每棵树的分支颜色与粗细、叶标签颜色 / 大小 / 偏移
  - 叶节点点（Tree 1 圆形、Tree 2 菱形，对应 pch 21 / 23）的边框、填充、大小
  - 内部节点编号（颜色 / 大小）开关
  - 内部节点高亮：选节点编号 + 颜色 + 透明度 + 延伸长度

说明：
  - 节点编号规则：叶 = 1..N（按出现顺序），内部节点 = N+1 起按后序遍历编号
  - 分组着色时，某分支若其全部后代叶同属一组则取该组颜色，否则回落到默认分支色
"""

NONE_LABEL = "(无)"

GROUP_PALETTE = (
    "#E64B35",
    "#4DBBD5",
    "#00A087",
    "#3C5488",
    "#F39B7F",
    "#8491B4",
    "#91D1C2",
    "#DC0000",
    "#7E6148",
    "#B09C85",
)

_FALLBACK = {
    "bg": "#f5f7fb",
    "text": "#111827",
}


# ---------------------------------------------------------------------------
# Newick / Nexus parsing
# ---------------------------------------------------------------------------
@dataclass
class _Node:
    label: str = ""
    length: float = 0.0
    children: list = field(default_factory=list)
    parent: "_Node | None" = None
    x: float = 0.0
    y: float = 0.0
    number: int = 0
    color: str = ""
    y_min: float = 0.0
    y_max: float = 0.0


def _strip_comments(text: str) -> str:
    """去掉 Newick 的方括号注释，引号内的方括号保留。"""
    out: list[str] = []
    depth = 0
    in_quote = False
    for index, char in enumerate(text):
        if in_quote:
            out.append(char)
            if char == "'" and (index + 1 >= len(text) or text[index + 1] != "'"):
                in_quote = False
            continue
        if char == "'":
            in_quote = True
            out.append(char)
            continue
        if char == "[":
            depth += 1
            continue
        if char == "]":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(char)
    return "".join(out)


def _clean_newick(text: str) -> str:
    content = _strip_comments(text or "")
    match = re.search(r"\btree\b[^=]*=\s*([^;]+)", content, re.IGNORECASE | re.DOTALL)
    if match and "(" in match.group(1):
        content = match.group(1)
    if "(" not in content:
        raise ValueError("未找到 Newick 结构（缺少括号），请确认文件为 Newick / Nexus 格式")
    return content[content.index("(") : content.rindex(")") + 1]


def parse_newick(text: str) -> _Node:
    """递归下降解析 Newick；支持引号标签、内部节点支持率与枝长。"""
    source = _clean_newick(text)
    pos = 0
    total = len(source)

    def skip_ws() -> None:
        nonlocal pos
        while pos < total and source[pos].isspace():
            pos += 1

    def read_label() -> str:
        nonlocal pos
        skip_ws()
        if pos < total and source[pos] == "'":
            pos += 1
            buffer: list[str] = []
            while pos < total:
                char = source[pos]
                if char == "'":
                    if pos + 1 < total and source[pos + 1] == "'":
                        buffer.append("'")
                        pos += 2
                        continue
                    pos += 1
                    break
                buffer.append(char)
                pos += 1
            return "".join(buffer)
        start = pos
        while pos < total and source[pos] not in "(),:;" and not source[pos].isspace():
            pos += 1
        return source[start:pos]

    def read_number() -> float:
        nonlocal pos
        skip_ws()
        start = pos
        while pos < total and source[pos] not in "(),;" and not source[pos].isspace():
            pos += 1
        try:
            return float(source[start:pos])
        except ValueError:
            return 0.0

    def parse_clade() -> _Node:
        nonlocal pos
        skip_ws()
        node = _Node()
        if pos < total and source[pos] == "(":
            pos += 1
            while True:
                child = parse_clade()
                child.parent = node
                node.children.append(child)
                skip_ws()
                if pos < total and source[pos] == ",":
                    pos += 1
                    continue
                if pos < total and source[pos] == ")":
                    pos += 1
                    break
                raise ValueError("Newick 括号不匹配，请检查文件是否完整")
            node.label = read_label()
        else:
            node.label = read_label()
        skip_ws()
        if pos < total and source[pos] == ":":
            pos += 1
            node.length = read_number()
        return node

    return parse_clade()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
def _preorder(root: _Node) -> list[_Node]:
    nodes: list[_Node] = []
    stack = [root]
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(reversed(node.children))
    return nodes


def _postorder(root: _Node) -> list[_Node]:
    nodes: list[_Node] = []

    def walk(node: _Node) -> None:
        for child in node.children:
            walk(child)
        nodes.append(node)

    walk(root)
    return nodes


def layout_tree(root: _Node, by_branch_length: bool = False) -> tuple[list[_Node], list[_Node], float]:
    """等长枝（或按枝长）矩形布局，返回 (全部节点, 叶节点, 最大 x)。"""

    def walk(node: _Node, x: float) -> None:
        node.x = x
        for child in node.children:
            step = child.length if by_branch_length else 1.0
            if not np.isfinite(step) or step <= 0:
                step = 1.0
            walk(child, x + step)

    walk(root, 0.0)

    leaves = [node for node in _preorder(root) if not node.children]
    total = len(leaves)
    for index, leaf in enumerate(leaves):
        leaf.y = float(total - 1 - index)

    def assign_internal(node: _Node) -> None:
        if node.children:
            for child in node.children:
                assign_internal(child)
            node.y = float(np.mean([child.y for child in node.children]))

    assign_internal(root)

    # 节点编号：叶 1..N，内部节点 N+1 起按后序遍历
    for index, leaf in enumerate(leaves):
        leaf.number = index + 1
    internals = [node for node in _postorder(root) if node.children]
    for offset, node in enumerate(internals):
        node.number = total + offset + 1

    # 每个节点覆盖的叶 y 区间（高亮矩形用）
    def span(node: _Node) -> tuple[float, float]:
        if not node.children:
            node.y_min = node.y_max = node.y
        else:
            spans = [span(child) for child in node.children]
            node.y_min = min(item[0] for item in spans)
            node.y_max = max(item[1] for item in spans)
        return node.y_min, node.y_max

    span(root)
    max_x = max(node.x for node in _preorder(root)) if root.children else 1.0
    return _preorder(root), leaves, max(max_x, 1.0)


def _apply_group_colors(root: _Node, label_color: dict[str, str], default_color: str) -> None:
    """自底向上：若某节点的全部后代叶同属一组，则该节点使用该组颜色。"""

    def walk(node: _Node) -> set[str]:
        if not node.children:
            color = label_color.get(node.label)
            node.color = color or default_color
            return {color} if color else set()
        merged: set[str] = set()
        for child in node.children:
            merged |= walk(child)
        node.color = next(iter(merged)) if len(merged) == 1 else default_color
        return merged

    walk(root)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _theme() -> dict:
    return THEMES.get(st.session_state.get("theme", "Light"), THEMES["Light"])


def _theme_color(key: str) -> str:
    return _theme().get(key, _FALLBACK.get(key, "#111827"))


def _read_tree_text(sample_key: str, upload_key: str) -> tuple[str, str]:
    if st.session_state.get("pt_use_sample", True):
        try:
            return get_sample_path(sample_key).read_text(encoding="utf-8"), ""
        except Exception as exc:  # pragma: no cover - filesystem guard
            return "", f"示例文件读取失败：{exc}"
    uploaded = st.session_state.get(upload_key)
    if uploaded is None:
        return "", "请先上传树文件，或在左侧勾选「使用示例数据」。"
    raw = uploaded.read()
    try:
        uploaded.seek(0)
    except Exception:
        pass
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace"), ""
    return str(raw), ""


def _read_pairing() -> tuple[pd.DataFrame | None, str]:
    if st.session_state.get("pt_use_sample", True):
        try:
            path = get_sample_path("pt_pairing")
            return read_table(path, path.name), ""
        except Exception as exc:  # pragma: no cover
            return None, f"示例配对表读取失败：{exc}"
    uploaded = st.session_state.get("pt_pair_file")
    if uploaded is None:
        return None, ""
    try:
        frame = read_table(uploaded, getattr(uploaded, "name", "pairing.csv"))
    except Exception as exc:
        return None, f"配对表解析失败：{exc}"
    return frame, ""


def _read_groups() -> tuple[dict[str, str], str]:
    """返回 label -> color 映射；组颜色优先取文件的 color 列，否则按组序取调色板。"""
    frame: pd.DataFrame | None = None
    if st.session_state.get("pt_use_group_sample", False):
        try:
            path = get_sample_path("pt_groups")
            frame = read_table(path, path.name)
        except Exception as exc:  # pragma: no cover
            return {}, f"示例分组读取失败：{exc}"
    elif st.session_state.get("pt_group_file") is not None:
        uploaded = st.session_state.get("pt_group_file")
        try:
            frame = read_table(uploaded, getattr(uploaded, "name", "groups.csv"))
        except Exception as exc:
            return {}, f"分组表解析失败：{exc}"

    if frame is None or frame.empty:
        return {}, ""

    columns = {str(c).strip().lower(): str(c) for c in frame.columns}
    label_col = columns.get("label") or columns.get("tip") or columns.get("name")
    group_col = columns.get("group") or columns.get("cluster")
    if label_col is None or group_col is None:
        return {}, "分组表需要包含 label 与 group 两列（可选 color 列）。"
    color_col = columns.get("color") or columns.get("colour")

    group_order: list[str] = []
    group_color: dict[str, str] = {}
    for _, row in frame.iterrows():
        group = str(row[group_col]).strip()
        if not group or group.lower() == "nan":
            continue
        if group not in group_order:
            group_order.append(group)
            explicit = str(row[color_col]).strip() if color_col else ""
            group_color[group] = explicit if explicit.startswith("#") else GROUP_PALETTE[len(group_order) - 1]

    mapping: dict[str, str] = {}
    for _, row in frame.iterrows():
        group = str(row[group_col]).strip()
        label = str(row[label_col]).strip()
        if label and group in group_color:
            mapping[label] = group_color[group]
    return mapping, ""


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
def _pick_paths() -> tuple[_Node | None, _Node | None, list[_Node], list[_Node], float, float, str]:
    text1, error1 = _read_tree_text("pt_tree1", "pt_file1")
    text2, error2 = _read_tree_text("pt_tree2", "pt_file2")
    if error1 or error2:
        return None, None, [], [], 1.0, 1.0, error1 or error2
    try:
        root1 = parse_newick(text1)
        root2 = parse_newick(text2)
    except Exception as exc:
        return None, None, [], [], 1.0, 1.0, f"树文件解析失败：{exc}"
    _, leaves1, max1 = layout_tree(root1)
    _, leaves2, max2 = layout_tree(root2)
    if len(leaves1) < 2 or len(leaves2) < 2:
        return root1, root2, leaves1, leaves2, max1, max2, "每棵树至少需要 2 个叶节点。"
    return root1, root2, leaves1, leaves2, max1, max2, ""


def _multi(label: str, options: list[str], key: str) -> list[str]:
    if key in st.session_state:
        st.session_state[key] = [value for value in st.session_state[key] if value in options]
    return st.multiselect(label, options, key=key)


def controls(shared: dict) -> None:
    st.markdown("### 数据")
    sample_loader_control(
        "pt_use_sample",
        ["pt_tree1", "pt_tree2", "pt_pairing", "pt_groups"],
        "pt_load_sample_btn",
    )
    if not st.session_state.get("pt_use_sample", True):
        st.file_uploader(
            "Tree 1（Newick / Nexus）",
            type=["nwk", "newick", "nexus", "nex", "tree", "txt"],
            key="pt_file1",
        )
        st.file_uploader(
            "Tree 2（Newick / Nexus）",
            type=["nwk", "newick", "nexus", "nex", "tree", "txt"],
            key="pt_file2",
        )
        st.file_uploader(
            "配对表（tree1_label / tree2_label）",
            type=["csv", "tsv", "txt", "xlsx"],
            key="pt_pair_file",
        )

    root1, root2, leaves1, leaves2, max1, max2, error = _pick_paths()
    if error:
        st.info(error)
        return

    st.caption(f"Tree 1：{len(leaves1)} 叶 / 深度 {max1:g}　·　Tree 2：{len(leaves2)} 叶 / 深度 {max2:g}")

    st.markdown("### 分组着色")
    st.checkbox("启用示例分组（A / B / C 三组）", value=False, key="pt_use_group_sample")
    if not st.session_state.get("pt_use_group_sample", False):
        st.file_uploader("分组表（label / group，可选 color）", type=["csv", "tsv", "txt"], key="pt_group_file")
    mapping, group_error = _read_groups()
    if group_error:
        st.warning(group_error)
    elif mapping:
        st.caption(f"已匹配 {len(mapping)} 个叶标签的分组颜色")

    st.markdown("### 连线")
    st.number_input("两树间隙（X 轴）", min_value=1, max_value=20, value=5, step=1, key="pt_tree_gap")
    st.slider("Tree 1 连线偏移", 0.0, 2.0, 0.2, 0.05, key="pt_conn_offset1")
    st.slider("Tree 2 连线偏移", 0.0, 2.0, 0.2, 0.05, key="pt_conn_offset2")
    st.selectbox("连接线型", ["曲线（Curve）", "直线（Straight）"], index=0, key="pt_conn_style")
    st.color_picker("连线默认颜色", "#555555", key="pt_line_color")
    st.slider("连线粗细", 0.1, 3.0, 0.5, 0.1, key="pt_conn_width")
    st.selectbox("标签对齐", ["贴紧叶节点", "统一对齐", "不显示"], index=0, key="pt_align_tips")
    st.selectbox("两树垂直对齐", ["居中", "顶部"], index=0, key="pt_valign")
    st.checkbox(
        "叶尖对齐（补齐末端枝）",
        value=True,
        key="pt_tip_align",
        help="等长枝布局下叶尖会停在各自深度上；勾选后把末端枝补到同一深度，叶尖严格对齐。",
    )

    for tree_index, default_branch in ((1, "#0099CC"), (2, "#CC6600")):
        st.markdown(f"### Tree {tree_index} 外观")
        st.color_picker("分支颜色", default_branch, key=f"pt_branch_color{tree_index}")
        st.slider("分支粗细", 0.1, 3.0, 1.0, 0.1, key=f"pt_branch_size{tree_index}")
        st.color_picker("标签颜色", "#000000", key=f"pt_label_color{tree_index}")
        st.slider("标签大小", 1.0, 8.0, 3.0, 0.5, key=f"pt_label_size{tree_index}")
        st.slider("标签偏移", 0.0, 2.0, 0.2, 0.1, key=f"pt_label_offset{tree_index}")
        st.color_picker("点边框色", "#000000", key=f"pt_point_color{tree_index}")
        st.color_picker("点填充色", "#FFFFFF", key=f"pt_point_fill_color{tree_index}")
        st.slider("点大小", 0.0, 5.0, 3.0, 0.5, key=f"pt_point_size{tree_index}")
        st.checkbox("显示内部节点编号", value=False, key=f"pt_show_nodes{tree_index}")
        if st.session_state.get(f"pt_show_nodes{tree_index}", False):
            # 默认分别是 red / blue，这里换成等价的十六进制
            st.color_picker(
                "编号颜色",
                "#FF0000" if tree_index == 1 else "#0000FF",
                key=f"pt_node_color{tree_index}",
            )
            st.slider("编号大小", 1.0, 5.0, 3.0, 0.5, key=f"pt_node_size{tree_index}")

    st.markdown("### 标题")
    st.checkbox("添加图形标题", value=False, key="pt_add_title")
    if st.session_state.get("pt_add_title", False):
        st.text_input("图形标题", "Paired Tree Comparison", key="pt_title")


def advanced_controls(shared: dict) -> None:
    """Paired Tree 的高级参数：内部节点高亮。"""
    root1, root2, _leaves1, _leaves2, _max1, _max2, error = _pick_paths()
    if error or root1 is None or root2 is None:
        return
    st.markdown("### 内部节点高亮")
    for tree_index, root in ((1, root1), (2, root2)):
        options = [
            str(node.number)
            for node in _preorder(root)
            if node.children and node.y_max - node.y_min >= 1
        ]
        selected = _multi(f"Tree {tree_index} 高亮节点编号", options, f"pt_hl_nodes{tree_index}")
        for number in selected:
            st.color_picker(f"节点 {number} 颜色", "#FF0000", key=f"pt_hl_color{tree_index}_{number}")
        st.slider("高亮透明度", 0.0, 1.0, 0.5, 0.1, key=f"pt_hl_alpha{tree_index}")
        st.slider("高亮延伸长度", 0.0, 5.0, 1.0, 0.1, key=f"pt_hl_extent{tree_index}")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def _segments(
    nodes: list[_Node], max_x: float, align_tips: bool = True
) -> list[tuple[float, float, float, float, str]]:
    """矩形树线段：竖直段（节点跨度）+ 水平段（节点→子节点），附带颜色。"""
    out: list[tuple[float, float, float, float, str]] = []
    for node in nodes:
        if node.children:
            ys = [child.y for child in node.children]
            out.append((node.x, min(ys), node.x, max(ys), node.color))
        for child in node.children:
            out.append((node.x, child.y, child.x, child.y, child.color))
        if not node.children and align_tips and node.x < max_x:
            # 末端枝补齐到同一深度，让两侧叶尖严格对齐
            out.append((node.x, node.y, max_x, node.y, node.color))
    return out


def _bump_curve(x1: float, y1: float, x2: float, y2: float, samples: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """平滑 S 形：水平方向余弦缓动，垂直方向线性。"""
    ts = np.linspace(0.0, 1.0, samples)
    xs = x1 + (x2 - x1) * (0.5 - 0.5 * np.cos(np.pi * ts))
    ys = y1 + (y2 - y1) * ts
    return xs, ys


def build(shared: dict):
    theme = _theme()
    root1, root2, leaves1, leaves2, max1, max2, error = _pick_paths()
    if error:
        return None, None, error, HELP_TEXT

    pairing, pairing_error = _read_pairing()
    if pairing_error:
        return None, None, pairing_error, HELP_TEXT

    group_map, group_error = _read_groups()
    if group_error:
        return None, None, group_error, HELP_TEXT

    # ---------- 参数 ----------
    gap_units = float(st.session_state.get("pt_tree_gap", 5))
    gap = gap_units / max1  # 归一化到 Tree 1 的深度单位（x 轴间隙）
    dist1 = float(st.session_state.get("pt_conn_offset1", 0.2)) / max1
    dist2 = float(st.session_state.get("pt_conn_offset2", 0.2)) / max2
    curve_flag = str(st.session_state.get("pt_conn_style", "曲线（Curve）")).startswith("曲线")
    line_color = st.session_state.get("pt_line_color") or "#555555"
    line_width = max(0.5, float(st.session_state.get("pt_conn_width", 0.5)) * 1.8)
    align_mode = st.session_state.get("pt_align_tips", "贴紧叶节点")
    valign = st.session_state.get("pt_valign", "居中")
    align_tips = bool(st.session_state.get("pt_tip_align", True))

    style: dict[int, dict] = {}
    for index, default_branch in ((1, "#0099CC"), (2, "#CC6600")):
        style[index] = {
            "branch": st.session_state.get(f"pt_branch_color{index}") or default_branch,
            "branch_w": max(0.6, float(st.session_state.get(f"pt_branch_size{index}", 1.0)) * 1.7),
            "label": st.session_state.get(f"pt_label_color{index}") or "#000000",
            "label_px": float(st.session_state.get(f"pt_label_size{index}", 3.0)) * 3.4,
            "label_off": float(st.session_state.get(f"pt_label_offset{index}", 0.2)),
            "point": st.session_state.get(f"pt_point_color{index}") or "#000000",
            "fill": st.session_state.get(f"pt_point_fill_color{index}") or "#FFFFFF",
            "point_px": max(2.0, float(st.session_state.get(f"pt_point_size{index}", 3.0)) * 3.0),
            "show_nodes": bool(st.session_state.get(f"pt_show_nodes{index}", False)),
            "node_color": st.session_state.get(f"pt_node_color{index}") or ("#FF0000" if index == 1 else "#0000FF"),
            "node_px": float(st.session_state.get(f"pt_node_size{index}", 3.0)) * 3.2,
        }

    _apply_group_colors(root1, group_map, style[1]["branch"])
    _apply_group_colors(root2, group_map, style[2]["branch"])

    nodes1 = _preorder(root1)
    nodes2 = _preorder(root2)

    # ---------- 坐标映射 ----------
    def fx1(value: float) -> float:
        return value / max1

    def fx2(value: float) -> float:
        return 2.0 + gap - value / max2

    shift = (len(leaves1) - len(leaves2)) / 2.0 if valign == "居中" else float(len(leaves1) - len(leaves2))
    if shift < 0:
        shift = 0.0

    tips1 = {leaf.label: leaf for leaf in leaves1}
    tips2 = {leaf.label: leaf for leaf in leaves2}

    # ---------- 配对 ----------
    pairs: list[tuple[str, str]] = []
    if pairing is not None and not pairing.empty:
        columns = {str(c).strip().lower(): str(c) for c in pairing.columns}
        left_col = columns.get("tree1_label") or columns.get("label1")
        right_col = columns.get("tree2_label") or columns.get("label2")
        if left_col is None or right_col is None:
            return None, None, "配对表需要包含 tree1_label 与 tree2_label 两列。", HELP_TEXT
        for left_label, right_label in zip(pairing[left_col], pairing[right_col]):
            left_text = str(left_label).strip()
            right_text = str(right_label).strip()
            if left_text in tips1 and right_text in tips2:
                pairs.append((left_text, right_text))
    else:
        pairs = [(label, label) for label in tips1 if label in tips2]

    if not pairs:
        return None, None, "没有可用的配对（请检查配对表标签是否与树中叶标签一致）。", HELP_TEXT

    # ---------- 图 ----------
    fig = go.Figure()

    # 1) 内部节点高亮（画在最底层）
    for tree_index, nodes, mapper in ((1, nodes1, fx1), (2, nodes2, fx2)):
        selected = st.session_state.get(f"pt_hl_nodes{tree_index}", []) or []
        alpha = float(st.session_state.get(f"pt_hl_alpha{tree_index}", 0.5))
        extent = float(st.session_state.get(f"pt_hl_extent{tree_index}", 1.0))
        for number in selected:
            node = next((item for item in nodes if str(item.number) == str(number)), None)
            if node is None:
                continue
            color = st.session_state.get(f"pt_hl_color{tree_index}_{number}") or "#FF0000"
            if tree_index == 1:
                x0, x1 = mapper(node.x), 1.0 + extent / max1
            else:
                x0, x1 = mapper(node.x), (1.0 + gap) - extent / max2
            y0 = node.y_min - 0.5 + (shift if tree_index == 2 else 0.0)
            y1 = node.y_max + 0.5 + (shift if tree_index == 2 else 0.0)
            fig.add_shape(
                type="rect",
                x0=min(x0, x1),
                x1=max(x0, x1),
                y0=y0,
                y1=y1,
                fillcolor=color,
                opacity=alpha,
                line=dict(width=0),
                layer="below",
            )

    # 2) 配对连线（在分支下层，先画）
    #    连线端点在叶标签外侧起画，避免线段压住标签文字（标签隐藏时不额外让位）
    units_per_px = (2.0 + gap) / 900.0

    def label_pad(text: str, font_px: float) -> float:
        if align_mode == "不显示":
            return 0.0
        return (0.58 * font_px * len(str(text)) + 6.0) * units_per_px

    line_groups: dict[str, tuple[list, list]] = {}
    for left_label, right_label in pairs:
        leaf1 = tips1[left_label]
        leaf2 = tips2[right_label]
        tip_x1 = 1.0 if align_tips else fx1(leaf1.x)
        tip_x2 = (1.0 + gap) if align_tips else fx2(leaf2.x)
        x1 = tip_x1 + dist1 + label_pad(left_label, style[1]["label_px"])
        y1 = leaf1.y
        x2 = tip_x2 - dist2 - label_pad(right_label, style[2]["label_px"])
        y2 = leaf2.y + shift

        color2 = group_map.get(right_label)
        color1 = group_map.get(left_label)
        if color2 and color2 != style[2]["branch"]:
            color = color2
        elif color1 and color1 != style[1]["branch"]:
            color = color1
        else:
            color = line_color

        xs, ys = line_groups.setdefault(color, ([], []))
        if curve_flag and abs(y1 - y2) > 1e-9:
            cx, cy = _bump_curve(x1, y1, x2, y2)
            xs.extend([*cx, None])
            ys.extend([*cy, None])
        else:
            xs.extend([x1, x2, None])
            ys.extend([y1, y2, None])

    for color, (xs, ys) in line_groups.items():
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                line=dict(color=color, width=line_width),
                opacity=0.9,
                hoverinfo="skip",
                showlegend=False,
            )
        )

    # 3) 分支
    for tree_index, nodes, mapper, max_x in ((1, nodes1, fx1, max1), (2, nodes2, fx2, max2)):
        y_shift = shift if tree_index == 2 else 0.0
        groups: dict[str, tuple[list, list]] = {}
        width = style[tree_index]["branch_w"]
        for x0, y0, x1, y1, color in _segments(nodes, max_x, align_tips):
            xs, ys = groups.setdefault(f"{color}|{width}", ([], []))
            xs.extend([mapper(x0), mapper(x1), None])
            ys.extend([y0 + y_shift, y1 + y_shift, None])
        for key, (xs, ys) in groups.items():
            color, width_text = key.split("|")
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    line=dict(color=color, width=float(width_text)),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    # 4) 叶节点点
    for tree_index, leaves, mapper in ((1, leaves1, fx1), (2, leaves2, fx2)):
        y_shift = shift if tree_index == 2 else 0.0
        if align_tips:
            tip_xs = [1.0 if tree_index == 1 else (1.0 + gap)] * len(leaves)
        else:
            tip_xs = [mapper(leaf.x) for leaf in leaves]
        fig.add_trace(
            go.Scatter(
                x=tip_xs,
                y=[leaf.y + y_shift for leaf in leaves],
                mode="markers",
                marker=dict(
                    symbol="circle" if tree_index == 1 else "diamond",
                    size=style[tree_index]["point_px"],
                    color=style[tree_index]["fill"],
                    line=dict(color=style[tree_index]["point"], width=1),
                ),
                text=[leaf.label for leaf in leaves],
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            )
        )

    # 5) 内部节点编号
    for tree_index, nodes, mapper in ((1, nodes1, fx1), (2, nodes2, fx2)):
        if not style[tree_index]["show_nodes"]:
            continue
        y_shift = shift if tree_index == 2 else 0.0
        subset = [node for node in nodes if node.children]
        if not subset:
            continue
        fig.add_trace(
            go.Scatter(
                x=[mapper(node.x) for node in subset],
                y=[node.y + y_shift for node in subset],
                mode="text",
                text=[str(node.number) for node in subset],
                textposition="middle right" if tree_index == 1 else "middle left",
                textfont=dict(size=style[tree_index]["node_px"], color=style[tree_index]["node_color"]),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    # 6) 叶标签（最后画，压在连线之上）
    if align_mode != "不显示":
        for tree_index, leaves, mapper, anchor in (
            (1, leaves1, fx1, 1.0),
            (2, leaves2, fx2, 1.0 + gap),
        ):
            y_shift = shift if tree_index == 2 else 0.0
            offset = style[tree_index]["label_off"] / (max1 if tree_index == 1 else max2)
            if align_tips:
                base_xs = [1.0 if tree_index == 1 else (1.0 + gap)] * len(leaves)
            else:
                base_xs = [mapper(leaf.x) for leaf in leaves]
            if align_mode == "统一对齐":
                anchor = 1.0 if tree_index == 1 else (1.0 + gap)
                xs = [anchor + offset if tree_index == 1 else anchor - offset] * len(leaves)
            else:
                xs = [
                    base + offset if tree_index == 1 else base - offset
                    for base in base_xs
                ]
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=[leaf.y + y_shift for leaf in leaves],
                    mode="text",
                    text=[leaf.label for leaf in leaves],
                    textposition="middle right" if tree_index == 1 else "middle left",
                    textfont=dict(size=style[tree_index]["label_px"], color=style[tree_index]["label"]),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    # ---------- 布局 ----------
    add_title = bool(st.session_state.get("pt_add_title", False))
    title = (st.session_state.get("pt_title") or "Paired Tree Comparison") if add_title else ""
    text_color = theme.get("text", _FALLBACK["text"])
    max_tips = max(len(leaves1), len(leaves2))
    height = int(min(1500, max(560, 24 * max_tips)))

    y_low = min(node.y for node in nodes1) - 1.0
    y_high = max(node.y for node in nodes2) + shift + 1.0

    fig.update_layout(
        height=height,
        plot_bgcolor=theme.get("bg", _FALLBACK["bg"]),
        paper_bgcolor=theme.get("bg", _FALLBACK["bg"]),
        font=dict(color=text_color),
        margin=dict(l=10, r=10, t=60 if title else 20, b=10),
        hovermode="closest",
        showlegend=False,
    )
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=17, color=text_color)))
    fig.update_xaxes(
        visible=False,
        range=[-0.03, 2.0 + gap + 0.03],
        fixedrange=False,
    )
    fig.update_yaxes(
        visible=False,
        range=[y_low, y_high],
        fixedrange=False,
    )

    # ---------- 数据预览 ----------
    preview = pd.DataFrame(
        {
            "tree1_label": [left for left, _ in pairs],
            "tree2_label": [right for _, right in pairs],
        }
    )
    preview["tree1_y"] = [tips1[left].y for left, _ in pairs]
    preview["tree2_y"] = [tips2[right].y + shift for _, right in pairs]

    shared["last_plotly"] = fig
    shared["data"] = preview
    matched = len(pairs)
    status = (
        f"双树比较就绪：Tree 1 {len(leaves1)} 叶 / Tree 2 {len(leaves2)} 叶；"
        f"配对连线 {matched} 条"
    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, preview, status, HELP_TEXT


def render(shared: dict):
    controls(shared)
    return build(shared)


__call__ = render
