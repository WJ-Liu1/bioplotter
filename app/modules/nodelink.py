from __future__ import annotations

import io
from math import cos, sin, pi, degrees
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_bytes, sample_loader_control
from app.core.theme import THEMES

HELP_TEXT = """
Node-link Diagram (Plotly 交互版本)

支持输入：
  1. 边表数据
     - 必须包含列：from, to, value
     - color 列可选
  2. 矩阵数据
     - 行为节点，列为节点，单元格为连接权重
功能：
  - 支持 自动识别 / 边表 / 矩阵 三种读取模式
  - 自动将矩阵转换为边表后绘制 Node-link Diagram
  - 圆形层级 node-link 布局
  - 自定义 hub 节点
  - 调整连线粗细、透明度、弯曲程度
  - 分别设置外层与内层节点、标签、数值显示
说明：
  - 本模块使用 Plotly 实现，支持缩放、悬停等交互
  - 视觉效果接近经典圆形树状网络图
"""

SHAPE_MAP = {
    "circle": "circle",
    "square": "square",
    "lozenge": "diamond",
    "Regular triangle": "triangle-up",
    "Inverted triangle": "triangle-down",
}

DEFAULT_EDGE_COLOR = "#5BF0EB"  # 默认连线颜色

# 颜色名映射（将非标准 CSS 颜色名转换为十六进制）
COLOR_NAME_MAP = {
    # 这里使用经典绘图色板取值，而不是 CSS 取值，
    # 以便与常见的网络节点配色保持一致。
    "springgreen4": "#008B45",
    "springgreen3": "#00CD7F",
    "springgreen2": "#00EE76",
    "springgreen1": "#00FF7F",
    "gray": "#BEBEBE",
    "grey": "#BEBEBE",
    "grey50": "#7F7F7F",
    "gray50": "#7F7F7F",
    "lightgray": "#D3D3D3",
    "lightgrey": "#D3D3D3",
    "darkgray": "#A9A9A9",
    "darkgrey": "#A9A9A9",
    "black": "#000000",
    "white": "#FFFFFF",
    "red": "#FF0000",
    "green": "#00FF00",
    "blue": "#0000FF",
    "yellow": "#FFFF00",
    "orange": "#FFA500",
    "purple": "#A020F0",
    "pink": "#FFC0CB",
    "hotpink": "#FF69B4",
    "brown": "#A52A2A",
    "cyan": "#00FFFF",
    "magenta": "#FF00FF",
    "navy": "#000080",
    "teal": "#008080",
    "olive": "#808000",
    "maroon": "#800000",
    "silver": "#C0C0C0",
    "gold": "#FFD700",
    "violet": "#EE82EE",
    "indigo": "#4B0082",
    "tomato": "#FF6347",
    "coral": "#FF7F50",
    "salmon": "#FA8072",
    "khaki": "#F0E68C",
    "plum": "#DDA0DD",
    "orchid": "#DA70D6",
    "thistle": "#D8BFD8",
    "peru": "#CD853F",
    "sandybrown": "#F4A460",
    "chocolate": "#D2691E",
    "sienna": "#A0522D",
    "rosybrown": "#BC8F8F",
    "moccasin": "#FFE4B5",
    "navajowhite": "#FFDEAD",
    "peachpuff": "#FFDAB9",
    "mistyrose": "#FFE4E1",
    "lavender": "#E6E6FA",
    "linen": "#FAF0E6",
    "antiquewhite": "#FAEBD7",
    "beige": "#F5F5DC",
    "wheat": "#F5DEB3",
    "burlywood": "#DEB887",
    "tan": "#D2B48C",
    "lightcyan": "#E0FFFF",
    "aliceblue": "#F0F8FF",
    "azure": "#F0FFFF",
    "honeydew": "#F0FFF0",
    "ivory": "#FFFFF0",
    "floralwhite": "#FFFAF0",
    "seashell": "#FFF5EE",
    "oldlace": "#FDF5E6",
    "snow": "#FFFAFA",
    "ghostwhite": "#F8F8FF",
}


def _safe_color(c, default):
    """将颜色值转换为 Plotly 可接受的格式"""
    if c is None:
        return default
    if isinstance(c, float) and np.isnan(c):
        return default
    if isinstance(c, str):
        c_stripped = c.strip().lower()
        if c_stripped == 'nan':
            return default
        if c_stripped in COLOR_NAME_MAP:
            return COLOR_NAME_MAP[c_stripped]
        if c_stripped.startswith('#'):
            return c_stripped
        # 如果是标准 CSS 颜色名（不带数字后缀），Plotly 可能支持，直接返回
        # 但为了安全，可以进一步检查，这里直接返回原值
        return c_stripped
    return default


def _color_with_alpha(color, alpha):
    """将颜色字符串（十六进制）转换为 rgba 字符串，添加 alpha 通道"""
    if alpha >= 1.0:
        return color
    if color.startswith('#'):
        r = int(color[1:3], 16) / 255.0
        g = int(color[3:5], 16) / 255.0
        b = int(color[5:7], 16) / 255.0
        return f"rgba({r*255:.0f}, {g*255:.0f}, {b*255:.0f}, {alpha})"
    # 对于非十六进制颜色，简单返回原色
    return color


# -----------------------------
# 数据清洗 / 格式识别（与原版完全相同）
# -----------------------------
def _clean_text(x) -> str:
    return str(x).replace("\ufeff", "").strip()


def _is_probably_numeric_series(s: pd.Series, threshold: float = 0.8) -> bool:
    if s is None or len(s) == 0:
        return False
    test = pd.to_numeric(s, errors="coerce")
    return bool(test.notna().mean() >= threshold)


def _normalize_nodelink_edgelist(df: pd.DataFrame, default_color: str = DEFAULT_EDGE_COLOR) -> pd.DataFrame:
    work = df.copy()
    work.columns = [_clean_text(c).lower() for c in work.columns]

    rename_map = {}
    for c in work.columns:
        if c in {"from", "source", "src", "start", "parent"}:
            rename_map[c] = "from"
        elif c in {"to", "target", "dst", "end", "child"}:
            rename_map[c] = "to"
        elif c in {"value", "weight", "weights", "score"}:
            rename_map[c] = "value"
        elif c in {"color", "colour", "col"}:
            rename_map[c] = "color"
    if rename_map:
        work = work.rename(columns=rename_map)

    if {"from", "to"}.issubset(set(work.columns)):
        if "value" not in work.columns:
            other_cols = [c for c in work.columns if c not in {"from", "to"}]
            if other_cols:
                work = work.rename(columns={other_cols[0]: "value"})
            else:
                work["value"] = 1

        if "color" not in work.columns:
            other_cols = [c for c in work.columns if c not in {"from", "to", "value"}]
            if other_cols:
                work = work.rename(columns={other_cols[0]: "color"})
            else:
                work["color"] = default_color

        out = work[["from", "to", "value", "color"]].copy()
    else:
        if work.shape[1] < 3:
            raise ValueError("边表至少需要 3 列：from、to、value；color 可选。")

        if work.shape[1] >= 4:
            out = work.iloc[:, :4].copy()
            out.columns = ["from", "to", "value", "color"]
        else:
            out = work.iloc[:, :3].copy()
            out.columns = ["from", "to", "value"]
            out["color"] = default_color

    out["from"] = out["from"].astype(str).map(_clean_text)
    out["to"] = out["to"].astype(str).map(_clean_text)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["color"] = out["color"].astype(str).map(_clean_text)

    out = out.dropna(subset=["value"])
    out = out[(out["value"] > 0) & (out["from"] != "") & (out["to"] != "")]
    out = out[out["from"] != out["to"]].copy()

    out.loc[out["color"].eq("") | out["color"].isna(), "color"] = default_color

    if out.empty:
        raise ValueError("有效边数据为空，请检查输入文件。")
    return out.reset_index(drop=True)


def _matrix_to_nodelink_edgelist(raw_df: pd.DataFrame, default_color: str = DEFAULT_EDGE_COLOR) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = raw_df.copy()
    work.columns = [_clean_text(c) for c in work.columns]

    if work.shape[0] == 0 or work.shape[1] < 2:
        raise ValueError("矩阵格式至少需要 2 列（第 1 列通常为行名，其余为节点列）。")

    first_col = work.columns[0]
    first_series = work[first_col]
    first_col_name = _clean_text(first_col).lower()

    first_col_is_label = (
        first_col_name in {"", "unnamed: 0", "unnamed", "name", "node", "nodes", "id", "label"}
        or (not _is_probably_numeric_series(first_series))
    )

    if first_col_is_label:
        work = work.set_index(first_col)
    else:
        if isinstance(work.index, pd.RangeIndex):
            raise ValueError("矩阵格式建议第一列为节点名（行名），当前未识别到有效行名列。")

    work.index = [_clean_text(x) for x in work.index]
    work.columns = [_clean_text(c) for c in work.columns]

    row_mask = [x != "" and x.lower() != "nan" for x in work.index]
    col_mask = [x != "" and x.lower() != "nan" for x in work.columns]
    work = work.loc[row_mask, col_mask]

    if work.empty:
        raise ValueError("矩阵在清洗后为空。")

    for col in work.columns:
        work[col] = pd.to_numeric(work[col], errors="coerce")

    work = work.dropna(axis=0, how="all").dropna(axis=1, how="all").fillna(0)
    if work.empty:
        raise ValueError("矩阵中没有可用数值。")

    edges = work.stack().reset_index()
    edges.columns = ["from", "to", "value"]
    edges["from"] = edges["from"].astype(str).map(_clean_text)
    edges["to"] = edges["to"].astype(str).map(_clean_text)
    edges["value"] = pd.to_numeric(edges["value"], errors="coerce")

    edges = edges.dropna(subset=["value"])
    edges = edges[(edges["value"] > 0) & (edges["from"] != "") & (edges["to"] != "")]
    edges = edges[edges["from"] != edges["to"]].copy()

    if edges.empty:
        raise ValueError("矩阵转换后没有有效连接（要求值 > 0，且排除自连接）。")

    # 如果是对称矩阵，去掉重复边
    is_symmetric = False
    try:
        if set(work.index) == set(work.columns) and len(work.index) == len(work.columns):
            common = sorted(set(work.index))
            aligned = work.reindex(index=common, columns=common)
            vals = aligned.values.astype(float)
            is_symmetric = np.allclose(vals, vals.T, equal_nan=True)
    except Exception:
        is_symmetric = False

    if is_symmetric:
        edges["pair"] = edges.apply(
            lambda r: tuple(sorted([str(r["from"]), str(r["to"])])),
            axis=1,
        )
        edges = edges.drop_duplicates("pair").drop(columns="pair")

    edges["color"] = default_color
    return edges.reset_index(drop=True), work


_NODELINK_KNOWN_COLUMNS = {
    "from", "to", "source", "target", "src", "dst", "start", "end",
    "parent", "child", "value", "weight", "weights", "score", "color",
    "colour", "col",
}


def _read_nodelink_raw(uploaded, name: str | None = None) -> pd.DataFrame:
    """读取 Node-link 输入，兼容没有表头的示例数据。

    无表头文件需要显式按 ``header=None`` 读取，
    否则 data0.csv 的第一行 ``origin,group1,30,blue`` 会被误当作表头。
    """
    raw = read_table(uploaded, name)
    fname = (
        name
        or getattr(uploaded, "name", None)
        or (Path(uploaded).name if isinstance(uploaded, (str, Path)) else "")
    )
    suffix = Path(str(fname)).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return raw

    columns = {_clean_text(col).lower() for col in raw.columns}
    if columns & _NODELINK_KNOWN_COLUMNS:
        return raw

    sep = None if suffix in {".tsv", ".txt"} else ","
    if isinstance(uploaded, (str, Path)):
        return pd.read_csv(uploaded, header=None, sep=sep, engine="python")

    if hasattr(uploaded, "getvalue"):
        data = uploaded.getvalue()
    else:
        data = uploaded.read()
        try:
            uploaded.seek(0)
        except Exception:
            pass
    return pd.read_csv(io.BytesIO(data), header=None, sep=sep, engine="python")


def _read_nodelink_data(uploaded, data_mode: str = "auto", default_color: str = DEFAULT_EDGE_COLOR) -> dict:
    raw = _read_nodelink_raw(uploaded, getattr(uploaded, "name", None))

    if raw is None or raw.empty:
        raise ValueError("读取到的文件为空。")

    if data_mode == "edge":
        edges_df = _normalize_nodelink_edgelist(raw, default_color=default_color)
        nodes = sorted(pd.unique(pd.concat([edges_df["from"], edges_df["to"]], ignore_index=True)).tolist())
        matrix_df = pd.DataFrame(0.0, index=nodes, columns=nodes)
        for _, row in edges_df.iterrows():
            matrix_df.loc[row["from"], row["to"]] += float(row["value"])
        return {"type": "edgelist", "edges": edges_df, "matrix_df": matrix_df}

    if data_mode == "matrix":
        edges_df, matrix_df = _matrix_to_nodelink_edgelist(raw, default_color=default_color)
        return {"type": "matrix", "edges": edges_df, "matrix_df": matrix_df}

    try:
        edges_df = _normalize_nodelink_edgelist(raw, default_color=default_color)
        nodes = sorted(pd.unique(pd.concat([edges_df["from"], edges_df["to"]], ignore_index=True)).tolist())
        matrix_df = pd.DataFrame(0.0, index=nodes, columns=nodes)
        for _, row in edges_df.iterrows():
            matrix_df.loc[row["from"], row["to"]] += float(row["value"])
        return {"type": "edgelist", "edges": edges_df, "matrix_df": matrix_df}
    except Exception:
        edges_df, matrix_df = _matrix_to_nodelink_edgelist(raw, default_color=default_color)
        return {"type": "matrix", "edges": edges_df, "matrix_df": matrix_df}


def _sample_df(default_color: str = DEFAULT_EDGE_COLOR) -> pd.DataFrame:
    sample_path = get_sample_path("nodelink")
    raw = _read_nodelink_raw(sample_path, sample_path.name)
    return _normalize_nodelink_edgelist(raw, default_color=default_color)


def _sample_download_bytes() -> bytes:
    return sample_bytes("nodelink")


# -----------------------------
# 原有布局与绘图辅助（保留，仅用于计算）
# -----------------------------
def _sort_edges(edges: pd.DataFrame, hub_name: str) -> pd.DataFrame:
    work = edges.copy()
    if hub_name and hub_name in set(work["from"]):
        first = work[work["from"] == hub_name].copy()
        rest = work[work["from"] != hub_name].copy()
    else:
        first = pd.DataFrame(columns=work.columns)
        rest = work.copy()
    freq = rest["from"].value_counts().to_dict()
    rest["_freq"] = rest["from"].map(freq).fillna(0)
    rest = rest.sort_values(["_freq", "from", "value"], ascending=[False, True, False])
    out = pd.concat([first, rest.drop(columns="_freq", errors="ignore")], ignore_index=True)
    return out


def _choose_root(edges: pd.DataFrame, hub_name: str) -> str:
    nodes = pd.unique(pd.concat([edges["from"], edges["to"]], ignore_index=True)).tolist()
    if hub_name and hub_name in nodes:
        return hub_name
    indeg = edges["to"].value_counts().to_dict()
    candidates = [n for n in pd.unique(edges["from"]) if indeg.get(n, 0) == 0]
    if candidates:
        outdeg = edges["from"].value_counts().to_dict()
        return sorted(candidates, key=lambda x: outdeg.get(x, 0), reverse=True)[0]
    return str(edges.iloc[0]["from"])


def _node_values(edges: pd.DataFrame, root: str) -> dict[str, float]:
    vals: dict[str, float] = {root: 1.0}
    for src, tgt, val in edges[["from", "to", "value"]].itertuples(index=False, name=None):
        vals[str(tgt)] = float(val)
        vals.setdefault(str(src), 1.0)
    return vals


def _r_node_colors(edges: pd.DataFrame, default_color: str) -> dict[str, str]:
    """按节点分组生成配色映射。

    处理顺序：
      1. 为每个节点找到父节点；
      2. 汇总数据中出现的颜色并追加默认色；
      3. 按类别在字母序中的位置依次取色，而不是按颜色名匹配。

    这里保持同样的“位置映射”，因此输出稳定且可复现。
    """
    nodes = list(
        dict.fromkeys(
            [str(v) for v in edges["from"]] + [str(v) for v in edges["to"]]
        )
    )
    incoming: dict[str, str] = {}
    for src, tgt in edges[["from", "to"]].itertuples(index=False, name=None):
        incoming.setdefault(str(tgt), str(src))

    group_of = {node: incoming.get(node) for node in nodes}

    raw_colors: list[str] = []
    for value in edges["color"].tolist():
        text = str(value).strip()
        if not text or text.lower() == "nan":
            continue
        if text not in raw_colors:
            raw_colors.append(text)
    palette = [_safe_color(text, default_color) for text in raw_colors]
    palette.append("#FF0000")

    levels = sorted({group for group in group_of.values() if group})
    level_colors = {
        level: palette[index % len(palette)]
        for index, level in enumerate(levels)
    }

    # 缺失分组统一使用灰色 (#7F7F7F)。
    return {
        node: level_colors.get(group, "#7F7F7F") if group else "#7F7F7F"
        for node, group in group_of.items()
    }


def _build_children_map(edges: pd.DataFrame) -> dict[str, list[str]]:
    # 保持 _sort_edges 的顺序：叶节点编号来自 edges 的排列，
    # 即先按分组大小降序、组内按 value 降序，而不是按分组名排序。
    children_map: dict[str, list[str]] = {}
    for parent, child in edges[["from", "to"]].itertuples(index=False, name=None):
        children_map.setdefault(str(parent), []).append(str(child))
    return children_map


def _all_roots(G: nx.DiGraph, root: str) -> list[str]:
    others = [n for n in G.nodes if G.in_degree(n) == 0 and n != root]
    return [root] + others


def _compute_radial_positions(G: nx.DiGraph, root: str, children_map: dict[str, list[str]]):
    roots = _all_roots(G, root)
    # 节点行序来自 edges 中 from / to 的出现顺序；G 的节点插入序
    # 与 sort_edges 后的边序一致，因此叶节点顺序可直接取 G.nodes 的顺序。
    leaf_nodes = [n for n in G.nodes if G.out_degree(n) == 0]
    if not leaf_nodes:
        leaf_nodes = list(G.nodes)
    leaf_order = list(leaf_nodes)
    nleaf = max(len(leaf_order), 1)
    # angle = 90 - 360 * id / nleaves
    leaf_angles = {
        node: (90.0 - 360.0 * (i + 1) / nleaf) * pi / 180.0
        for i, node in enumerate(leaf_order)
    }
    roots_for_depth = roots if roots else [root]
    depth = {root: 0}
    for r in roots_for_depth:
        lengths = nx.single_source_shortest_path_length(G, r)
        for node, d in lengths.items():
            if node not in depth or d < depth[node]:
                depth[node] = d
    for n in G.nodes:
        depth.setdefault(n, 1)
    max_depth = max(depth.values()) if depth else 1
    max_depth = max(max_depth, 1)
    angle_cache: dict[str, float] = {}

    def node_angle(node: str) -> float:
        if node in angle_cache:
            return angle_cache[node]
        children = children_map.get(node, [])
        if not children:
            angle_cache[node] = leaf_angles.get(node, 0.0)
            return angle_cache[node]
        child_angles = [node_angle(c) for c in children if c in G.nodes]
        if not child_angles:
            angle_cache[node] = leaf_angles.get(node, 0.0)
        else:
            angle_cache[node] = float(np.mean(child_angles))
        return angle_cache[node]

    pos = {}
    meta = {}
    for n in G.nodes:
        ang = node_angle(n)
        r = depth[n] / max_depth
        x = r * cos(ang)
        y = r * sin(ang)
        deg = degrees(ang)
        is_leaf = G.out_degree(n) == 0
        # 内部节点的 id 固定为 nleaves/4，因此 angle 恒为 0（水平文字）；
        # 只有叶节点使用 90 - 360*i/n 并在 < -90 时翻转。
        text_deg = 0.0
        if is_leaf:
            text_deg = deg
            if deg < -90:
                text_deg = deg + 180
        meta[n] = {
            "angle_rad": ang,
            "angle_deg": text_deg,
            "depth": depth[n],
            "leaf": is_leaf,
        }
        pos[n] = (x, y)
    return pos, meta


def _scale_sizes(values: dict[str, float]) -> dict[str, float]:
    arr = np.array(list(values.values()), dtype=float)
    if len(arr) == 0:
        return {}
    vmin, vmax = np.min(arr), np.max(arr)
    if np.isclose(vmin, vmax):
        return {k: 5.5 for k in values}
    # 尺寸范围 1–10，单位按毫米换算。
    return {
        k: 1.0 + 9.0 * ((v - vmin) / (vmax - vmin))
        for k, v in values.items()
    }


# -----------------------------
# 绘图辅助（Plotly）
# -----------------------------
def _make_diagonal_curve(x1, y1, x2, y2, strength=1.0, n_points=64):
    """近似对角边弯曲（strength = ...）。

    strength = 0 时退化为直线；strength = 1 时先沿父节点半径向外，
    再切向旋转到子节点，形成圆形树状图里的 S 形对角线。
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    t = np.linspace(0.0, 1.0, n_points)
    straight_x = x1 + (x2 - x1) * t
    straight_y = y1 + (y2 - y1) * t

    r1 = float(np.hypot(x1, y1))
    r2 = float(np.hypot(x2, y2))
    if strength <= 0.0 or r1 < 1e-9 or r2 < 1e-9:
        return straight_x, straight_y

    theta1 = float(np.arctan2(y1, x1))
    theta2 = float(np.arctan2(y2, x2))
    delta = (theta2 - theta1 + pi) % (2.0 * pi) - pi

    ease = t * t * (3.0 - 2.0 * t)
    radius = r1 + (r2 - r1) * t
    theta = theta1 + delta * ease
    curve_x = radius * np.cos(theta)
    curve_y = radius * np.sin(theta)

    x_out = (1.0 - strength) * straight_x + strength * curve_x
    y_out = (1.0 - strength) * straight_y + strength * curve_y
    return x_out, y_out


# -----------------------------
# Sidebar 控件
# -----------------------------
def controls(shared: dict) -> None:
    sample_loader_control("ndl_use_sample", "nodelink", "ndl_load_sample_btn")

    if not st.session_state.get("ndl_use_sample", True):
        st.radio(
            "输入数据格式",
            options=["自动识别", "边表（from/to/value）", "矩阵"],
            index=0,
            key="ndl_input_format",
            help="自动识别会优先按边表解析，失败后自动按矩阵解析。",
        )
        st.file_uploader(
            "上传 Node-link 数据文件（CSV / TSV / TXT / XLSX）",
            type=["csv", "tsv", "txt", "xlsx"],
            key="ndl_file",
        )

    st.download_button(
        "下载示例数据（Node-link）",
        data=_sample_download_bytes(),
        file_name="nodelink_example.csv",
        mime="text/csv",
        width="stretch",
    )

    st.text_input("Hub 节点名称（可选）", value="", key="ndl_hub")
    st.slider("连线粗细", min_value=1, max_value=10, value=1, key="ndl_edge_width")
    st.slider("连线透明度", min_value=0.0, max_value=1.0, value=1.0, step=0.05, key="ndl_edge_alpha")
    st.slider("连线弯曲程度", min_value=0.0, max_value=1.0, value=1.0, step=0.05, key="ndl_edge_strength")

    st.color_picker(
        "连线颜色",
        value=DEFAULT_EDGE_COLOR,
        key="ndl_edge_color",
    )


def advanced_controls(shared: dict) -> None:
    """Node-link 的高级参数：外/内层标签、数值与节点形状。"""
    theme = THEMES[st.session_state.theme]
    st.radio(
        "增加显示细节层级",
        ["Null", "Outer layer", "Inner layer"],
        horizontal=True,
        key="ndl_detail_layer",
    )

    if st.session_state.get("ndl_detail_layer") == "Outer layer":
        st.slider("外层标签字号", min_value=1, max_value=10, value=5, key="ndl_outer_label_size")
        st.slider("外层标签透明度", min_value=0.0, max_value=1.0, value=1.0, step=0.05, key="ndl_outer_label_alpha")
        st.slider("外层节点透明度", min_value=0.0, max_value=1.0, value=1.0, step=0.05, key="ndl_outer_node_alpha")
        st.selectbox("外层节点形状", list(SHAPE_MAP.keys()), index=0, key="ndl_outer_shape")
        st.radio("外层是否显示数值", ["Don't show", "Show"], horizontal=True, key="ndl_outer_show_value")

        if st.session_state.get("ndl_outer_show_value") == "Show":
            st.color_picker("外层数值颜色", value=theme.get("text", "#000000"), key="ndl_outer_number_color")
            st.slider("外层数值字号", min_value=1, max_value=10, value=5, key="ndl_outer_number_size")

    if st.session_state.get("ndl_detail_layer") == "Inner layer":
        st.slider("内层标签字号", min_value=1, max_value=10, value=5, key="ndl_inner_label_size")
        st.slider("内层标签透明度", min_value=0.0, max_value=1.0, value=1.0, step=0.05, key="ndl_inner_label_alpha")
        st.slider("内层节点透明度", min_value=0.0, max_value=1.0, value=1.0, step=0.05, key="ndl_inner_node_alpha")
        st.selectbox("内层节点形状", list(SHAPE_MAP.keys()), index=0, key="ndl_inner_shape")
        st.radio("内层是否显示数值", ["Don't show", "Show"], horizontal=True, key="ndl_inner_show_value")

        if st.session_state.get("ndl_inner_show_value") == "Show":
            st.color_picker("内层数值颜色", value=theme.get("text", "#000000"), key="ndl_inner_number_color")
            st.slider("内层数值字号", min_value=1, max_value=10, value=5, key="ndl_inner_number_size")


# -----------------------------
# 主构建逻辑（Plotly 版本）
# -----------------------------
def build(shared: dict):
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    default_edge_color = DEFAULT_EDGE_COLOR
    use_sample = st.session_state.get("ndl_use_sample", True)

    if use_sample:
        edges = _sample_df(default_color=default_edge_color).copy()
        nodes = sorted(pd.unique(pd.concat([edges["from"], edges["to"]], ignore_index=True)).tolist())
        matrix_df = pd.DataFrame(0.0, index=nodes, columns=nodes)
        for _, row in edges.iterrows():
            matrix_df.loc[row["from"], row["to"]] += float(row["value"])
        source_type = "edgelist"
    else:
        uploaded = st.session_state.get("ndl_file")
        if uploaded is None:
            return None, None, "请先上传数据文件。", HELP_TEXT

        mode_label = st.session_state.get("ndl_input_format", "自动识别")
        mode_map = {
            "自动识别": "auto",
            "边表（from/to/value）": "edge",
            "矩阵": "matrix",
        }
        data_mode = mode_map.get(mode_label, "auto")

        try:
            obj = _read_nodelink_data(uploaded, data_mode=data_mode, default_color=default_edge_color)
        except Exception as exc:
            return None, None, f"文件读取失败：{exc}", HELP_TEXT

        edges = obj["edges"].copy()
        matrix_df = obj["matrix_df"].copy()
        source_type = obj["type"]

    try:
        edges = _normalize_nodelink_edgelist(edges, default_color=default_edge_color)
    except Exception as exc:
        return None, None, str(exc), HELP_TEXT

    hub = st.session_state.get("ndl_hub", "").strip()
    edges = _sort_edges(edges, hub)
    root = _choose_root(edges, hub)

    G = nx.DiGraph()
    for src, tgt, val, color in edges[["from", "to", "value", "color"]].itertuples(index=False, name=None):
        G.add_edge(
            str(src),
            str(tgt),
            value=float(val),
            color=str(color),
        )

    if G.number_of_nodes() == 0:
        return None, None, "图中没有可用节点。", HELP_TEXT

    children_map = _build_children_map(edges)
    pos, meta = _compute_radial_positions(G, root, children_map)

    node_values = _node_values(edges, root)
    # 节点按分组着色，颜色来自 color 映射。
    node_colors = _r_node_colors(edges, default_color=default_edge_color)
    default_node_color = "#7F7F7F"
    node_sizes = _scale_sizes(node_values)

    # ---------- Plotly 图形 ----------
    fig = go.Figure()

    # 1. 绘制所有边（S 形对角线）
    edge_color = st.session_state.get("ndl_edge_color", default_edge_color)
    edge_width = st.session_state.get("ndl_edge_width", 1)
    edge_alpha = st.session_state.get("ndl_edge_alpha", 1.0)
    edge_strength = st.session_state.get("ndl_edge_strength", 1.0)

    for src, tgt in edges[["from", "to"]].itertuples(index=False, name=None):
        src = str(src)
        tgt = str(tgt)
        x1, y1 = pos[src]
        x2, y2 = pos[tgt]
        x_curve, y_curve = _make_diagonal_curve(
            x1, y1, x2, y2, strength=edge_strength, n_points=64
        )
        fig.add_trace(go.Scatter(
            x=x_curve, y=y_curve,
            mode='lines',
            # 线宽以毫米计，×2.8 换到 Plotly 像素。
            line=dict(color=edge_color, width=edge_width * 2.8),
            opacity=edge_alpha,
            showlegend=False,
            hoverinfo='none'
        ))

    # 2. 绘制节点（分为外层和内层）
    outer_shape = SHAPE_MAP.get(st.session_state.get("ndl_outer_shape", "circle"), "circle")
    inner_shape = SHAPE_MAP.get(st.session_state.get("ndl_inner_shape", "circle"), "circle")

    outer_label_size = st.session_state.get("ndl_outer_label_size", 5)
    inner_label_size = st.session_state.get("ndl_inner_label_size", 5)
    outer_label_alpha = st.session_state.get("ndl_outer_label_alpha", 1.0)
    inner_label_alpha = st.session_state.get("ndl_inner_label_alpha", 1.0)
    outer_node_alpha = st.session_state.get("ndl_outer_node_alpha", 1.0)
    inner_node_alpha = st.session_state.get("ndl_inner_node_alpha", 1.0)
    outer_show_value = st.session_state.get("ndl_outer_show_value", "Don't show") == "Show"
    inner_show_value = st.session_state.get("ndl_inner_show_value", "Don't show") == "Show"
    outer_number_color = st.session_state.get("ndl_outer_number_color", theme.get("text", "#000000"))
    inner_number_color = st.session_state.get("ndl_inner_number_color", theme.get("text", "#000000"))
    outer_number_size = st.session_state.get("ndl_outer_number_size", 5)
    inner_number_size = st.session_state.get("ndl_inner_number_size", 5)

    node_edge_color = theme.get("node_edge_color", "#000000")

    # 分别收集外层和内层节点数据
    outer_nodes_x = []
    outer_nodes_y = []
    outer_nodes_color = []
    outer_nodes_size = []
    outer_nodes_label = []
    outer_nodes_value = []
    inner_nodes_x = []
    inner_nodes_y = []
    inner_nodes_color = []
    inner_nodes_size = []
    inner_nodes_label = []
    inner_nodes_value = []

    for node in G.nodes:
        x, y = pos[node]
        leaf = meta[node]["leaf"]
        node_color = _safe_color(node_colors.get(node, default_node_color), default_node_color)
        node_size_mm = node_sizes.get(node, 1.0)
        plotly_size = node_size_mm * 2.8
        if leaf:
            px, py = x * 1.07, y * 1.07
            outer_nodes_x.append(px)
            outer_nodes_y.append(py)
            outer_nodes_color.append(node_color)
            outer_nodes_size.append(plotly_size)
            outer_nodes_label.append(node)
            if outer_show_value:
                val = node_values.get(node, "")
                outer_nodes_value.append(f"{val:g}" if isinstance(val, (int, float)) else str(val))
            else:
                outer_nodes_value.append("")
        else:
            px, py = x, y
            inner_nodes_x.append(px)
            inner_nodes_y.append(py)
            inner_nodes_color.append(node_color)
            inner_nodes_size.append(plotly_size)
            inner_nodes_label.append(node)
            if inner_show_value:
                val = node_values.get(node, "")
                inner_nodes_value.append(f"{val:g}" if isinstance(val, (int, float)) else str(val))
            else:
                inner_nodes_value.append("")

    # 添加外层节点散点
    if outer_nodes_x:
        fig.add_trace(go.Scatter(
            x=outer_nodes_x, y=outer_nodes_y,
            mode='markers',
            marker=dict(
                size=outer_nodes_size,
                color=outer_nodes_color,
                symbol=outer_shape,
                line=dict(color=node_edge_color, width=0.56),
                opacity=outer_node_alpha
            ),
            showlegend=False,
            hoverinfo='text',
            text=outer_nodes_label
        ))

        # 外层节点标签（使用 annotation，字体透明度通过 rgba 实现）
        for i, (x, y, label) in enumerate(zip(outer_nodes_x, outer_nodes_y, outer_nodes_label)):
            lx, ly = x * 1.25 / 1.07, y * 1.25 / 1.07
            angle = meta[label]["angle_deg"] if label in meta else 0
            label_color = _safe_color(node_colors.get(label, default_node_color), default_node_color)
            label_color_with_alpha = _color_with_alpha(label_color, outer_label_alpha)
            fig.add_annotation(
                x=lx, y=ly,
                text=label,
                showarrow=False,
                font=dict(size=outer_label_size * 2.8, color=label_color_with_alpha),
                textangle=-angle,
                xanchor='center',
                yanchor='middle'
            )
            if outer_show_value and outer_nodes_value[i]:
                fig.add_annotation(
                    x=x, y=y,
                    text=outer_nodes_value[i],
                    showarrow=False,
                    font=dict(size=outer_number_size, color=outer_number_color),
                    xanchor='center',
                    yanchor='middle'
                )

    # 添加内层节点散点
    if inner_nodes_x:
        fig.add_trace(go.Scatter(
            x=inner_nodes_x, y=inner_nodes_y,
            mode='markers',
            marker=dict(
                size=inner_nodes_size,
                color=inner_nodes_color,
                symbol=inner_shape,
                line=dict(color=node_edge_color, width=0.56),
                opacity=inner_node_alpha
            ),
            showlegend=False,
            hoverinfo='text',
            text=inner_nodes_label
        ))

        for i, (x, y, label) in enumerate(zip(inner_nodes_x, inner_nodes_y, inner_nodes_label)):
            lx, ly = x * 1.25, y * 1.25
            angle = meta[label]["angle_deg"] if label in meta else 0
            label_color = _safe_color(node_colors.get(label, default_node_color), default_node_color)
            label_color_with_alpha = _color_with_alpha(label_color, inner_label_alpha)
            fig.add_annotation(
                x=lx, y=ly,
                text=label,
                showarrow=False,
                font=dict(size=inner_label_size * 2.8, color=label_color_with_alpha),
                textangle=-angle,
                xanchor='center',
                yanchor='middle'
            )
            if inner_show_value and inner_nodes_value[i]:
                fig.add_annotation(
                    x=x, y=y,
                    text=inner_nodes_value[i],
                    showarrow=False,
                    font=dict(size=inner_number_size, color=inner_number_color),
                    xanchor='center',
                    yanchor='middle'
                )

    # 3. 布局设置
    title_text = ""
    fig.update_layout(
        xaxis=dict(visible=False, range=[-1.3, 1.3]),
        yaxis=dict(visible=False, range=[-1.3, 1.3]),
        plot_bgcolor="white",
        paper_bgcolor="white",
        width=750,
        height=750,
        margin=dict(l=0, r=0, t=0, b=0),
        hovermode=False
    )

    shared["last_plotly"] = fig
    shared["data"] = edges
    shared["status"] = (
        f"Node-link 图已生成。识别类型：{source_type}；"
        f"矩阵维度：{matrix_df.shape[0]} x {matrix_df.shape[1]}；"
        f"共 {G.number_of_nodes()} 个节点，{G.number_of_edges()} 条边。Root: {root}"
    )
    shared["help_text"] = HELP_TEXT

    return fig, edges, shared["status"], HELP_TEXT


def render(shared: dict):
    controls(shared)
    return build(shared)


__call__ = render
