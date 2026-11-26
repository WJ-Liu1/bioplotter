from __future__ import annotations

import numpy as np
import pandas as pd
import networkx as nx
import streamlit as st
import plotly.graph_objects as go
from pathlib import Path

from app.core.io_utils import read_table
from app.core.palettes import SCI_NETWORK_COLORS
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES

HELP_TEXT = """
Arc Diagram (Plotly 交互版本)

支持输入：
  1. 边表数据
     - 必须包含列：from, to, value
  2. 矩阵数据
     - 行为节点，列为节点，单元格为连接权重
功能：
  - 支持 自动识别 / 边表 / 矩阵 三种读取模式
  - 自动将矩阵转换为边表后绘制 Arc Diagram
  - 支持节点排序、社区着色、边权重着色、标题、图例等
  - 支持多种社区检测算法（贪心模块度、Louvain、标签传播）
  - 弧线透明度随边权重渐变
  - 节点标签可带背景框（通过文本背景实现）
说明：
  - 绘制参数采用经典弧形图规范：
    弧高约为跨度的一半、弧宽 = 1.5 × value、节点大小 = log(degree + 1) + 0.5、
    标签默认全部显示并竖排在基线下方
  - 本模块使用 Plotly 实现，支持缩放、悬停等交互
"""

# ========== 数据解析部分（与原版完全相同，未做修改） ==========
def _clean_text(x) -> str:
    return str(x).replace("﻿", "").strip()

def _is_probably_numeric_series(s: pd.Series, threshold: float = 0.8) -> bool:
    if s is None or len(s) == 0:
        return False
    test = pd.to_numeric(s, errors="coerce")
    return bool(test.notna().mean() >= threshold)

def _normalize_arc_edgelist(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work.columns = [_clean_text(c).lower() for c in work.columns]

    rename_map = {}
    for c in work.columns:
        if c in {"from", "source", "src", "start"}:
            rename_map[c] = "from"
        elif c in {"to", "target", "dst", "end"}:
            rename_map[c] = "to"
        elif c in {"value", "weight", "weights", "score"}:
            rename_map[c] = "value"
    if rename_map:
        work = work.rename(columns=rename_map)

    need = {"from", "to", "value"}
    if not need.issubset(set(work.columns)):
        raise ValueError(
            f"边表必须包含列：from, to, value；当前列为：{', '.join(map(str, work.columns))}"
        )

    out = work[["from", "to", "value"]].copy()
    out["from"] = out["from"].astype(str).map(_clean_text)
    out["to"] = out["to"].astype(str).map(_clean_text)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")

    out = out.dropna(subset=["value"])
    out = out[(out["value"] > 0) & (out["from"] != "") & (out["to"] != "")]
    out = out[out["from"] != out["to"]].copy()

    if out.empty:
        raise ValueError("边表中没有可用的有效连接（value 必须 > 0，且 from != to）。")
    return out.reset_index(drop=True)


def _normalize_arc_nodes(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["name", "group", "fill", "border"])

    work = df.copy()
    work.columns = [_clean_text(column).lower() for column in work.columns]
    rename_map: dict[str, str] = {}
    for column in work.columns:
        if column in {"name", "label", "node", "id"}:
            rename_map[column] = "name"
        elif column in {"group", "grp", "community"}:
            rename_map[column] = "group"
        elif column in {"fill", "colour", "color", "bg"}:
            rename_map[column] = "fill"
        elif column in {"border", "stroke", "outline"}:
            rename_map[column] = "border"
    if rename_map:
        work = work.rename(columns=rename_map)
    if "name" not in work.columns:
        raise ValueError("节点属性表必须包含 name/label 列。")

    out = pd.DataFrame()
    out["name"] = work["name"].astype(str).map(_clean_text)
    if "group" in work.columns:
        out["group"] = pd.to_numeric(work["group"], errors="coerce")
    else:
        out["group"] = np.arange(len(work), dtype=float)
    out["fill"] = (
        work["fill"].astype(str).map(_clean_text)
        if "fill" in work.columns
        else "#69B3A2"
    )
    out["border"] = (
        work["border"].astype(str).map(_clean_text)
        if "border" in work.columns
        else "#000000"
    )
    out = out[out["name"] != ""].drop_duplicates("name", keep="last")
    out["order"] = np.arange(len(out))
    return out.reset_index(drop=True)


def _matrix_from_edges(edges_df: pd.DataFrame) -> pd.DataFrame:
    nodes = sorted(pd.unique(pd.concat([edges_df["from"], edges_df["to"]], ignore_index=True)).tolist())
    matrix_df = pd.DataFrame(0.0, index=nodes, columns=nodes)
    for _, row in edges_df.iterrows():
        matrix_df.loc[row["from"], row["to"]] = float(row["value"])
    return matrix_df


def _read_arc_gml(uploaded) -> dict:
    raw = uploaded.getvalue() if hasattr(uploaded, "getvalue") else Path(str(uploaded)).read_bytes()
    text = raw.decode("utf-8", errors="replace")
    try:
        graph = nx.parse_gml(text, label="label")
    except Exception:
        graph = nx.parse_gml(text)
    if graph.is_directed():
        graph = graph.to_undirected()

    node_rows: list[dict] = []
    for node, attrs in graph.nodes(data=True):
        label = _clean_text(attrs.get("label", node))
        node_rows.append(
            {
                "name": label,
                "group": attrs.get("group", 0),
                "fill": attrs.get("fill", "#69B3A2"),
                "border": attrs.get("border", "#000000"),
            }
        )
    nodes_df = _normalize_arc_nodes(pd.DataFrame(node_rows))

    edge_rows: list[dict] = []
    for source, target, attrs in graph.edges(data=True):
        value = pd.to_numeric(attrs.get("value", attrs.get("weight", 1)), errors="coerce")
        if pd.isna(value) or float(value) <= 0:
            continue
        edge_rows.append(
            {
                "from": _clean_text(source),
                "to": _clean_text(target),
                "value": float(value),
            }
        )
    edges_df = pd.DataFrame(edge_rows)
    if edges_df.empty:
        raise ValueError("GML 文件中没有 value > 0 的有效边。")
    edges_df = edges_df[edges_df["from"] != edges_df["to"]].reset_index(drop=True)
    if edges_df.empty:
        raise ValueError("GML 文件中没有可绘制的非自环边。")
    return {
        "type": "gml",
        "edges": edges_df,
        "matrix_df": _matrix_from_edges(edges_df),
        "nodes": nodes_df,
    }

def _matrix_to_arc_edgelist(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
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

    return edges.reset_index(drop=True), work

def _read_arc_data(uploaded, data_mode: str = "auto") -> dict:
    if str(getattr(uploaded, "name", "")).lower().endswith(".gml"):
        return _read_arc_gml(uploaded)

    raw = read_table(uploaded, uploaded.name)
    if raw is None or raw.empty:
        raise ValueError("读取到的文件为空。")

    if data_mode == "edge":
        edges_df = _normalize_arc_edgelist(raw)
        return {"type": "edgelist", "edges": edges_df, "matrix_df": _matrix_from_edges(edges_df), "nodes": None}

    if data_mode == "matrix":
        edges_df, matrix_df = _matrix_to_arc_edgelist(raw)
        return {"type": "matrix", "edges": edges_df, "matrix_df": matrix_df, "nodes": None}

    try:
        edges_df = _normalize_arc_edgelist(raw)
        return {"type": "edgelist", "edges": edges_df, "matrix_df": _matrix_from_edges(edges_df), "nodes": None}
    except Exception:
        edges_df, matrix_df = _matrix_to_arc_edgelist(raw)
        return {"type": "matrix", "edges": edges_df, "matrix_df": matrix_df, "nodes": None}

def _sample_edgelist() -> pd.DataFrame:
    file_path = get_sample_path("arc")
    return _normalize_arc_edgelist(read_table(file_path, file_path.name))

def _sample_nodes() -> pd.DataFrame:
    file_path = get_sample_path("arc_nodes")
    return _normalize_arc_nodes(read_table(file_path, file_path.name))

def _sample_download_bytes() -> bytes:
    file_path = get_sample_path("arc")
    with open(file_path, "rb") as f:
        return f.read()

# ========== 图形辅助函数 ==========
def _community_membership(G: nx.Graph, algorithm: str = "greedy") -> dict[str, int]:
    try:
        if algorithm == "louvain":
            try:
                import community as community_louvain
                partition = community_louvain.best_partition(G, weight="value")
                membership = {node: int(comm) + 1 for node, comm in partition.items()}
                if membership:
                    return membership
            except ImportError:
                st.warning("Louvain 算法需要安装 python-louvain 包，已回退至贪心模块度。")
                algorithm = "greedy"
        elif algorithm == "label_propagation":
            comms = list(nx.community.label_propagation_communities(G))
            membership = {}
            for i, comm in enumerate(comms, start=1):
                for node in comm:
                    membership[node] = i
            if membership:
                return membership
        comms = list(nx.community.greedy_modularity_communities(G, weight="value"))
        membership = {node: i+1 for i, comm in enumerate(comms) for node in comm}
        if membership:
            return membership
    except Exception as e:
        st.warning(f"社区检测失败，已忽略：{e}")
    return {n: 1 for n in G.nodes()}

def _node_degree(G: nx.Graph) -> dict[str, float]:
    """无权重度数，用于节点大小与排序。"""
    return {n: float(d) for n, d in G.degree()}

def _ordered_nodes(nodes_df: pd.DataFrame, sort_by: str) -> list[str]:
    if sort_by == "degree_desc":
        tmp = nodes_df.sort_values(["n", "name"], ascending=[False, True])
    elif sort_by == "degree_asc":
        tmp = nodes_df.sort_values(["n", "name"], ascending=[True, True])
    elif sort_by == "name":
        tmp = nodes_df.sort_values(["name"], ascending=[True])
    else:
        if "order" in nodes_df.columns:
            tmp = nodes_df.sort_values(["grp", "n", "order"], ascending=[False, False, True])
        else:
            tmp = nodes_df.sort_values(["grp", "n", "name"], ascending=[False, False, True])
    return tmp["name"].astype(str).tolist()

def _scale_vals(vals: np.ndarray, lo: float, hi: float) -> np.ndarray:
    vals = np.asarray(vals, dtype=float)
    if len(vals) == 0:
        return vals
    vmin = np.nanmin(vals)
    vmax = np.nanmax(vals)
    if np.isclose(vmin, vmax):
        return np.full_like(vals, (lo + hi) / 2, dtype=float)
    return lo + (vals - vmin) * (hi - lo) / (vmax - vmin)

def _make_arc_curve(x1, x2, height_multiplier=1.0, n_points=72):
    """半圆弧：半径取节点跨度的一半。"""
    span = abs(float(x2) - float(x1))
    if span <= 0:
        return [float(x1), float(x2)], [0.0, 0.0]
    midpoint = (float(x1) + float(x2)) / 2.0
    radius = span / 2.0
    direction = 1.0 if x2 >= x1 else -1.0
    theta = np.linspace(np.pi, 0.0, n_points)
    x_curve = midpoint + direction * radius * np.cos(theta)
    y_curve = radius * np.sin(theta) * float(height_multiplier)
    return x_curve, y_curve

# ========== Streamlit 控件 ==========
def controls(shared: dict) -> None:
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    sample_loader_control("arc_use_sample", "arc", "arc_load_sample_btn")
    if not st.session_state.get("arc_use_sample", True):
        st.radio(
            "输入数据格式",
            options=["自动识别", "边表（from/to/value）", "矩阵"],
            index=0,
            key="arc_input_format",
            help="自动识别会优先按边表解析，失败后自动按矩阵解析。",
        )
        st.file_uploader(
            "上传数据文件（CSV / TSV / TXT / XLSX / GML）",
            type=["csv", "tsv", "txt", "xlsx", "gml"],
            key="arc_file_upload",
        )

    st.download_button(
        "下载示例边表（Arc）",
        data=_sample_download_bytes(),
        file_name="Arc_Diagram_example.csv",
        mime="text/csv",
        width="stretch",
    )

    st.markdown("### 节点 (Node) 设置")
    st.color_picker("默认节点边框色", value="#69B3A2", key="arc_point_color")
    st.selectbox(
        "节点形状",
        ["circle", "square", "triangle-up", "diamond"],
        index=0,
        key="arc_node_shape",
    )
    st.slider(
        "最多显示节点数",
        40,
        300,
        150,
        5,
        key="arc_max_nodes",
        help="默认展示全部节点；节点过多时可下调，按 degree 降序保留前 N 个。",
    )
    st.slider("节点大小乘数", 0.5, 2.0, 1.0, 0.1, key="arc_node_size_multiplier")
    st.selectbox(
        "节点排序依据",
        ["社区 + 度数 (默认)", "度数降序", "度数升序", "名称字母序"],
        index=0,
        key="arc_sort_by_label",
    )

    st.markdown("### 着色选项")
    st.checkbox("按社区着色节点和弧线", value=False, key="arc_color_by_community")
    st.checkbox("按边权重着色弧线", value=False, key="arc_color_by_weight")
    st.markdown("### 弧/边 (Arc/Edge) 设置")
    st.color_picker("弧线颜色 (默认)", value="#4D4D4D", key="arc_line_color")
    st.selectbox("弧线类型", ["solid", "dash", "dot"], index=0, key="arc_line_type")
    st.slider("弧线粗细乘数", 0.5, 3.0, 1.0, 0.1, key="arc_thickness_multiplier")
    st.slider("弧高度倍率", 0.1, 3.0, 1.0, 0.05, key="arc_height_multiplier")
    st.checkbox("弧线透明度随权重渐变", value=False, key="arc_alpha_by_weight")

    st.markdown("### 标签设置")
    st.slider("标签字体大小", 6, 24, 8, key="arc_label_size")
    st.slider("标签垂直偏移", -50, 50, -6, key="arc_label_offset")
    st.checkbox("显示全部节点标签", value=True, key="arc_all_labels")
    st.checkbox("标签背景框", value=False, key="arc_label_background")

    st.markdown("### 图例")
    st.checkbox("显示图例", value=True, key="arc_show_legend")

    st.markdown("### 标题")
    st.checkbox("添加图形标题", value=False, key="arc_add_title")
    if st.session_state.get("arc_add_title", False):
        st.text_input("输入标题", "Network Arc Diagram", key="arc_title")


def advanced_controls(shared: dict) -> None:
    """Arc Diagram 的高级参数：社区检测算法。"""
    st.markdown("### 社区检测")
    st.selectbox(
        "社区检测算法",
        ["贪心模块度 (Greedy Modularity)", "Louvain", "标签传播 (Label Propagation)"],
        index=0,
        key="arc_community_algorithm",
        help="Louvain 算法需要安装 python-louvain 包。"
    )


# ========== 主构建逻辑（Plotly 版本，修正 textoffset 错误） ==========
def build(shared: dict):
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    use_sample = st.session_state.get("arc_use_sample", True)

    if use_sample:
        edges_df = _sample_edgelist().copy()
        obj = {
            "type": "gml",
            "edges": edges_df,
            "matrix_df": _matrix_from_edges(edges_df),
            "nodes": _sample_nodes(),
        }
    else:
        uploaded = st.session_state.get("arc_file_upload")
        if uploaded is None:
            return None, None, "请先上传数据文件。", HELP_TEXT
        mode_label = st.session_state.get("arc_input_format", "自动识别")
        mode_map = {
            "自动识别": "auto",
            "边表（from/to/value）": "edge",
            "矩阵": "matrix",
        }
        data_mode = mode_map.get(mode_label, "auto")
        try:
            obj = _read_arc_data(uploaded, data_mode=data_mode)
        except Exception as exc:
            return None, None, f"文件解析失败：{exc}", HELP_TEXT

    edges_df = obj["edges"].copy().reset_index(drop=True)
    matrix_df = obj["matrix_df"].copy()

    if edges_df.empty:
        return None, None, "没有有效连接可绘制 Arc Diagram。", HELP_TEXT

    shared["data"] = edges_df.copy()
    shared["status"] = (
        f"Arc Diagram 文件读取成功。识别类型：{obj['type']}；"
        f"矩阵维度：{matrix_df.shape[0]} x {matrix_df.shape[1]}；有效边数：{len(edges_df)}"
    )

    # 构建网络
    G = nx.from_pandas_edgelist(
        edges_df,
        source="from",
        target="to",
        edge_attr="value",
        create_using=nx.Graph(),
    )

    # 社区检测
    alg_map = {
        "贪心模块度 (Greedy Modularity)": "greedy",
        "Louvain": "louvain",
        "标签传播 (Label Propagation)": "label_propagation",
    }
    alg_label = st.session_state.get("arc_community_algorithm", "贪心模块度 (Greedy Modularity)")
    alg = alg_map.get(alg_label, "greedy")
    membership = _community_membership(G, algorithm=alg)

    # 节点度数：不加权，与边权仅用于弧线粗细不同
    degree = _node_degree(G)

    nodes_df = pd.DataFrame(
        {
            "name": list(G.nodes()),
            "grp": [membership.get(n, 1) for n in G.nodes()],
            "n": [degree.get(n, 0.0) for n in G.nodes()],
        }
    )
    node_meta = obj.get("nodes")
    has_node_meta = isinstance(node_meta, pd.DataFrame) and not node_meta.empty
    if has_node_meta:
        meta = node_meta.drop_duplicates("name", keep="last").set_index("name")
        nodes_df["grp"] = nodes_df["name"].map(meta["group"]).fillna(nodes_df["grp"]).astype(int)
        nodes_df["fill"] = nodes_df["name"].map(meta["fill"]).fillna("#69B3A2")
        nodes_df["border"] = nodes_df["name"].map(meta["border"]).fillna("#69B3A2")
        nodes_df["order"] = nodes_df["name"].map(meta["order"]).fillna(1_000_000).astype(int)
    else:
        nodes_df["fill"] = "#69B3A2"
        nodes_df["border"] = "#000000"

    # 节点太多时按 degree 截断（只影响展示，不改原始数据）
    total_nodes = int(len(nodes_df))
    max_nodes = int(st.session_state.get("arc_max_nodes", 150))
    if total_nodes > max_nodes:
        keep = set(nodes_df.nlargest(max_nodes, "n")["name"].tolist())
        nodes_df = nodes_df[nodes_df["name"].isin(keep)].reset_index(drop=True)
        edges_df = edges_df[edges_df["from"].isin(keep) & edges_df["to"].isin(keep)].reset_index(drop=True)

    nodes_shown = int(len(nodes_df))

    # 节点排序
    sort_map = {
        "社区 + 度数 (默认)": "community_degree",
        "度数降序": "degree_desc",
        "度数升序": "degree_asc",
        "名称字母序": "name",
    }
    sort_by = sort_map[st.session_state.get("arc_sort_by_label", "社区 + 度数 (默认)")]
    ordered = _ordered_nodes(nodes_df, sort_by)
    pos_map = {name: i for i, name in enumerate(ordered)}

    # 节点颜色
    node_default_color = st.session_state.get("arc_point_color") or "#69B3A2"
    node_lookup = nodes_df.set_index("name")
    comm_colors = None
    if st.session_state.get("arc_color_by_community", False):
        communities = sorted(pd.unique(nodes_df["grp"]).tolist())
        plotly_colors = list(SCI_NETWORK_COLORS)
        comm_colors = {comm: plotly_colors[i % len(plotly_colors)] for i, comm in enumerate(communities)}
        node_fill = [comm_colors[int(node_lookup.loc[name, "grp"])] for name in ordered]
        edge_colors = [comm_colors[int(node_lookup.loc[u, "grp"])] for u in edges_df["from"]]
    else:
        if has_node_meta:
            node_fill = [str(node_lookup.loc[name, "fill"]) for name in ordered]
        else:
            node_fill = [node_default_color] * len(ordered)
        edge_colors = [st.session_state.get("arc_line_color") or "#4D4D4D"] * len(edges_df)

    node_border_colors = [node_default_color] * len(ordered) if has_node_meta else ["#000000"] * len(ordered)

    # 按权重着色覆盖弧线颜色
    if st.session_state.get("arc_color_by_weight", False):
        vals = edges_df["value"].to_numpy(dtype=float)
        if np.isclose(np.nanmin(vals), np.nanmax(vals)):
            edge_colors = [theme.get("sci_network_dark", "#4A5D54")] * len(vals)
        else:
            # 权重色阶：浅→深使用网络类 SCI 色（浅灰绿 → 深青）
            blues = [
                "#E3E9E2", "#C7DBD8", "#A9CBC5", "#8ABBB4", "#6BA9A4", "#4E9794", "#2F8281", "#1B6D6C",
            ]
            norm = (vals - np.nanmin(vals)) / (np.nanmax(vals) - np.nanmin(vals))
            edge_colors = [blues[int(np.clip(v * (len(blues)-1), 0, len(blues)-1))] for v in norm]

    # 节点大小：cex.nodes = log(degree + 1) + 0.5，这里换算为像素直径
    node_sizes = (
        np.log(nodes_df.set_index("name").loc[ordered, "n"].to_numpy(dtype=float) + 1) + 0.5
    ) * 6.5 * st.session_state.get("arc_node_size_multiplier", 1.0)

    # 边粗细：lwd.arcs = 1.5 * value，直接按权重线性换算，不做 min-max 拉伸
    edge_widths = np.clip(
        1.5 * edges_df["value"].to_numpy(dtype=float)
        * st.session_state.get("arc_thickness_multiplier", 1.0),
        0.8,
        26.0,
    )

    # 边透明度：实心弧线默认 0.9；仅开启“随权重渐变”时才变化
    weights = edges_df["value"].to_numpy(dtype=float)
    if st.session_state.get("arc_alpha_by_weight", False) and not np.isclose(np.min(weights), np.max(weights)):
        alphas = 0.3 + 0.6 * (weights - np.min(weights)) / (np.max(weights) - np.min(weights))
    else:
        alphas = [0.9] * len(weights)

    # 节点形状映射到 Plotly symbol
    shape_map = {
        "circle": "circle",
        "square": "square",
        "triangle-up": "triangle-up",
        "diamond": "diamond",
    }
    marker_symbol = shape_map.get(st.session_state.get("arc_node_shape", "circle"), "circle")

    # ========== 开始构建 Plotly 图形 ==========
    fig = go.Figure()

    # 1. 绘制所有弧线（半圆）
    height_multiplier = st.session_state.get("arc_height_multiplier", 1.0)
    for idx, row in edges_df.iterrows():
        x1 = pos_map[row["from"]]
        x2 = pos_map[row["to"]]
        x_curve, y_curve = _make_arc_curve(x1, x2, height_multiplier, n_points=72)
        line_dash = st.session_state.get("arc_line_type", "solid")
        fig.add_trace(go.Scatter(
            x=x_curve,
            y=y_curve,
            mode='lines',
            line=dict(
                color=edge_colors[idx],
                width=edge_widths[idx],
                dash=line_dash
            ),
            opacity=alphas[idx],
            showlegend=False,
            hoverinfo='none'
        ))

    # 2. 绘制节点（散点图）
    node_x = [pos_map[node] for node in ordered]
    node_y = [0] * len(ordered)
    fig.add_trace(go.Scatter(
        x=node_x,
        y=node_y,
        mode='markers',
        marker=dict(
            size=node_sizes,
            color=node_fill,
            symbol=marker_symbol,
            line=dict(color=node_border_colors[0] if node_border_colors else "#000000", width=2.0),
            opacity=1.0
        ),
        hoverinfo='text',
        text=ordered,
        showlegend=False
    ))

    # 3. 添加节点标签（竖排、全部节点、位于基线下方）
    label_offset_y = st.session_state.get("arc_label_offset", -6) / 100.0  # 转换为数据坐标
    degree_rank = (
        nodes_df.set_index("name")["n"].reindex(ordered).fillna(0).sort_values(ascending=False).index.tolist()
    )
    if st.session_state.get("arc_all_labels", True):
        label_nodes = set(ordered)
    else:
        label_nodes = set(degree_rank[: min(len(ordered), 12)])
    label_size = st.session_state.get("arc_label_size", 8)
    text_color = theme.get("text", "#000000")
    for node_name in ordered:
        if node_name not in label_nodes:
            continue
        fig.add_annotation(
            x=pos_map[node_name],
            y=label_offset_y,
            text=str(node_name),
            showarrow=False,
            font=dict(size=label_size, color=text_color),
            textangle=-90,
            xanchor="center",
            yanchor="top",
        )

    # 4. 设置布局
    title_text = ""
    if st.session_state.get("arc_add_title", False):
        title_text = st.session_state.get("arc_title", "Network Arc Diagram")

    # y 轴按实际最高弧线收紧（半径 = 跨度一半的半圆）
    span_max = 0.0
    if len(edges_df) and "from" in edges_df and "to" in edges_df:
        spans = (edges_df["to"].map(pos_map) - edges_df["from"].map(pos_map)).abs().dropna()
        if len(spans):
            span_max = float(spans.max())
    arc_max = span_max * 0.5 * height_multiplier
    ymax = max(arc_max, 1.0) + 0.1
    ymin = min(-0.55, label_offset_y - 0.5)

    fig.update_layout(
        title=dict(text=title_text, font=dict(color=theme.get("text", "#000000"))),
        xaxis=dict(
            showticklabels=False,
            showgrid=False,
            zeroline=False,
            range=[-1, len(ordered)],
            constrain='domain'
        ),
        yaxis=dict(
            showticklabels=False,
            showgrid=False,
            zeroline=False,
            range=[ymin, ymax]
        ),
        plot_bgcolor=theme.get("bg", "#f5f7fb"),
        paper_bgcolor=theme.get("bg", "#f5f7fb"),
        width=900,
        height=500,
        margin=dict(l=30, r=30, t=50, b=30),
        hovermode=False
    )

    # 5. 添加图例（按社区着色）
    if st.session_state.get("arc_show_legend", True) and st.session_state.get("arc_color_by_community", True) and comm_colors:
        for comm, color in comm_colors.items():
            fig.add_trace(go.Scatter(
                x=[None], y=[None],
                mode='markers',
                marker=dict(size=10, color=color, symbol=marker_symbol, line=dict(color='black', width=1)),
                name=f'Community {comm}',
                showlegend=True
            ))
        fig.update_layout(legend=dict(
            title="Communities",
            orientation="v",
            x=1.02, y=1,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="black",
            borderwidth=0.5
        ))

    shared["status"] = (
        f"Arc Diagram 就绪：显示 Top {nodes_shown} / 总节点 {total_nodes}；"
        f"边 {len(edges_df)} 条；社区 {nodes_df['grp'].nunique()} 个"
    )
    shared["last_plotly"] = fig
    shared["help_text"] = HELP_TEXT

    return fig, edges_df, shared["status"], HELP_TEXT

def render(shared: dict):
    controls(shared)
    return build(shared)

__call__ = render
