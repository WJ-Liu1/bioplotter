from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_bytes, sample_text, sample_loader_control
from app.core.theme import THEMES


HELP_TEXT = """
Sankey 桑基图

输入要求：
1. 连边表至少 4 列：source / target / value / colorlink
2. 节点表至少 2 列：nodes / colornode

支持两种输入方式：
- 上传连边 / 节点文件
- 直接粘贴连边 / 节点文本（Tab 分隔）

参数说明：
- 标签字体：节点标签使用的字体
- 末级节点靠右：尽量把末端节点排到右侧
- 节点宽度：节点矩形宽度
- 节点间距：节点之间的垂直间距
- 标签字号：节点标签字号

说明：
- 当前使用 Plotly Sankey 实现
- 视觉上采用经典桑基图样式，但不做像素级复刻
"""


DEFAULT_NODE_COLOR = "#3AA2B6"  # SCI 网络类主色
DEFAULT_LINK_COLOR = "rgba(160,160,160,0.45)"


def _sample_zip_bytes() -> bytes:
    buf = BytesIO()
    with ZipFile(buf, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("linksdata.txt", sample_bytes("sankey_links"))
        zf.writestr("nodesdata.txt", sample_bytes("sankey_nodes"))
    buf.seek(0)
    return buf.getvalue()


def _parse_pasted_table(text: str) -> pd.DataFrame:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    rows = [line.split("\t") for line in lines]
    if not rows:
        return pd.DataFrame()
    header = rows[0]
    body = rows[1:]
    return pd.DataFrame(body, columns=header)


def _safe_plotly_color(value, fallback: str) -> str:
    mapping = {
        "black": "#000000",
        "white": "#FFFFFF",
        "red": "#FF0000",
        "green": "#008000",
        "blue": "#0000FF",
        "lightpink": "#FFB6C1",
        "ghostwhite": "#F8F8FF",
        "lightgreen": "#90EE90",
        "darkorange": "#FF8C00",
        "mistyrose": "#FFE4E1",
        "cadetblue": "#5F9EA0",
        "deeppink": "#FF1493",
        "gray": "#808080",
        "grey": "#808080",
        "lightgray": "#D3D3D3",
        "lightgrey": "#D3D3D3",
        "darkgray": "#A9A9A9",
        "darkgrey": "#A9A9A9",
        "orange": "#FFA500",
        "yellow": "#FFFF00",
        "purple": "#800080",
        "pink": "#FFC0CB",
        "brown": "#A52A2A",
        "cyan": "#00FFFF",
        "magenta": "#FF00FF",
        "gold": "#FFD700",
        "navy": "#000080",
        "teal": "#008080",
        "olive": "#808000",
        "maroon": "#800000",
        "silver": "#C0C0C0",
        "darkviolet": "#9400D3",
        "darkvoilet": "#9400D3",   # tolerate common typo
        "violet": "#EE82EE",
    }

    if value is None:
        return fallback

    v = str(value).strip()
    if not v:
        return fallback

    low = v.lower()

    if v.startswith("#"):
        return v
    if low.startswith("rgb(") or low.startswith("rgba("):
        return v
    if low.startswith("hsl(") or low.startswith("hsla("):
        return v
    if low.startswith("hsv(") or low.startswith("hsva("):
        return v

    return mapping.get(low, v if " " not in v else fallback)


def _with_alpha(value, alpha: float) -> str:
    """把颜色转成带 alpha 的 rgba/hex8。"""
    color = _safe_plotly_color(value, DEFAULT_LINK_COLOR)
    low = color.strip().lower()

    if low.startswith("rgba("):
        parts = low[5:-1].split(",")
        if len(parts) == 4:
            return f"rgba({parts[0].strip()},{parts[1].strip()},{parts[2].strip()},{alpha})"
    if low.startswith("rgb("):
        parts = low[4:-1].split(",")
        if len(parts) == 3:
            return f"rgba({parts[0].strip()},{parts[1].strip()},{parts[2].strip()},{alpha})"
    if low.startswith("#") and len(low) in {7, 9}:
        raw = low[1:7]
        return (
            f"rgba({int(raw[0:2], 16)},{int(raw[2:4], 16)},"
            f"{int(raw[4:6], 16)},{alpha})"
        )
    return color


def _normalize_links_nodes(links: pd.DataFrame, nodes: pd.DataFrame):
    links = links.copy()
    nodes = nodes.copy()

    if links.shape[1] < 4:
        raise ValueError("links data must have at least 4 columns: source, target, value, colorlink")
    if nodes.shape[1] < 2:
        raise ValueError("nodes data must have at least 2 columns: nodes, colornode")

    links = links.iloc[:, :4].copy()
    nodes = nodes.iloc[:, :2].copy()

    links.columns = ["source", "target", "value", "colorlink"]
    nodes.columns = ["nodes", "colornode"]

    links["source"] = links["source"].astype(str).str.strip()
    links["target"] = links["target"].astype(str).str.strip()
    links["value"] = pd.to_numeric(links["value"], errors="coerce")
    links["colorlink"] = links["colorlink"].astype(str).str.strip()

    nodes["nodes"] = nodes["nodes"].astype(str).str.strip()
    nodes["colornode"] = nodes["colornode"].astype(str).str.strip()

    links = links.dropna(subset=["source", "target", "value"]).copy()
    nodes = nodes.dropna(subset=["nodes"]).copy()

    links = links[(links["source"] != "") & (links["target"] != "") & (links["value"] > 0)].copy()
    nodes = nodes[nodes["nodes"] != ""].copy()

    if links.empty:
        raise ValueError("links data is empty or the value column cannot be parsed as positive numbers.")
    if nodes.empty:
        raise ValueError("nodes data is empty.")

    links.loc[links["colorlink"].eq("") | links["colorlink"].isna(), "colorlink"] = DEFAULT_LINK_COLOR
    # SCI 分层配色（默认）：按节点所在层级交替使用主色 / 深色，避免样例数据里的彩虹色
    if st.session_state.get("sk_sci_colors", True):
        depth: dict[str, int] = {}
        for _, row in links.iterrows():
            depth.setdefault(str(row["source"]), 0)
            depth[str(row["target"])] = max(depth.get(str(row["target"]), 0), depth[str(row["source"])] + 1)
        node_palette = {
            str(name): (DEFAULT_NODE_COLOR if depth.get(str(name), 0) % 2 == 0 else "#4A5D54")
            for name in nodes["nodes"]
        }
        nodes["colornode"] = [node_palette[str(name)] for name in nodes["nodes"]]

        def _rgba(hex_color: str, alpha: float) -> str:
            raw = hex_color.lstrip("#")
            r, g, b = (int(raw[index:index + 2], 16) for index in (0, 2, 4))
            return f"rgba({r},{g},{b},{alpha})"

        # 连线统一用浅青 + 0.35 透明度：深绿节点做源时若跟随源色会整片发灰
        link_rgba = _rgba("#8FC4D4", 0.35)
        links["colorlink"] = [link_rgba] * len(links)
    else:
        # 沿用数据列：空值再用 SCI 双色补齐
        primary = DEFAULT_NODE_COLOR
        secondary = "#4A5D54"
        nodes["colornode"] = [
            str(value).strip() if str(value).strip() else (primary if position % 2 == 0 else secondary)
            for position, value in enumerate(nodes["colornode"])
        ]

    # 默认样式：link stroke-opacity = 0.7，node rect opacity = 0.9
    links["colorlink"] = links["colorlink"].map(lambda x: _with_alpha(x, 0.7))
    nodes["colornode"] = nodes["colornode"].map(lambda x: _with_alpha(x, 0.9))

    return links.reset_index(drop=True), nodes.reset_index(drop=True)


def _load_data_from_state():
    if st.session_state.get("sk_use_sample", True):
        links_path = get_sample_path("sankey_links")
        nodes_path = get_sample_path("sankey_nodes")
        return read_table(links_path, links_path.name), read_table(nodes_path, nodes_path.name), None

    mode = st.session_state.get("sk_input_mode", "Upload data")

    if mode == "Upload data":
        links_file = st.session_state.get("sk_links_file")
        nodes_file = st.session_state.get("sk_nodes_file")

        if links_file is None or nodes_file is None:
            return None, None, "Please upload both links and nodes files."

        try:
            links = read_table(links_file, links_file.name)
            nodes = read_table(nodes_file, nodes_file.name)
        except Exception as exc:
            return None, None, f"File read failed: {exc}"

        return links, nodes, None

    paste_links = st.session_state.get("sk_paste_links", "")
    paste_nodes = st.session_state.get("sk_paste_nodes", "")

    if not paste_links.strip() or not paste_nodes.strip():
        return None, None, "In paste mode, links and nodes text cannot be empty."

    try:
        links = _parse_pasted_table(paste_links)
        nodes = _parse_pasted_table(paste_nodes)
    except Exception as exc:
        return None, None, f"Failed to parse pasted text: {exc}"

    return links, nodes, None


def controls(shared: dict) -> None:
    sample_loader_control(
        "sk_use_sample",
        ["sankey_links", "sankey_nodes"],
        "sk_load_sample_btn",
        extra_state={"sk_input_mode": "Upload data"},
    )

    if not st.session_state.get("sk_use_sample", True):
        st.selectbox(
            "数据输入方式",
            ["Upload data", "Paste data"],
            index=0,
            key="sk_input_mode",
        )
    else:
        st.caption("当前使用内置示例数据生成桑基图。")

    st.download_button(
        "下载示例数据（ZIP）",
        data=_sample_zip_bytes(),
        file_name="sampledata.zip",
        mime="application/zip",
        width="stretch",
    )

    if st.session_state.get("sk_use_sample", True):
        pass
    elif st.session_state.get("sk_input_mode", "Upload data") == "Upload data":
        st.file_uploader(
            "links data",
            type=["csv", "tsv", "txt", "xlsx"],
            key="sk_links_file",
            help="links table should contain: source, target, value, colorlink",
        )
        st.file_uploader(
            "nodes data",
            type=["csv", "tsv", "txt", "xlsx"],
            key="sk_nodes_file",
            help="nodes table should contain: nodes, colornode",
        )
    else:
        if st.button("填充示例连边数据", width="stretch"):
            st.session_state["sk_paste_links"] = sample_text("sankey_links")

        if st.button("填充示例节点数据", width="stretch"):
            st.session_state["sk_paste_nodes"] = sample_text("sankey_nodes")

        st.text_area(
            "粘贴连边数据",
            key="sk_paste_links",
            height=180,
            placeholder="在此粘贴 Tab 分隔的连边数据",
        )
        st.text_area(
            "粘贴节点数据",
            key="sk_paste_nodes",
            height=180,
            placeholder="在此粘贴 Tab 分隔的节点数据",
        )

    st.markdown("---")
    st.selectbox(
        "标签字体",
        [
            "serif",
            "monospace",
            "cursive",
            "fantasy",
            "system-ui",
            "Times New Roman",
            "Microsoft YaHei",
            "Microsoft JhengHei",
            "SimSun",
            "SimHei",
            "KaiTi",
            "FangSong",
            "NSimSun",
            "DFKai-SB",
        ],
        index=0,
        key="sk_font_family",
    )

    st.checkbox(
        "使用 SCI 分层配色",
        value=False,
        key="sk_sci_colors",
        help="关闭（默认）时节点与连线颜色直接取数据中的 colornode / colorlink 列；开启后改为按层级交替的 SCI 双色。",
    )


def advanced_controls(shared: dict) -> None:
    """Sankey 的高级参数：节点布局与标签尺寸。"""
    st.toggle(
        "末级节点靠右",
        key="sk_sinks_right",
    )
    st.slider("节点宽度", min_value=1, max_value=50, value=30, step=1, key="sk_node_width")
    st.slider("节点间距", min_value=1, max_value=50, value=30, step=1, key="sk_node_padding")
    st.slider("标签字号", min_value=1, max_value=30, value=15, step=1, key="sk_font_size")


def build(shared: dict):
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    links_raw, nodes_raw, err = _load_data_from_state()
    if err:
        return None, None, err, HELP_TEXT

    try:
        links, nodes = _normalize_links_nodes(links_raw, nodes_raw)
    except Exception as exc:
        return None, None, str(exc), HELP_TEXT

    node_names = nodes["nodes"].tolist()
    node_index = {name: i for i, name in enumerate(node_names)}

    missing_sources = sorted(set(links["source"]) - set(node_names))
    missing_targets = sorted(set(links["target"]) - set(node_names))
    if missing_sources or missing_targets:
        msg = []
        if missing_sources:
            msg.append(f"links contain sources not defined in nodes: {', '.join(missing_sources[:10])}")
        if missing_targets:
            msg.append(f"links contain targets not defined in nodes: {', '.join(missing_targets[:10])}")
        return None, {"links": links, "nodes": nodes}, "；".join(msg), HELP_TEXT

    links["IDsource"] = links["source"].map(node_index).astype(int)
    links["IDtarget"] = links["target"].map(node_index).astype(int)

    # Plotly Sankey 会把较大的节点索引排在上方；默认布局按数据顺序自上而下。
    # 反转节点表，让第一行（示例中的 gene）位于顶部，与默认输出的方向一致。
    plot_order = list(range(len(node_names)))[::-1]
    remap = {old: new for new, old in enumerate(plot_order)}
    links["IDsource"] = links["IDsource"].map(remap).astype(int)
    links["IDtarget"] = links["IDtarget"].map(remap).astype(int)
    plot_nodes = nodes.iloc[plot_order].reset_index(drop=True)

    node_width = st.session_state.get("sk_node_width", 30)
    node_padding = st.session_state.get("sk_node_padding", 30)
    font_family = st.session_state.get("sk_font_family", "serif")
    font_size = st.session_state.get("sk_font_size", 15)
    sinks_right = bool(st.session_state.get("sk_sinks_right", False))

    arrangement = "snap" if sinks_right else "perpendicular"

    fig = go.Figure(
        go.Sankey(
            # 右侧留 18% 宽度给末级节点的标签，否则 x=1 处的名称会被画布裁掉
            domain=dict(x=[0.0, 0.82], y=[0.0, 1.0]),
            arrangement=arrangement,
            node=dict(
                pad=node_padding,
                thickness=node_width,
                line=dict(color="rgba(0,0,0,0.25)", width=0.5),
                label=plot_nodes["nodes"].tolist(),
                color=plot_nodes["colornode"].tolist(),
            ),
            link=dict(
                source=links["IDsource"].tolist(),
                target=links["IDtarget"].tolist(),
                value=links["value"].tolist(),
                color=links["colorlink"].tolist(),
            ),
        )
    )

    title = ""
    bg_color = theme.get("bg", "#f5f7fb")
    text_color = theme.get("text", "#111827")

    fig.update_layout(
        title=title,
        font=dict(family=font_family, size=font_size, color=text_color),
        paper_bgcolor=bg_color,
        plot_bgcolor=bg_color,
        height=560,
        margin=dict(l=10, r=140, t=60, b=20),
    )

    shared["last_plotly"] = fig
    shared["data"] = {"links": links, "nodes": nodes}
    shared["status"] = f"Sankey 已生成：{len(nodes)} 个节点，{len(links)} 条连边。"
    shared["help_text"] = HELP_TEXT

    return fig, {"links": links, "nodes": nodes}, shared["status"], HELP_TEXT


def render(shared: dict):
    return build(shared)


__call__ = render
