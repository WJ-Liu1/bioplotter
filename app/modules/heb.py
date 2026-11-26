from __future__ import annotations
import re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from scipy.interpolate import CubicHermiteSpline
from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_bytes, sample_loader_control
from app.core.theme import THEMES
HELP_TEXT = """
Hierarchical Edge Bundling (Plotly 交互版本)
输入数据要求：
  - 上传 CSV / TSV / TXT / XLSX
  - 支持两种格式：
    1. 边表：必须包含 from, to, value 三列
    2. 矩阵：行为节点，列为节点，单元格为连接权重
功能：
  - 按节点名的层级分隔符还原树（flare 示例：flare.analytics.cluster.X）
  - 极坐标树状布局（环形 dendrogram）
  - 沿层次骨架生成捆绑连线，叶标签沿半径旋转
  - 可调节：
    - 边捆绑张力（越大越贴合骨架）
    - 边宽度
    - 标签大小
    - 是否显示标签
    - 图形标题
    - 骨架颜色、连线颜色、标签颜色
说明：
  - 本模块使用 Plotly 实现，支持缩放、悬停等交互
  - 布局采用经典环形层次边捆绑样式，示例数据为 flare imports
"""# -----------------------------# 数据清洗 / 格式识别（与原版完全相同）# -----------------------------
def _clean_text(x) -> str:
    return str(x).replace("\ufeff", "").strip()
def _clean_lower(x) -> str:
    return _clean_text(x).lower()
def _is_probably_numeric_series(s: pd.Series, threshold: float = 0.8) -> bool:
    if s is None or len(s) == 0:
        return False
    test = pd.to_numeric(s, errors="coerce")
    return bool(test.notna().mean() >= threshold)
def _looks_like_edgelist(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return False
    cols = [_clean_lower(c) for c in df.columns]
    colset = set(cols)
    if {"from", "to", "value"}.issubset(colset):
        return True
    has_from = any(c in {"from", "source", "src", "start"} for c in cols)
    has_to = any(c in {"to", "target", "dst", "end"} for c in cols)
    has_value = any(c in {"value", "weight", "weights", "score"} for c in cols)
    return has_from and has_to and has_value
def _looks_like_matrix(df: pd.DataFrame) -> bool:
    if df is None or df.empty or df.shape[1] < 2:
        return False
    work = df.copy()
    work.columns = [_clean_text(c) for c in work.columns]
    first_col = work.columns[0]
    first_col_lower = _clean_lower(first_col)
    first_series = work.iloc[:, 0]
    first_col_is_label = (        first_col_lower in {"", "unnamed: 0", "unnamed", "name", "node", "nodes", "id", "label"}        or (not _is_probably_numeric_series(first_series))    )
    if not first_col_is_label:
        return False
    numeric_ratios = []
    for col in work.columns[1:]:
        numeric_ratios.append(pd.to_numeric(work[col], errors="coerce").notna().mean())
    mostly_numeric_body = bool(len(numeric_ratios) > 0 and np.mean(numeric_ratios) >= 0.6)
    row_names = {_clean_text(x) for x in first_series if _clean_text(x) != "" and _clean_lower(x) != "nan"}
    col_names = {_clean_text(c) for c in work.columns[1:] if _clean_text(c) != "" and _clean_lower(c) != "nan"}
    overlap = len(row_names & col_names)
    square_like = len(row_names) > 0 and len(col_names) > 0 and abs(len(row_names) - len(col_names)) <= 1
    return mostly_numeric_body and (overlap >= 2 or square_like)
def _normalize_heb_edgelist(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work.columns = [_clean_lower(c) for c in work.columns]
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
        raise ValueError(f"边表必须包含列：from, to, value；当前列为：{', '.join(map(str, work.columns))}")
    out = work[["from", "to", "value"]].copy()
    out["from"] = out["from"].astype(str).map(_clean_text)
    out["to"] = out["to"].astype(str).map(_clean_text)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna(subset=["value"])
    out = out[(out["value"] > 0) & (out["from"] != "") & (out["to"] != "")]
    out = out[out["from"] != out["to"]].copy()
    if out.empty:
        raise ValueError("边表中没有可用的有效连接（value 必须 > 0，且 from != to）。")
    return out
def _matrix_to_heb_edgelist(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work.columns = [_clean_text(c) for c in work.columns]
    if work.shape[0] == 0 or work.shape[1] < 2:
        raise ValueError("矩阵格式至少需要 2 列（第 1 列通常为行名，其余为节点列）。")
    first_col = work.columns[0]
    first_series = work[first_col]
    first_col_name = _clean_lower(first_col)
    first_col_is_label = (        first_col_name in {"", "unnamed: 0", "unnamed", "name", "node", "nodes", "id", "label"}        or (not _is_probably_numeric_series(first_series))    )
    if first_col_is_label:
        work = work.set_index(first_col)
    else:
        if isinstance(work.index, pd.RangeIndex):
            raise ValueError("矩阵格式建议第一列为节点名（行名），当前未识别到有效行名列。")
    work.index = [_clean_text(x) for x in work.index]
    work.columns = [_clean_text(c) for c in work.columns]
    row_mask = [x != "" and _clean_lower(x) != "nan" for x in work.index]
    col_mask = [x != "" and _clean_lower(x) != "nan" for x in work.columns]
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
        edges["pair"] = edges.apply(lambda r: tuple(sorted([str(r["from"]), str(r["to"])])), axis=1)
        edges = edges.drop_duplicates("pair").drop(columns="pair")
    return edges
def _build_parse_note(requested_mode: str, actual_mode: str, looks_edge: bool, looks_matrix: bool) -> str:
    mode_name = {"auto": "自动识别", "edge": "边表", "matrix": "矩阵", "sample": "示例数据"}
    actual_label = mode_name.get(actual_mode, actual_mode)
    requested_label = mode_name.get(requested_mode, requested_mode)
    if requested_mode == "auto":
        if looks_matrix and not looks_edge and actual_mode == "matrix":
            return "已自动识别为【矩阵】格式并完成解析。"
        if looks_edge and not looks_matrix and actual_mode == "edge":
            return "已自动识别为【边表】格式并完成解析。"
        return f"已自动解析输入数据，当前使用【{actual_label}】模式。"
    if requested_mode == "sample":
        if actual_mode == "matrix":
            return "示例数据看起来是【矩阵】格式，已自动按【矩阵】完成解析。"
        return "示例数据已按【边表】格式解析。"
    if requested_mode != actual_mode:
        return f"你当前选择的是【{requested_label}】，但上传文件更像【{actual_label}】格式；程序已自动切换为【{actual_label}】完成解析。"
    return f"当前按【{actual_label}】格式完成解析。"
def _parse_heb_data(raw: pd.DataFrame, requested_mode: str = "auto") -> tuple[pd.DataFrame, dict]:
    if raw is None or raw.empty:
        raise ValueError("读取到的文件为空。")
    requested_mode = (requested_mode or "auto").lower()
    looks_edge = _looks_like_edgelist(raw)
    looks_matrix = _looks_like_matrix(raw)
    parsers = {"edge": _normalize_heb_edgelist, "matrix": _matrix_to_heb_edgelist}
    if requested_mode == "edge":
        attempts = ["edge", "matrix"]
    elif requested_mode == "matrix":
        attempts = ["matrix", "edge"]
    elif requested_mode == "sample":
        attempts = ["matrix", "edge"] if (looks_matrix and not looks_edge) else ["edge", "matrix"]
    else:
        attempts = ["matrix", "edge"] if (looks_matrix and not looks_edge) else ["edge", "matrix"]
    errors = {}
    for actual_mode in attempts:
        try:
            out = parsers[actual_mode](raw)
            note = _build_parse_note(requested_mode, actual_mode, looks_edge, looks_matrix)
            info = {                "requested_mode": requested_mode,                "actual_mode": actual_mode,                "looks_like_edgelist": looks_edge,                "looks_like_matrix": looks_matrix,                "switched_mode": requested_mode not in {"auto", "sample"} and requested_mode != actual_mode,                "note": note,            }
            return out, info
        except Exception as exc:
            errors[actual_mode] = str(exc)
    hint = []
    if looks_matrix and not looks_edge:
        hint.append("当前文件更像【矩阵】格式（第一列像行名，后续列像节点列，单元格像权重）。")
    elif looks_edge and not looks_matrix:
        hint.append("当前文件更像【边表】格式（应包含 from / to / value 三列）。")
    else:
        hint.append("当前文件格式无法被明确识别为标准边表或标准矩阵。")
    if "edge" in errors:
        hint.append(f"边表解析失败：{errors['edge']}")
    if "matrix" in errors:
        hint.append(f"矩阵解析失败：{errors['matrix']}")
    hint.append("建议检查是否存在空表头、非数值权重、全 0 矩阵，或首列未正确保存为行名。")
    raise ValueError("；".join(hint))
def _read_heb_data(uploaded, data_mode: str = "auto") -> tuple[pd.DataFrame, dict]:
    raw = read_table(uploaded, uploaded.name)
    return _parse_heb_data(raw, requested_mode=data_mode)
def _sample_df() -> tuple[pd.DataFrame, dict]:
    sample_path = get_sample_path("heb")
    raw = read_table(sample_path, sample_path.name)
    if raw is None or raw.empty:
        raise ValueError("示例数据为空。")
    return _parse_heb_data(raw, requested_mode="sample")
def _sample_download_bytes() -> bytes:
    return sample_bytes("heb")# -----------------------------# 绘图辅助（Plotly 版）# -----------------------------
def _short_name(x: str) -> str:
    """取层级路径最后一段作为短名称。"""
    return str(x).rsplit(".", 1)[-1]
def _build_hierarchy(names: list[str]) -> tuple[dict[str, list[str]], str, dict[str, int]]:
    """按点名中的 "." 还原层级树（flare 数据集就是这种命名）。

    返回 (children, root, depth)。若多个根，则创建虚拟根 ""。
    """
    nodes: set[str] = set()
    for name in names:
        parts = str(name).split(".")
        for i in range(1, len(parts) + 1):
            nodes.add(".".join(parts[:i]))
    children: dict[str, list[str]] = {n: [] for n in nodes}
    roots: list[str] = []
    for n in sorted(nodes):
        if "." in n:
            parent = n.rsplit(".", 1)[0]
            if parent in children:
                children[parent].append(n)
            else:
                roots.append(n)
        else:
            roots.append(n)
    if len(roots) > 1:
        children[""] = roots
        root = ""
    elif roots:
        root = roots[0]
    else:
        root = ""
    depth: dict[str, int] = {root: 0}
    stack = [root]
    while stack:
        cur = stack.pop()
        for child in children.get(cur, []):
            depth[child] = depth[cur] + 1
            stack.append(child)
    return children, root, depth
def _cubic_bezier_curve(p0, p3, tension, n_points=60):
    """控制点向圆心收拢的三次贝塞尔，用于近似边捆绑曲线。"""
    t = float(np.clip(tension, 0.0, 1.0))
    c_scale = max(0.02, 1.0 - 0.92 * t)
    p1 = np.array(p0) * c_scale
    p2 = np.array(p3) * c_scale
    ts = np.linspace(0, 1, n_points)
    xs = (1-ts)**3 * p0[0] + 3*(1-ts)**2*ts * p1[0] + 3*(1-ts)*ts**2 * p2[0] + ts**3 * p3[0]
    ys = (1-ts)**3 * p0[1] + 3*(1-ts)**2*ts * p1[1] + 3*(1-ts)*ts**2 * p2[1] + ts**3 * p3[1]
    return xs, ys
def _catmull_rom(points: list[tuple[float, float]], samples: int = 10):
    """Catmull-Rom 样条：把折线路径（叶 -> 祖先 -> LCA -> 祖先 -> 叶）平滑成曲线。"""
    pts = np.asarray(points, dtype=float)
    if len(pts) < 2:
        return np.array([]), np.array([])
    if len(pts) == 2:
        t = np.linspace(0, 1, samples * 2)
        return pts[0, 0] + (pts[1, 0] - pts[0, 0]) * t, pts[0, 1] + (pts[1, 1] - pts[0, 1]) * t
    padded = np.vstack([pts[0], pts, pts[-1]])
    xs, ys = [], []
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i - 1], padded[i], padded[i + 1], padded[i + 2]
        for t in np.linspace(0, 1, samples, endpoint=False):
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            xs.append(x)
            ys.append(y)
    xs.append(pts[-1, 0])
    ys.append(pts[-1, 1])
    return np.asarray(xs), np.asarray(ys)
def _ancestors(node: str, parent: dict[str, str]) -> list[str]:
    chain = [node]
    while chain[-1] in parent and parent[chain[-1]] not in chain:
        chain.append(parent[chain[-1]])
    return chain
def _bundle_points(src: str, tgt: str, pos: dict[str, tuple[float, float]],                   parent: dict[str, str], samples: int = 8):
    """沿层次骨架构造边捆绑的连线路径。"""
    up_src = _ancestors(src, parent)
    up_tgt = _ancestors(tgt, parent)
    common = set(up_src) & set(up_tgt)
    lca = next((n for n in up_src if n in common), None)
    if lca is None:
        return np.array([]), np.array([])
    path = up_src[: up_src.index(lca) + 1] + list(reversed(up_tgt[: up_tgt.index(lca)]))
    pts = [pos[n] for n in path if n in pos]
    if len(pts) < 2:
        return np.array([]), np.array([])
    return _catmull_rom(pts, samples=samples)# -----------------------------# Streamlit 控件（与原版相同）# -----------------------------
def controls(shared: dict) -> None:
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]
    sample_loader_control("heb_use_sample", "heb", "heb_load_sample_btn")
    if not st.session_state.get("heb_use_sample", True):
        st.radio(            "输入数据格式",            options=["自动识别", "边表（from/to/value）", "矩阵"],            index=0,            key="heb_input_format",            help="即使手动选错格式，程序也会自动尝试按另一种格式回退解析。",        )
        st.file_uploader(            "上传数据文件（CSV / TSV / TXT / XLSX）",            type=["csv", "tsv", "txt", "xlsx"],            key="heb_file_upload",        )
    st.download_button(        "下载示例数据（HEB 示例文件）",        data=_sample_download_bytes(),        file_name="heb_example.csv",        mime="text/csv",        width="stretch",    )
    st.slider("边捆绑张力", 0.0, 1.0, 0.9, step=0.05, key="heb_bundling")
    st.slider("基础边宽", 0.1, 2.0, 0.6, step=0.1, key="heb_edge_width")
    st.slider("标签大小", 1.0, 3.0, 1.5, step=0.1, key="heb_label_size")
    st.checkbox("显示叶节点标签", value=True, key="heb_show_labels")
    with st.expander("颜色设置", expanded=False):
        st.color_picker("骨架颜色", value="#BFC9C4", key="heb_skeleton_color")
        st.color_picker("连线颜色", value="#69B3A2", key="heb_edge_color")
        st.color_picker("标签颜色", value=theme.get("text", "#000000"), key="heb_label_color")
    st.checkbox("添加图形标题", value=False, key="heb_add_title")
    if st.session_state.get("heb_add_title", False):
        st.text_input("输入标题", value="Network HEB Diagram", key="heb_title")# -----------------------------# 主构建逻辑（Plotly 版本）# -----------------------------
def build(shared: dict):
    use_sample = st.session_state.get("heb_use_sample", True)
    if use_sample:
        try:
            final_edgelist, parse_info = _sample_df()
        except Exception as exc:
            return None, None, f"示例数据读取失败：{exc}", HELP_TEXT
        note = parse_info.get("note", "")
        if note:
            if parse_info.get("actual_mode") == "matrix":
                st.warning(note)
            else:
                st.info(note)
        actual_mode_label = {            "edge": "边表",            "matrix": "矩阵",        }.get(parse_info.get("actual_mode", ""), parse_info.get("actual_mode", ""))
        shared["status"] = (            f"HEB 使用示例数据；实际解析：{actual_mode_label}；"            f"有效边数：{len(final_edgelist)}"        )
    else:
        uploaded = st.session_state.get("heb_file_upload")
        if uploaded is None:
            return None, None, "请先上传数据文件。", HELP_TEXT
        mode_label = st.session_state.get("heb_input_format", "自动识别")
        mode_map = {            "自动识别": "auto",            "边表（from/to/value）": "edge",            "矩阵": "matrix",        }
        data_mode = mode_map.get(mode_label, "auto")
        try:
            final_edgelist, parse_info = _read_heb_data(uploaded, data_mode=data_mode)
        except Exception as exc:
            return None, None, f"上传数据读取失败：{exc}", HELP_TEXT
        note = parse_info.get("note", "")
        if note:
            if parse_info.get("switched_mode", False):
                st.warning(note)
            else:
                st.info(note)
        actual_mode_label = {            "edge": "边表",            "matrix": "矩阵",        }.get(parse_info.get("actual_mode", ""), parse_info.get("actual_mode", ""))
        shared["status"] = (            f"HEB 上传成功：{uploaded.name}；用户选择：{mode_label}；"            f"实际解析：{actual_mode_label}；有效边数：{len(final_edgelist)}"        )
    if final_edgelist is None or final_edgelist.empty:
        return None, None, "没有有效边数据可用于绘图。", HELP_TEXT
    shared["data"] = final_edgelist.copy()
    all_names = sorted(        pd.unique(            pd.concat([final_edgelist["from"], final_edgelist["to"]], ignore_index=True)        ).tolist()    )
    if len(all_names) < 2:
        return None, None, "有效节点不足 2 个，无法绘制 HEB 图。", HELP_TEXT

    # 按点名层级建树（flare 的 "flare.analytics.cluster.X" 形式）
    children, root, depth = _build_hierarchy(all_names)
    leaves = [n for n in sorted(children) if not children.get(n)]
    if not leaves:
        leaves = all_names
    n_leaves = len(leaves)
    leaf_index = {name: i for i, name in enumerate(leaves)}    # 角度：90 - 360 * id / nleaves（id 从 1 开始），叶节点等距排布
    leaf_angle = {name: 90 - 360 * (i + 1) / n_leaves for i, name in enumerate(leaves)}    # 每个子树包含的叶节点编号区间 -> 子树角度取区间中点
    leaf_ids: dict[str, list[int]] = {}
    def _collect(node: str) -> list[int]:
        if not children.get(node):
            leaf_ids[node] = [leaf_index[name] for name in [node]] if node in leaf_index else []
        else:
            acc: list[int] = []
            for child in children[node]:
                acc.extend(_collect(child))
            leaf_ids[node] = acc
        return leaf_ids[node]
    _collect(root)
    max_depth = max(depth.values()) if depth else 1
    max_depth = max(max_depth, 1)
    pos: dict[str, tuple[float, float]] = {}
    node_angle: dict[str, float] = {}
    for node, d in depth.items():
        if node == "":
            pos[node] = (0.0, 0.0)
            node_angle[node] = 90.0
            continue
        ids = leaf_ids.get(node) or [0]
        angle = 90 - 360 * ((min(ids) + max(ids)) / 2 + 1) / n_leaves
        node_angle[node] = angle
        r = d / max_depth
        rad = np.deg2rad(angle)
        pos[node] = (np.cos(rad) * r, np.sin(rad) * r)    # 子节点 -> 父节点映射，供捆绑路径使用
    parent: dict[str, str] = {}
    for p, kids in children.items():
        for child in kids:
            parent[child] = p
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]
    skeleton_color = st.session_state.get("heb_skeleton_color", "#BFC9C4")
    edge_color = st.session_state.get("heb_edge_color", theme.get("sci_network_primary", "#3AA2B6"))
    label_color = st.session_state.get("heb_label_color", theme.get("text", "#000000"))
    fig = go.Figure()

    # 1. 绘制径向树骨架（环形 dendrogram）
    sk_x, sk_y = [], []
    for pnode, kids in children.items():
        for child in kids:
            if pnode not in pos or child not in pos:
                continue
            x0, y0 = pos[pnode]
            x1, y1 = pos[child]
            sk_x += [x0, x1, None]
            sk_y += [y0, y1, None]
    fig.add_trace(go.Scatter(        x=sk_x, y=sk_y,        mode="lines",        line=dict(color=skeleton_color, width=0.8),        opacity=0.6,        showlegend=False,        hoverinfo="none",    ))    # 2. 绘制捆绑连线（颜色 #69B3A2、低透明度）
    edge_width = st.session_state.get("heb_edge_width", 0.6)
    tension = float(np.clip(st.session_state.get("heb_bundling", 0.9), 0.0, 1.0))
    ln_x, ln_y = [], []
    for src, tgt in final_edgelist[["from", "to"]].itertuples(index=False, name=None):
        src, tgt = str(src), str(tgt)
        if src not in pos or tgt not in pos:
            continue
        xs, ys = _bundle_points(src, tgt, pos, parent, samples=8)
        if len(xs) == 0:
            continue        # tension 越大越贴合分层骨架；越小越接近一条直弦
        if tension < 0.999:
            lin_x = np.linspace(pos[src][0], pos[tgt][0], len(xs))
            lin_y = np.linspace(pos[src][1], pos[tgt][1], len(ys))
            xs = tension * xs + (1 - tension) * lin_x
            ys = tension * ys + (1 - tension) * lin_y
        ln_x += list(xs) + [None]
        ln_y += list(ys) + [None]
    fig.add_trace(go.Scatter(        x=ln_x, y=ln_y,        mode="lines",        line=dict(color=edge_color, width=edge_width),        opacity=0.14,        showlegend=False,        hoverinfo="none",    ))    # 3. 叶节点标签（shortName，沿半径方向旋转）
    if st.session_state.get("heb_show_labels", True):
        label_size = st.session_state.get("heb_label_size", 1.5) * 4
        for leaf in leaves:
            x, y = pos[leaf]
            lx, ly = x * 1.02, y * 1.02
            ang = leaf_angle[leaf]
            if ang < -90:
                ang += 180
            if abs(x) >= abs(y):
                xanchor = "left" if x > 0 else "right"
                yanchor = "middle"
            else:
                xanchor = "center"
                yanchor = "top" if y > 0 else "bottom"
            fig.add_annotation(                x=lx, y=ly,                text=_short_name(leaf),                showarrow=False,                font=dict(size=label_size, color=label_color),                textangle=-ang,                xanchor=xanchor,                yanchor=yanchor,            )    # 5. 标题
    title_text = ""
    if st.session_state.get("heb_add_title", False):
        title_text = st.session_state.get("heb_title", "Network HEB Diagram")
    fig.update_layout(        title=dict(text=title_text, font=dict(color=theme.get("text", "#000000")), x=0.5),        xaxis=dict(visible=False, range=[-1.18, 1.18]),        yaxis=dict(visible=False, range=[-1.18, 1.18]),        plot_bgcolor=theme.get("bg", "#f5f7fb"),        paper_bgcolor=theme.get("bg", "#f5f7fb"),        width=800,        height=800,        margin=dict(l=20, r=20, t=50, b=20),        hovermode=False    )
    shared["last_plotly"] = fig
    shared["help_text"] = HELP_TEXT
    shared["status"] = shared.get("status", f"HEB 图已生成，有效边数：{len(final_edgelist)}")
    return fig, final_edgelist, shared["status"], HELP_TEXT
def render(shared: dict):
    controls(shared)
    return build(shared)
__call__ = render