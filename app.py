from __future__ import annotations

import copy
import html
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from string import Template

import matplotlib.pyplot as plt
import pandas as pd
import plotly.io as pio
import streamlit as st

try:
    from app.core.catalog import (
        CATEGORY_ORDER,
        DATA_SHAPE_ORDER,
        PLOTS,
        data_shape_for,
        difficulty_for,
        grouped_plots,
        meta_for,
        preview_svg,
        search_plots,
    )
except ImportError as exc:
    # 旧 Streamlit 进程会缓存已导入模块，热重载只重跑 app.py，导致新符号缺失。
    st.error(
        "检测到旧的后台进程仍在运行，新代码无法加载。\n\n"
        "请关闭当前运行窗口，重新运行 `start_app.bat`（或重启 streamlit）后再刷新页面。"
    )
    st.caption(f"原始错误：{exc}")
    st.stop()
from app.docs_hub import close_doc, render_docs_cards, render_docs_detail, select_doc
from app.core.figure_style import (
    FONT_FAMILIES,
    GRID_MODES,
    LEGEND_POSITIONS,
    apply_figure_style,
    init_figure_style_defaults,
    normalized_export_stem,
    plot_style_signature,
    reset_figure_style,
    style_source_label,
)
from app.core.export_check import (
    JOURNAL_TEMPLATES,
    build_export_check,
    diagnose_static_export_error,
    figure_font_info,
)
from app.core.export_static import render_html_bytes, render_static_bytes
from app.core.plot_utils import fig_to_bytes
from app.core.layout_guard import prevent_label_clipping
from app.core.sample_utils import SAMPLE_PATHS, sample_zip_bytes
from app.core.palettes import SCI_PALETTES
from app.core.project_io import (
    BUNDLE_KEY,
    BUNDLE_MODULE_KEY,
    BUNDLE_NAME_KEY,
    BUNDLE_SIG_KEY,
    build_project_bundle,
    install_project_uploader,
    project_filename,
    project_signature,
    restore_project_bundle,
)
from app.core.theme import THEMES, apply_sci_theme
from app.modules import (
    arc,
    beeswarm,
    bubble,
    chord_edgelist,
    circle_viz,
    circular_bar,
    genomic_variation,
    goenrich,
    grouped_matrix,
    heatmap,
    heb,
    kaplan_meier,
    manhattan,
    mantel,
    nodelink,
    paired_tree,
    pca,
    pirate,
    raincloud,
    sankey_d3,
    scaboxden,
    splitviolin,
    upset,
    volcano,
)

# 模块注册：直接存储模块对象，不要加 .render
MODULES = {
    "Arc Diagram": arc,
    "Hierarchical Edge Bundling": heb,
    "Pirate Plot": pirate,
    "Chord Diagram": chord_edgelist,
    "Node-link Diagram": nodelink,
    "Raincloud Plot": raincloud,
    "Mantel Test": mantel,
    "Beeswarm": beeswarm,
    "GO Enrichment": goenrich,
    "Sankey": sankey_d3,
    "ScaBoxDen": scaboxden,
    "Split Violin": splitviolin,
    # 原生融合（原 iframe 外挂应用重写）
    "BubbleViz": bubble,
    "Grouped Matrix Plotting": grouped_matrix,
    "CircleViz": circle_viz,
    "CircularBarPlot": circular_bar,
    "Genomic Variation Viewer": genomic_variation,
    # 新增 6 个生信模块
    "Volcano Plot": volcano,
    "PCA": pca,
    "Heatmap": heatmap,
    "UpSet Plot": upset,
    "Kaplan-Meier": kaplan_meier,
    "Manhattan Plot": manhattan,
    # 双树比较（原生 Plotly 实现）
    "Paired Tree Comparison": paired_tree,
}

BRAND = "BioPlotter"
TAGLINE = "Visualization Studio"

# 界面上暴露的主题（Paper 为默认）；其余主题保留键值以兼容旧项目包
THEME_CHOICES = ("Paper", "Slate", "Warm", "Midnight")
STYLE_FILE = Path(__file__).resolve().parent / "app" / "assets" / "styles.css"


@lru_cache(maxsize=1)
def _load_styles() -> str:
    """外置主题样式表：assets/styles.css，含 $placeholder 占位符。"""
    return STYLE_FILE.read_text(encoding="utf-8")

st.set_page_config(
    page_title=f"{BRAND} · 生物数据可视化工作台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="auto",
)


def init_state() -> None:
    defaults = {
        "page": "home",
        "plot_type": None,
        "figure_title": "",
        "last_fig": None,
        "last_plotly": None,
        "data": None,
        "status": None,
        "status_kind": "info",
        "status_time": None,
        "help_text": None,
        "last_plot_key": None,
        "figure_revision": 0,
        "last_style_signature": None,
        "theme": "Paper",
        "gallery_query": "",
        "gallery_category": "全部",
        "gallery_shape": "全部形状",
        "sci_palette": "Auto",
        "sci_palette_applied": "Auto",
        "home_category_anchor": "",
        "doc_selected": None,
        "_doc_param_seen": None,
        "_boot_done": False,
    }
    init_figure_style_defaults(defaults)
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def sync_theme_widget_state() -> None:
    """主题被项目恢复等方式外部改写时，把下拉框同步到新值；用户手动切换时保留其选择。"""
    theme = st.session_state.get("theme", "Paper")
    applied = st.session_state.get("_theme_applied")
    if applied is None:
        st.session_state["_theme_applied"] = theme
        return
    if applied != theme:
        st.session_state["_theme_applied"] = theme
        st.session_state["theme_selector_top"] = theme


def clear_cached_outputs() -> None:
    st.session_state["last_fig"] = None
    st.session_state["last_plotly"] = None
    st.session_state["data"] = None
    st.session_state["status"] = None
    st.session_state["status_kind"] = "info"
    st.session_state["status_time"] = None
    st.session_state["help_text"] = None


def _qp_value(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def sync_route_from_query() -> None:
    page = _qp_value(st.query_params.get("page"))
    plot = _qp_value(st.query_params.get("plot"))

    if page == "plot" and plot in MODULES:
        st.session_state.page = "plot"
        st.session_state.plot_type = plot
        if not st.session_state.figure_title:
            st.session_state.figure_title = plot
    elif page == "docs":
        # 文档已并入首页：旧链接统一落到首页的展开态
        st.session_state.page = "home"
        st.session_state.plot_type = None
    else:
        st.session_state.page = "home"
        st.session_state.plot_type = None


def sync_doc_state() -> None:
    """URL 里的 doc 只在真正变化时同步到会话，避免每次 rerun 覆盖本地选择。"""
    url_doc = _qp_value(st.query_params.get("doc"))
    if url_doc not in PLOTS:
        url_doc = None
    if url_doc != st.session_state.get("_doc_param_seen"):
        st.session_state["_doc_param_seen"] = url_doc
        st.session_state["doc_selected"] = url_doc


def open_plot(plot: str) -> None:
    st.session_state.page = "plot"
    st.session_state.plot_type = plot
    st.session_state.figure_title = plot
    st.session_state.last_plot_key = None
    clear_cached_outputs()
    st.query_params["page"] = "plot"
    st.query_params["plot"] = plot
    st.rerun()


def go_home() -> None:
    st.session_state.page = "home"
    st.session_state.plot_type = None
    st.query_params["page"] = "home"
    if "plot" in st.query_params:
        del st.query_params["plot"]
    st.rerun()


def reset_module_colors() -> None:
    """切换主题时清除模块自定义颜色，使其回到新主题默认值。"""
    prefixes = [
        "arc_",
        "bee_",
        "ch_",
        "chord_",
        "go_",
        "heb_",
        "mt_",
        "mantel_",
        "ndl_",
        "pir_",
        "pirate_",
        "rc_",
        "rain_",
        "sk_",
        "sankey_",
        "sbd_",
        "splitviolin_",
        "sv_",
        "bubble_",
        "gmp_",
        "circle_",
        "cbar_",
        "genvar_",
        "volcano_",
        "pca_",
        "heatmap_",
        "upset_",
        "km_",
        "manhattan_",
        "pt_",
    ]

    keys_to_delete = []
    for key in list(st.session_state.keys()):
        if any(key.startswith(prefix) for prefix in prefixes):
            if (
                "color" in key
                or "fill" in key
                or "edge" in key
                or "reg" in key
                or "line" in key
                or "bg" in key
            ):
                keys_to_delete.append(key)

    for key in keys_to_delete:
        del st.session_state[key]


def _rgba(hex_color: str, alpha: float) -> str:
    """把 #rrggbb 转成 rgba(...)，用于生成强调色的淡化底色。"""
    raw = str(hex_color).lstrip("#")
    if len(raw) != 6:
        return f"rgba(20,101,90,{alpha})"
    red, green, blue = (int(raw[index:index + 2], 16) for index in (0, 2, 4))
    return f"rgba({red},{green},{blue},{alpha})"


def inject_css() -> None:
    theme = THEMES.get(st.session_state.theme, THEMES["Paper"])
    dark = theme.get("mode") == "dark"

    line = "rgba(255,255,255,0.10)" if dark else "rgba(15,23,42,0.08)"
    line_strong = "rgba(255,255,255,0.16)" if dark else "rgba(15,23,42,0.14)"
    shadow = "0 18px 44px rgba(0,0,0,0.35)" if dark else "0 12px 34px rgba(15,23,42,0.07)"
    preview_bg = theme.get("preview_bg", "#242735" if dark else "#f8fafc")
    preview_grid = theme.get("preview_grid", "#343a4d" if dark else "#e5e9f0")
    preview_ink = theme.get("preview_ink", "#e5e7eb" if dark else "#0f172a")
    hero_one = theme.get("hero_one", "rgba(52,211,153,0.16)" if dark else "rgba(36,162,106,0.13)")
    hero_two = theme.get("hero_two", "rgba(59,130,246,0.14)" if dark else "rgba(59,130,246,0.10)")
    bg_blur = theme.get("bg_blur", "rgba(30,30,46,0.96)" if dark else "rgba(245,247,251,0.98)")
    sidebar_bg = theme.get("sidebar_bg", "#e9eef5")
    sidebar_panel = theme.get("sidebar_panel", "#f8fafc")
    sidebar_text = theme.get("sidebar_text", "#1f2937")
    sidebar_muted = theme.get("sidebar_muted", "#64748b")
    sidebar_line = theme.get("sidebar_line", "rgba(15,23,42,0.10)")
    sidebar_hover = theme.get("sidebar_hover", "#dde5ef")
    sidebar_field_bg = theme.get("sidebar_field_bg", "#ffffff")
    sidebar_field_text = theme.get("sidebar_field_text", "#0f172a")
    sidebar_field_ph = sidebar_muted
    accent_soft = _rgba(theme["accent"], 0.16 if dark else 0.07)
    accent_line = _rgba(theme["accent"], 0.45 if dark else 0.28)

    css = Template(_load_styles()).substitute(
        bg=theme["bg"],
        panel=theme["panel"],
        text=theme["text"],
        muted=theme["muted"],
        primary=theme["primary"],
        accent=theme["accent"],
        line=line,
        line_strong=line_strong,
        shadow=shadow,
        preview_bg=preview_bg,
        preview_grid=preview_grid,
        preview_ink=preview_ink,
        hero_one=hero_one,
        hero_two=hero_two,
        bg_blur=bg_blur,
        sidebar_bg=sidebar_bg,
        sidebar_panel=sidebar_panel,
        sidebar_text=sidebar_text,
        sidebar_muted=sidebar_muted,
        sidebar_line=sidebar_line,
        sidebar_hover=sidebar_hover,
        sidebar_field_bg=sidebar_field_bg,
        sidebar_field_text=sidebar_field_text,
        sidebar_field_ph=sidebar_field_ph,
        accent_soft=accent_soft,
        accent_line=accent_line,
    )

    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_sidebar_brand() -> None:
    st.markdown(
        f"""
        <div class="sidebar-brand">
            <div class="brand-mark">B</div>
            <div>
                <div class="brand-name">{BRAND}</div>
                <div class="brand-sub">{TAGLINE}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_theme_picker(key: str) -> None:
    theme_options = list(THEME_CHOICES)
    current = st.session_state.theme
    if current not in theme_options:
        theme_options.append(current)
    theme_labels = {
        "Paper": "Paper · 纸白",
        "Light": "Light · 明亮",
        "Dark": "Dark · 暗色",
        "Ocean": "Ocean · 海洋",
        "Forest": "Forest · 森林",
        "Sunset": "Sunset · 日落",
        "Lavender": "Lavender · 薰衣草",
        "Slate": "Slate · 石板",
        "Warm": "Warm · 暖米",
        "Midnight": "Midnight · 午夜",
        "Nord": "Nord · 北欧",
    }
    selected_theme = st.selectbox(
        "界面主题",
        options=theme_options,
        index=theme_options.index(current),
        format_func=lambda name: theme_labels.get(name, name),
        key=key,
    )
    if selected_theme != st.session_state.theme:
        st.session_state.theme = selected_theme
        st.session_state["_theme_applied"] = selected_theme
        reset_module_colors()
        st.rerun()


PALETTE_LABELS: dict[str, str] = {
    "Auto": "Auto · 按图类型",
    "No.001": "No.001 · 黑白藏青",
    "No.002": "No.002 · 米白砖红",
    "No.003": "No.003 · 墨绿珊瑚",
    "No.005": "No.005 · 湖蓝橄榄",
    "No.009": "No.009 · 苔绿棕金",
    "No.012": "No.012 · 灰绿玫瑰",
    "No.013": "No.013 · 青蓝沙金",
    "No.015": "No.015 · 雾蓝酒红",
    "No.018": "No.018 · 深紫陶红",
    "No.021": "No.021 · 靛蓝灰米",
}


def render_palette_picker() -> None:
    """侧栏 SCI 配色选择：Auto 保持各图自己的语义色，指定色板则统一分组色。"""
    options = ["Auto", *SCI_PALETTES.keys()]
    current = st.session_state.get("sci_palette", "Auto")
    if current not in options:
        current = "Auto"

    selected = st.selectbox(
        "SCI 配色",
        options=options,
        index=options.index(current),
        format_func=lambda value: PALETTE_LABELS.get(value, value),
        key="sci_palette",
    )

    if selected != st.session_state.get("sci_palette_applied"):
        st.session_state.sci_palette_applied = selected
        apply_sci_theme(selected)
        # 清掉模块自定义颜色 + 已生成的图，下一次渲染就会用新色板重画
        reset_module_colors()
        clear_cached_outputs()
        st.session_state.last_plot_key = None
        st.rerun()


def render_project_panel(meta=None) -> None:
    """Save/restore a self-contained .bioplot.zip project bundle."""
    render_project_save_section(meta)
    render_project_restore_section()


def render_project_save_section(meta=None) -> None:
    """项目包保存区：准备 + 下载。仅在绘图页（meta 不为 None）渲染。"""
    if meta is None:
        return
    plot_name = meta.name
    if st.button(
        "准备项目包",
        key=f"project_prepare_{plot_name}",
        width="stretch",
    ):
        try:
            bundle, filename, signature = build_project_bundle(
                plot_name, meta, st.session_state
            )
            st.session_state[BUNDLE_KEY] = bundle
            st.session_state[BUNDLE_NAME_KEY] = filename
            st.session_state[BUNDLE_SIG_KEY] = signature
            st.session_state[BUNDLE_MODULE_KEY] = plot_name
            st.success("项目包已准备好，点击下方按钮下载。")
        except Exception as exc:
            st.error(f"项目包生成失败：{exc}")

    bundle = st.session_state.get(BUNDLE_KEY)
    module_matches = st.session_state.get(BUNDLE_MODULE_KEY) == plot_name
    if bundle and module_matches:
        current_signature = project_signature(plot_name, st.session_state)
        stored_signature = st.session_state.get(BUNDLE_SIG_KEY)
        if stored_signature and stored_signature != current_signature:
            st.warning("参数或数据已变化，请重新准备项目包。")
        else:
            st.download_button(
                "下载项目包",
                data=bundle,
                file_name=st.session_state.get(BUNDLE_NAME_KEY)
                or project_filename(plot_name, st.session_state),
                mime="application/zip",
                width="stretch",
                key=f"project_download_{plot_name}",
            )
            st.caption(
                "包含数据、参数、主题与图形配置 · "
                f"{len(bundle) / 1024:.1f} KB"
            )
    st.caption("项目包可在刷新、换机器或交接时恢复当前模块。")


def render_project_restore_section() -> None:
    """项目包恢复区：上传 + 载入。首页与绘图页共用。"""
    st.markdown("---")
    uploaded = st.file_uploader(
        "打开项目包（.bioplot.zip）",
        type=["zip"],
        key="project_open_upload",
    )
    if st.button(
        "载入项目",
        key="project_restore_btn",
        width="stretch",
        disabled=uploaded is None,
    ):
        try:
            manifest = restore_project_bundle(
                uploaded.getvalue(), st.session_state, MODULES
            )
            module_name = str(manifest.get("module") or "")
            title = str(manifest.get("figure_title") or module_name or "项目")
            st.session_state["_project_restore_notice"] = (
                f"项目包已恢复：{title} · {module_name}。"
                "数据与参数已载入，正在重新生成预览。"
            )
            st.rerun()
        except Exception as exc:
            st.error(f"项目包无法载入：{exc}")


def render_project_restore_notice() -> None:
    """在页面顶层显示一次性的项目恢复反馈。"""
    notice = st.session_state.pop("_project_restore_notice", None)
    if notice:
        st.success(notice)


def render_home_sidebar() -> None:
    with st.sidebar:
        render_sidebar_brand()
        render_project_restore_notice()
        with st.expander("项目包", expanded=False):
            render_project_restore_section()

        active_category = st.session_state.get("gallery_category", "全部")
        st.markdown(
            f'<div class="sidebar-label">图形库'
            f'<span class="sidebar-label-count">{len(MODULES)}</span></div>'
            '<div class="sidebar-hint">展开分类查看图形；点卡片看文档</div>',
            unsafe_allow_html=True,
        )
        for category, names in grouped_plots().items():
            # 只有用户在主区域选定具体分类时才自动展开，首屏保持全部收起
            is_open = active_category == category
            with st.expander(f"{category} · {len(names)}", expanded=is_open):
                for name in names:
                    st.button(
                        name,
                        key=f"nav_{name}",
                        width="stretch",
                        on_click=open_plot,
                        args=(name,),
                    )

        st.markdown(
            f'<div class="sidebar-foot">v3.0 · {len(MODULES)} 个图形模块 · '
            f"{len(CATEGORY_ORDER)} 个分类<br>{len(SAMPLE_PATHS)} 份内置示例数据</div>",
            unsafe_allow_html=True,
        )


def render_plot_sidebar(module_obj, meta) -> None:
    with st.sidebar:
        render_sidebar_brand()
        render_project_restore_notice()

        if st.button("← 返回图形库", width="stretch"):
            go_home()

        st.markdown(
            f"""
            <div class="sidebar-current">
                <b>{html.escape(meta.name)}</b>
                <span>{html.escape(meta.category)} · {html.escape(meta.inputs)}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        render_palette_picker()

        st.markdown("---")

        controls = getattr(module_obj, "controls", None)
        advanced_controls = getattr(module_obj, "advanced_controls", None)
        caption = "数据、样式与标注参数由当前模块提供，修改后点击「生成图形」。"

        if callable(advanced_controls):
            with st.expander("常用参数", expanded=True):
                st.caption(caption)
                if callable(controls):
                    controls(st.session_state)
                else:
                    st.info("当前模块未提供 controls()，将直接使用 build()/render()。")
            with st.expander("高级参数", expanded=False):
                st.caption("聚类、标注、细节层级等进阶选项；展开后修改并重新生成。")
                advanced_controls(st.session_state)
        else:
            with st.expander("参数设置", expanded=True):
                st.caption(caption)
                if callable(controls):
                    controls(st.session_state)
                else:
                    st.info("当前模块未提供 controls()，将直接使用 build()/render()。")






def render_topbar() -> None:
    """主内容区内的 sticky 顶栏：品牌 + 导航 + 计数 + 搜索 + 主题切换。

    必须是 stMain 的第一个元素，否则 sticky 定位会错乱（架构 §6.1）。
    """
    on_home = st.session_state.page == "home"

    with st.container(key="topbar"):
        brand_col, search_col, theme_col = st.columns([2.15, 1.15, 0.7], gap="small")

        with brand_col:
            library_class = "active" if on_home else ""
            st.markdown(
                f"""
                <div class="topbar">
                    <div class="topbar-brand">{BRAND}<span>v3.0</span></div>
                    <nav class="topbar-nav">
                        <a class="{library_class}" href="?page=home" target="_self">图形库</a>
                        <a data-secondary="1" href="?page=home#quickstart" target="_self">快速开始</a>
                        <a data-secondary="1" href="?page=home#about" target="_self">关于</a>
                    </nav>
                </div>
                """,
                unsafe_allow_html=True,
            )

        if on_home:
            with search_col:
                st.text_input(
                    "搜索图形",
                    key="gallery_query",
                    placeholder="搜索图形…",
                    label_visibility="collapsed",
                )

        with theme_col:
            render_theme_picker("theme_selector_top")


def render_page_head() -> None:
    st.markdown(
        f"""
        <div class="page-head">
            <div class="page-head-copy">
                <h1>为每一类组学数据，找到合适的图形表达</h1>
                <p>{len(MODULES)} 个生物信息学图形模块，参数在左侧实时调整，示例数据开箱即用。</p>
            </div>
            <div class="stat-chips">
                <span class="stat-chip"><b>{len(MODULES)}</b> 个模块</span>
                <span class="stat-chip"><b>{len(CATEGORY_ORDER)}</b> 个分类</span>
                <span class="stat-chip"><b>{len(SAMPLE_PATHS)}</b> 份示例数据</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_start_guide() -> None:
    """首页三步引导：准备数据 → 选择图表 → 调参导出（紧凑卡片，非 hero）。"""
    shape_hint = " / ".join(DATA_SHAPE_ORDER)
    st.markdown(
        f"""
        <div class="start-guide">
            <div class="guide-step">
                <div class="guide-idx">1</div>
                <div class="guide-body">
                    <b>准备数据</b>
                    <span>CSV / TSV / XLSX，按数据形状组织：{html.escape(shape_hint)}</span>
                </div>
            </div>
            <div class="guide-step">
                <div class="guide-idx">2</div>
                <div class="guide-body">
                    <b>选择图表</b>
                    <span>按分类或数据形状筛选，卡片上标注了数据形状与上手难度</span>
                </div>
            </div>
            <div class="guide-step">
                <div class="guide-idx">3</div>
                <div class="guide-body">
                    <b>调参导出</b>
                    <span>左侧调参，支持 HTML / JSON / PNG / SVG / PDF 导出</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def reset_gallery_filters() -> None:
    st.session_state.gallery_query = ""
    st.session_state.gallery_category = "全部"
    st.session_state.gallery_shape = "全部形状"


def render_gallery_controls() -> list[str]:
    filters_active = bool(
        st.session_state.gallery_query
        or st.session_state.gallery_category != "全部"
        or st.session_state.gallery_shape != "全部形状"
    )
    with st.container(key="gallery-filters"):
        if filters_active:
            pill_col, shape_col, count_col, clear_col = st.columns([4.0, 0.95, 0.6, 0.55])
        else:
            pill_col, shape_col, count_col = st.columns([4.3, 1.0, 0.75])
            clear_col = None
        names = _gallery_filter_row(pill_col, shape_col, count_col)
        if clear_col is not None:
            with clear_col:
                if st.button("清除", key="gallery_clear", width="content"):
                    reset_gallery_filters()
                    st.rerun()
    return names


def _gallery_filter_row(pill_col, shape_col, count_col) -> list[str]:
    with pill_col:
        st.radio(
            "分类",
            options=["全部", *CATEGORY_ORDER],
            key="gallery_category",
            horizontal=True,
            label_visibility="collapsed",
        )
    with shape_col:
        st.selectbox(
            "数据形状",
            options=["全部形状", *DATA_SHAPE_ORDER],
            key="gallery_shape",
            label_visibility="collapsed",
        )
    names = search_plots(
        st.session_state.gallery_query,
        st.session_state.gallery_category,
        st.session_state.gallery_shape,
    )
    with count_col:
        st.markdown(
            f'<div class="filter-count">'
            f'<span class="topbar-count">显示 {len(names)} / {len(MODULES)}</span></div>',
            unsafe_allow_html=True,
        )
    return names


def _slugify(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "-", name).strip("-").lower()


def gallery_card_html(plot_name: str) -> str:
    meta = meta_for(plot_name)
    preview = preview_svg(plot_name).strip()
    return f"""
        <article class="gallery-card">
            <div class="gallery-preview">
                {preview}
                <div class="gallery-hover">
                    <p>{html.escape(meta.summary)}</p>
                </div>
            </div>
            <div class="gallery-card-body">
                <div class="gallery-card-top">
                    <span class="pill">{html.escape(meta.category)}</span>
                </div>
                <h3>{html.escape(meta.name)}</h3>
            </div>
        </article>
        """


def render_gallery(names: list[str]) -> None:
    if not names:
        st.markdown(
            """
            <div class="empty-state">
                <div class="icon">?</div>
                <h3>没有匹配的图形</h3>
                <p>试试更短的关键词，或切换到「全部」分类。</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.button("清除筛选", on_click=reset_gallery_filters)
        return

    for start in range(0, len(names), 4):
        columns = st.columns(4, gap="medium")
        for column, plot_name in zip(columns, names[start:start + 4]):
            with column:
                with st.container(key=f"gallery-card-{_slugify(plot_name)}"):
                    st.markdown(gallery_card_html(plot_name), unsafe_allow_html=True)
                    st.button(
                        f"查看 {plot_name} 的说明",
                        key=f"gallery_pick_{_slugify(plot_name)}",
                        on_click=select_doc,
                        args=(plot_name,),
                        width="stretch",
                    )




def show_home() -> None:
    render_page_head()
    doc = st.session_state.get("doc_selected")
    if doc not in PLOTS:
        doc = None
    if doc is None:
        render_start_guide()
    names = render_gallery_controls()
    if doc is not None:
        if names and doc not in names:
            doc = names[0]
            st.session_state["doc_selected"] = doc
        with st.container(key="docs-close-wrap"):
            st.button(
                "← 收起文档",
                key="docs_close",
                on_click=close_doc,
                type="tertiary",
                width="content",
            )
        cards_col, detail_col = st.columns([1.45, 1.0], gap="large")
        with cards_col:
            with st.container(key="gallery-split"):
                render_docs_cards(names, doc)
        with detail_col:
            render_docs_detail(doc)
    else:
        render_gallery(names)
    render_footer()


def render_plot_header(meta) -> None:
    st.markdown(
        f"""
        <div class="plot-header">
            <div class="breadcrumb">
                <a href="?page=home" target="_self">图形库</a>
                <span>/</span>
                <span>{html.escape(meta.category)}</span>
                <span>/</span>
                <span>{html.escape(meta.name)}</span>
            </div>
            <div class="plot-title-row">
                <div>
                    <h1>{html.escape(meta.name)}</h1>
                    <p>{html.escape(meta.summary)}</p>
                </div>
                <span class="pill">{html.escape(meta.category)}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_help(meta) -> None:
    st.markdown(f"**{html.escape(meta.name)}**")
    st.write(meta.summary)
    st.caption("输入格式")
    st.code(meta.inputs, language=None)
    help_text = st.session_state.get("help_text")
    if help_text:
        st.markdown("---")
        st.markdown(str(help_text))


def _render_frame(frame: pd.DataFrame, max_rows: int) -> None:
    st.caption(f"{len(frame):,} 行 × {frame.shape[1]} 列")
    st.dataframe(frame.head(max_rows), width="stretch")


def render_data_health(data) -> None:
    """数据体检：规模 / 类型 / 缺失 / 重复 / 常量列，一行 metric + 一行 caption。"""
    if isinstance(data, pd.Series):
        data = data.to_frame()
    if not isinstance(data, pd.DataFrame) or data.empty:
        return

    rows, cols = data.shape
    numeric_cols = data.select_dtypes(include="number").shape[1]
    category_cols = cols - numeric_cols
    total_cells = rows * cols
    missing = int(data.isna().sum().sum())
    missing_ratio = (missing / total_cells * 100.0) if total_cells else 0.0
    duplicates = int(data.duplicated().sum())
    constant_cols = int(sum(1 for column in data.columns if data[column].nunique(dropna=False) <= 1))

    metric_cols = st.columns(4)
    with metric_cols[0]:
        st.metric("行 × 列", f"{rows:,} × {cols}")
    with metric_cols[1]:
        st.metric("数值列", f"{numeric_cols}")
    with metric_cols[2]:
        st.metric("分类列", f"{category_cols}")
    with metric_cols[3]:
        st.metric("缺失率", f"{missing_ratio:.1f}%")

    notes: list[str] = []
    if missing:
        notes.append(f"缺失单元格 {missing:,} 个（{missing_ratio:.1f}%）")
    if duplicates:
        notes.append(f"重复行 {duplicates:,} 行")
    if constant_cols:
        notes.append(f"常量列 {constant_cols} 列")
    if notes:
        st.warning("数据体检：" + "；".join(notes) + "。绘图前建议先清洗。")
    else:
        st.caption("数据体检：无缺失、无重复行、无常量列。")


def render_data_preview() -> None:
    data = st.session_state.get("data")
    if isinstance(data, pd.DataFrame):
        render_data_health(data)
        _render_frame(data, 200)
    elif isinstance(data, pd.Series):
        render_data_health(data)
        _render_frame(data.to_frame(), 200)
    elif isinstance(data, dict):
        items = [(str(key), value) for key, value in data.items() if value is not None]
        if not items:
            st.caption("暂无可预览的数据。")
            return
        tabs = st.tabs([key for key, _ in items])
        for tab, (_, value) in zip(tabs, items):
            with tab:
                if isinstance(value, pd.DataFrame):
                    render_data_health(value)
                    _render_frame(value, 100)
                elif isinstance(value, pd.Series):
                    render_data_health(value)
                    _render_frame(value.to_frame(), 100)
                else:
                    st.write(value)
    elif data is not None:
        st.write(data)
    else:
        st.caption("生成图形后，这里会显示本次使用的数据。")


@st.cache_resource(show_spinner=False)
def kaleido_available() -> bool:
    try:
        import kaleido  # noqa: F401

        return True
    except Exception:
        return False


# 期刊画布预设（宽度 mm）。96 dpi 是 Plotly/浏览器的 CSS 像素基准：
# 画布按 96 dpi 定尺寸，高分辨率再靠 scale 放大，这样 PNG 的物理尺寸、
# PDF/SVG 的 MediaBox 以及字号比例三者才能对齐（否则 PDF 会偏大 1/0.75 倍）。
EXPORT_PRESETS: dict[str, float | None] = {
    "单栏 85mm": 85.0,
    "1.5 栏 114mm": 114.0,
    "双栏 170mm": 170.0,
    **JOURNAL_TEMPLATES,
    "当前画布": None,
    "自定义": None,
}

EXPORT_DPI: dict[str, int] = {"300 dpi": 300, "600 dpi": 600}
EXPORT_BASE_DPI = 96
MM_PER_INCH = 25.4


def _mm_to_css_px(width_mm: float) -> int:
    return max(50, int(round(width_mm / MM_PER_INCH * EXPORT_BASE_DPI)))


def _canvas_aspect(figure) -> float:
    width = float(getattr(figure.layout, "width", None) or 960)
    height = float(getattr(figure.layout, "height", None) or 560)
    return (height / width) if width else 0.58


def _css_size(width_mm: float, height_mm: float | None, figure) -> tuple[int, int]:
    width_px = _mm_to_css_px(width_mm)
    if height_mm:
        return width_px, _mm_to_css_px(height_mm)
    return width_px, max(50, int(round(width_px * _canvas_aspect(figure))))


def _journal_size_controls(
    _key,
    figure,
    raster: bool,
) -> tuple[str, float, float | None, int, float]:
    """画布预设控件：返回 (模板名, 宽 mm, 高 mm 或 None, dpi, scale)。"""
    preset = st.selectbox(
        "画布预设",
        options=list(EXPORT_PRESETS),
        index=0,
        key=_key("export_preset"),
    )
    if preset in JOURNAL_TEMPLATES:
        st.caption("模板尺寸用于导出前预检，投稿前请以目标期刊最新指南为准。")

    width_mm = EXPORT_PRESETS[preset]
    height_mm: float | None = None

    if preset == "当前画布":
        width_px = float(getattr(figure.layout, "width", None) or 960)
        height_px = float(getattr(figure.layout, "height", None) or 560)
        width_mm = width_px / EXPORT_BASE_DPI * MM_PER_INCH
        height_mm = height_px / EXPORT_BASE_DPI * MM_PER_INCH
    elif preset == "自定义":
        aspect = _canvas_aspect(figure)
        lock_aspect = st.checkbox(
            "锁定纵横比",
            value=True,
            key=_key("export_lock_aspect"),
            help="锁定后高度按当前画布比例自动计算；关闭后可输入独立高度。",
        )
        size_cols = st.columns(2)
        with size_cols[0]:
            width_mm = float(
                st.number_input(
                    "宽度 (mm)",
                    min_value=40.0,
                    max_value=400.0,
                    value=85.0,
                    step=1.0,
                    key=_key("export_w_mm"),
                )
            )
        if lock_aspect:
            height_mm = round(width_mm * aspect, 1)
            with size_cols[1]:
                st.caption(f"高度自动：{height_mm:.1f} mm")
        else:
            with size_cols[1]:
                height_mm = float(
                    st.number_input(
                        "高度 (mm)",
                        min_value=30.0,
                        max_value=400.0,
                        value=round(85.0 * aspect, 1),
                        step=1.0,
                        key=_key("export_h_mm"),
                    )
                )

    dpi = EXPORT_DPI["300 dpi"]
    scale = 1.0
    if raster:
        dpi_label = st.selectbox(
            "输出精度",
            options=list(EXPORT_DPI),
            index=0,
            key=_key("export_dpi"),
        )
        dpi = EXPORT_DPI[dpi_label]
        scale = dpi / EXPORT_BASE_DPI

    return preset, width_mm, height_mm, dpi, scale


@st.cache_data(max_entries=24, show_spinner=False)
def render_static_image(
    fig_json: str,
    fmt: str,
    width: int,
    height: int,
    scale: float,
    transparent: bool,
    dpi: int | None = None,
) -> bytes:
    """静态图渲染。透明背景使用 paper_bgcolor="rgba(0,0,0,0)" 并写入真实 DPI。"""
    return render_static_bytes(
        fig_json,
        fmt,
        width,
        height,
        scale,
        transparent,
        dpi,
    )


@st.cache_data(max_entries=8, show_spinner=False)
def render_html_document(fig_json: str, offline: bool) -> bytes:
    return render_html_bytes(pio.from_json(fig_json), offline=offline)


@st.cache_data(max_entries=8, show_spinner=False)
def _cached_sample_zip(keys: tuple[str, ...]) -> bytes:
    return sample_zip_bytes(keys)


def figure_style_is_pending() -> bool:
    last_signature = st.session_state.get("last_style_signature")
    return bool(
        st.session_state.get("last_plotly") is not None
        and last_signature is not None
        and last_signature != plot_style_signature(st.session_state)
    )


def render_toolbar_status(slot=None) -> None:
    """单行状态条：状态、样式来源、数据规模、更新时间与未应用修改。"""
    target = slot if slot is not None else st
    kind = st.session_state.get("status_kind", "info")
    status_label = {
        "success": "已生成",
        "warning": "待处理",
        "error": "生成失败",
        "info": "就绪",
    }.get(kind, "就绪")
    status_class = {"success": "ok", "warning": "warn", "error": "err"}.get(
        kind, ""
    )
    source = style_source_label(st.session_state)
    data_text = describe_data(st.session_state.get("data"))
    generated_at = st.session_state.get("status_time") or "—"
    chips = [
        (
            f'<span class="status-chip {status_class}">'
            '<span class="dot"></span>'
            f"<span>状态</span><b>{status_label}</b>"
            "</span>"
        ),
        (
            '<span class="status-chip">'
            f"<span>样式来源</span><b>{html.escape(source)}</b>"
            "</span>"
        ),
        (
            '<span class="status-chip">'
            f"<span>数据</span><b>{html.escape(data_text)}</b>"
            "</span>"
        ),
        (
            '<span class="status-chip">'
            f"<span>更新</span><b>{html.escape(str(generated_at))}</b>"
            "</span>"
        ),
    ]
    if figure_style_is_pending():
        chips.append(
            '<span class="style-dirty-chip" role="status">'
            '<span class="dot"></span>'
            "<b>外观尚未应用</b>"
            "<span>· 点击「生成图形」更新预览与导出</span>"
            "</span>"
        )
    target.markdown(
        f'<div class="plot-status-strip">{"".join(chips)}</div>',
        unsafe_allow_html=True,
    )


def render_action_notice() -> None:
    """显示一次性的操作反馈（恢复外观、重置参数、导出完成）。"""
    notice = st.session_state.pop("_action_notice", None)
    if notice:
        st.success(str(notice))


def mark_export_complete(file_name: str, fmt: str) -> None:
    st.session_state["_action_notice"] = (
        f"导出完成：{file_name}（{fmt}）已生成并开始下载。"
    )


def render_export_check(report) -> None:
    status_label = {"ok": "通过", "warn": "提醒", "info": "信息"}
    rows = "".join(
        (
            f'<div class="export-check-row {item.status}">'
            f'<span>{html.escape(item.label)}</span>'
            f"<b>{html.escape(item.value)}</b>"
            f'<em>{status_label.get(item.status, "信息")}</em>'
            "</div>"
        )
        for item in report.items
    )
    tone = "warn" if report.warnings else "ok"
    st.markdown(
        f"""
        <div class="export-check-card {tone}">
            <div class="export-check-head">
                <b>导出前检查</b>
                <span>{html.escape(report.summary)}</span>
            </div>
            <div class="export-check-rows">{rows}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def export_stem(plot_name: str) -> str:
    return normalized_export_stem(st.session_state, plot_name)


def _reset_figure_appearance_state(mode: str) -> None:
    """在 widget 回调中重置外观，避免修改已实例化控件对应的 session_state。"""
    reset_figure_style(st.session_state)
    if mode == "site":
        st.session_state["theme"] = "Paper"
        st.session_state["sci_palette"] = "Auto"
        st.session_state["sci_palette_applied"] = "Auto"
    label = {
        "clear": "已清除通用外观覆盖",
        "site": "已恢复网站默认外观",
    }.get(mode, "外观已恢复")
    st.session_state["_action_notice"] = f"{label}，正在重新生成预览。"
    clear_cached_outputs()

def render_figure_style_controls(meta) -> bool:
    """统一外观控件；返回是否需要按新设置重新生成。"""
    source = style_source_label(st.session_state)
    st.caption(f"样式来源：**{source}**。通用设置优先于模块默认值，不修改数据与统计结果。")

    st.text_input(
        "图形标题",
        key="figure_title",
        placeholder="留空则保留模块标题",
    )
    st.checkbox(
        "用上面的标题覆盖模块标题",
        key="fs_title_override",
        help="关闭时，图形标题仍由各模块自己的标题设置控制；标题始终可作为导出文件名的后备值。",
    )

    st.selectbox(
        "字体",
        options=list(FONT_FAMILIES),
        key="fs_font_family",
    )
    st.slider(
        "全局字号比例",
        min_value=0.6,
        max_value=1.6,
        step=0.05,
        key="fs_font_scale",
        help="按模块原有字号层级等比缩放，避免破坏热图、网络图等模块的文字层级。",
    )

    size_left, size_right = st.columns(2)
    with size_left:
        st.number_input(
            "标题字号（0=跟随）",
            min_value=0,
            max_value=48,
            step=1,
            key="fs_title_size",
        )
        st.number_input(
            "刻度字号（0=跟随）",
            min_value=0,
            max_value=36,
            step=1,
            key="fs_tick_size",
        )
    with size_right:
        st.number_input(
            "轴标题字号（0=跟随）",
            min_value=0,
            max_value=36,
            step=1,
            key="fs_axis_title_size",
        )
        st.number_input(
            "图例字号（0=跟随）",
            min_value=0,
            max_value=36,
            step=1,
            key="fs_legend_size",
        )

    layout_left, layout_right = st.columns(2)
    with layout_left:
        st.selectbox(
            "图例位置",
            options=LEGEND_POSITIONS,
            key="fs_legend_position",
        )
    with layout_right:
        st.selectbox(
            "网格线",
            options=GRID_MODES,
            key="fs_grid_mode",
        )

    apply_clicked = st.button(
        "应用外观并重新生成",
        type="primary",
        width="stretch",
        key=f"style_apply_{meta.name}",
    )
    st.caption("修改外观后先应用，再切换至「导出与文件」，确保预览与导出使用同一份图形。")

    reset_left, reset_right = st.columns(2)
    with reset_left:
        st.button(
            "清除通用覆盖",
            width="stretch",
            key=f"style_clear_{meta.name}",
            on_click=_reset_figure_appearance_state,
            args=("clear",),
        )
    with reset_right:
        st.button(
            "恢复网站默认",
            width="stretch",
            key=f"style_site_{meta.name}",
            on_click=_reset_figure_appearance_state,
            args=("site",),
        )

    return apply_clicked


def _render_export_controls(meta, scope: str) -> None:
    plotly_fig = st.session_state.get("last_plotly")
    fig = st.session_state.get("last_fig")
    stem = export_stem(meta.name)
    font_family, min_font_px = (
        figure_font_info(plotly_fig)
        if plotly_fig is not None
        else ("", None)
    )
    min_font_pt = min_font_px * 0.75 if min_font_px else None

    def _key(piece: str) -> str:
        return f"{piece}_{scope}_{meta.name}"

    st.text_input(
        "导出文件名（不含扩展名）",
        key="fs_export_name",
        placeholder=st.session_state.get("figure_title") or meta.name,
    )
    if figure_style_is_pending():
        st.warning("外观设置尚未应用；当前预览与导出仍使用上一次生成结果。")

    if isinstance(fig, plt.Figure):
        fmt = st.radio(
            "导出格式",
            options=["PNG", "SVG", "PDF"],
            horizontal=True,
            key=_key("export_fmt"),
        )
        preset = st.selectbox(
            "画布预设",
            options=[name for name in EXPORT_PRESETS if name != "当前画布"],
            index=0,
            key=_key("export_preset"),
        )
        width_mm = EXPORT_PRESETS[preset]
        if preset == "自定义":
            width_mm = float(
                st.number_input(
                    "宽度 (mm)",
                    min_value=40.0,
                    max_value=400.0,
                    value=85.0,
                    step=1.0,
                    key=_key("export_w_mm"),
                )
            )
        # 矢量格式的物理尺寸由画布英寸数决定，dpi 只影响内嵌位图，不提供选项
        dpi = EXPORT_DPI["300 dpi"]
        if fmt == "PNG":
            dpi_label = st.selectbox(
                "输出精度",
                options=list(EXPORT_DPI),
                index=0,
                key=_key("export_dpi"),
            )
            dpi = EXPORT_DPI[dpi_label]

        try:
            payload = fig_to_bytes(fig, fmt.lower(), width_mm=width_mm, dpi=dpi)
            mime = {"PNG": "image/png", "SVG": "image/svg+xml", "PDF": "application/pdf"}[fmt]
            caption = (
                f"{width_mm:.0f} mm 宽 · {dpi} dpi"
                if fmt == "PNG"
                else f"{width_mm:.0f} mm 宽 · 矢量输出，可无损放大"
            )
            st.caption(caption)
            st.download_button(
                f"下载 {fmt}",
                data=payload,
                file_name=f"{stem}.{fmt.lower()}",
                mime=mime,
                width="stretch",
                key=_key(f"dl_matplotlib_{fmt}"),
                on_click=mark_export_complete,
                args=(f"{stem}.{fmt.lower()}", fmt),
            )
        except Exception as exc:
            st.warning(f"{fmt} 导出失败：{exc}")

    elif plotly_fig is not None:
        static_ready = kaleido_available()
        formats = (["PNG", "SVG", "PDF"] if static_ready else []) + ["HTML", "JSON"]

        fmt = st.radio(
            "导出格式",
            options=formats,
            horizontal=True,
            key=_key("export_fmt"),
        )

        payload = None
        mime = "text/plain"
        extension = fmt.lower()

        if fmt in {"PNG", "SVG", "PDF"}:
            template_name, width_mm, height_mm, dpi, scale = _journal_size_controls(
                _key, plotly_fig, raster=(fmt == "PNG")
            )
            css_w, css_h = _css_size(width_mm, height_mm, plotly_fig)
            height_mm_eff = css_h / EXPORT_BASE_DPI * MM_PER_INCH

            transparent = False
            if fmt == "PNG":
                transparent = st.checkbox(
                    "透明背景",
                    value=False,
                    key=_key("export_transparent"),
                )
                out_w = int(round(css_w * scale))
                out_h = int(round(css_h * scale))
                st.caption(
                    f"{width_mm:.1f} × {height_mm_eff:.1f} mm · "
                    f"输出 {out_w} × {out_h} px @ {dpi} dpi"
                )
            else:
                st.caption(
                    f"{width_mm:.1f} × {height_mm_eff:.1f} mm · 矢量输出，可无损放大"
                )

            render_export_check(
                build_export_check(
                    fmt=fmt,
                    file_name=stem,
                    width_mm=width_mm,
                    height_mm=height_mm_eff,
                    dpi=dpi,
                    transparent=transparent,
                    template_name=template_name,
                    font_family=font_family,
                    min_font_pt=min_font_pt,
                    static_ready=static_ready,
                )
            )

            # 静态图渲染很重（Kaleido 每次都要启动渲染进程），只在用户
            # 明确点击时执行，避免进入绘图页就把整个工具栏卡住。
            export_sig = (
                st.session_state.get("figure_revision"),
                fmt,
                round(css_w, 3),
                round(css_h, 3),
                round(scale, 4),
                bool(transparent),
                dpi,
                stem,
            )
            payload_key = _key("static_payload")
            sig_key = _key("static_payload_sig")
            if st.session_state.get(sig_key) != export_sig:
                st.session_state.pop(payload_key, None)

            if st.button(
                f"生成 {fmt} 文件",
                width="stretch",
                key=_key("static_build"),
                disabled=not static_ready,
            ):
                with st.spinner(f"正在渲染 {fmt}，通常需要 1–3 秒…"):
                    try:
                        st.session_state[payload_key] = render_static_image(
                            pio.to_json(plotly_fig),
                            fmt.lower(),
                            css_w,
                            css_h,
                            round(scale, 4),
                            transparent,
                            dpi,
                        )
                        st.session_state[sig_key] = export_sig
                    except Exception as exc:
                        st.session_state.pop(payload_key, None)
                        st.warning(
                            diagnose_static_export_error(
                                exc, static_ready=static_ready
                            )
                        )

            payload = (
                st.session_state.get(payload_key)
                if st.session_state.get(sig_key) == export_sig
                else None
            )
            if payload is None:
                st.caption("点击上方按钮生成文件；生成后这里会出现下载按钮。")
            else:
                mime = {
                    "PNG": "image/png",
                    "SVG": "image/svg+xml",
                    "PDF": "application/pdf",
                }[fmt]
        elif fmt == "HTML":
            html_mode = st.radio(
                "HTML 资源",
                options=["CDN（文件较小）", "完全离线（内联 Plotly JS）"],
                horizontal=True,
                key=_key("export_html_mode"),
            )
            html_offline = html_mode.startswith("完全离线")
            render_export_check(
                build_export_check(
                    fmt="HTML",
                    file_name=stem,
                    width_mm=None,
                    height_mm=None,
                    font_family=font_family,
                    min_font_pt=min_font_pt,
                    static_ready=static_ready,
                    html_offline=html_offline,
                )
            )
            payload = render_html_document(pio.to_json(plotly_fig), html_offline)
            mime = "text/html"
        else:
            payload = pio.to_json(plotly_fig, pretty=True)
            mime = "application/json"

        if payload is not None:
            st.download_button(
                f"下载 {fmt}",
                data=payload,
                file_name=f"{stem}.{extension}",
                mime=mime,
                width="stretch",
                key=_key(f"dl_plotly_{fmt}"),
                on_click=mark_export_complete,
                args=(f"{stem}.{extension}", fmt),
            )

        if not static_ready:
            st.caption("安装 kaleido 后可导出 PNG / SVG / PDF（当前仅 HTML / JSON）。")
    else:
        st.caption("生成图形后即可导出。")

    st.markdown("---")
    st.markdown("**配套示例数据**")
    try:
        st.download_button(
            "下载示例数据（.zip）",
            data=_cached_sample_zip(tuple(meta.sample_keys)),
            file_name=f"{meta.preview}_sample_data.zip",
            mime="application/zip",
            width="stretch",
            key=f"dl_sample_{meta.name}",
        )
        st.caption("；".join(meta.sample_keys))
    except Exception as exc:
        st.caption(f"示例数据不可用：{exc}")


def render_export_popover(meta, scope: str = "toolbar") -> bool:
    """统一外观与导出面板。返回是否需要重新生成图形。"""
    with st.expander("外观设置", expanded=True):
        apply_clicked = render_figure_style_controls(meta)
    with st.expander("导出与文件", expanded=False):
        _render_export_controls(meta, scope)
    with st.expander("项目包（保存与恢复）", expanded=False):
        render_project_save_section(meta)
        render_project_restore_section()
    return apply_clicked


def reset_plot_params(plot_name: str = "") -> None:
    """清空当前模块前缀下的全部参数（不止颜色），保留路由与主题状态。"""
    module_prefixes = (
        "arc_", "bee_", "ch_", "chord_", "go_", "heb_", "mt_", "mantel_",
        "ndl_", "pir_", "pirate_", "rc_", "rain_", "sk_", "sankey_", "sbd_",
        "splitviolin_", "sv_", "bubble_", "gmp_", "circle_", "cbar_", "genvar_",
        "volcano_", "pca_", "heatmap_", "upset_", "km_", "manhattan_",
    )
    keep = {
        "page", "plot_type", "theme", "figure_title", "last_fig", "last_plotly",
        "data", "status", "status_kind", "status_time", "help_text", "last_plot_key",
        "gallery_query", "gallery_category", "gallery_shape", "home_category_anchor",
    }
    for key in list(st.session_state.keys()):
        if key in keep or key.startswith("_"):
            continue
        if key.startswith(module_prefixes) or key.startswith("export_"):
            del st.session_state[key]
    st.session_state["_action_notice"] = (
        f"{plot_name or '当前模块'}的参数已重置，正在使用默认值重新生成。"
    )
    clear_cached_outputs()
    st.rerun()


_BOOT_LOADER_HTML = """
<style>
#bioplot-boot {
    position: fixed;
    inset: 0;
    z-index: 2147483000;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
    background: ${bg};
    background: color-mix(in srgb, ${bg} 88%, transparent);
    backdrop-filter: blur(3px);
    -webkit-backdrop-filter: blur(3px);
    opacity: 0;
    visibility: hidden;
    animation: bioplot-boot-in 0.18s ease 0.25s forwards;
}
#bioplot-boot .bioplot-dot-ring {
    width: 58px;
    height: 58px;
    border-radius: 50%;
    border: 6px dotted ${primary};
    animation: bioplot-boot-spin 1s linear infinite;
}
#bioplot-boot .bioplot-boot-text {
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.12em;
    color: ${muted};
}
@keyframes bioplot-boot-in {
    to { opacity: 1; visibility: visible; }
}
@keyframes bioplot-boot-spin {
    to { transform: rotate(360deg); }
}
</style>
<div id="bioplot-boot" role="status" aria-live="polite" aria-label="加载中">
    <div class="bioplot-dot-ring"></div>
    <div class="bioplot-boot-text">加载中…</div>
</div>
"""


def mount_boot_loader():
    """首个 delta：全屏虚点加载层；脚本结束时由调用方清空。"""
    theme = THEMES.get(st.session_state.get("theme", "Paper"), THEMES["Paper"])
    markup = Template(_BOOT_LOADER_HTML).substitute(
        bg=theme.get("bg", "#f7f8f6"),
        primary=theme.get("primary", "#14655a"),
        text=theme.get("text", "#16211d"),
        muted=theme.get("muted", "#5d6b65"),
    )
    slot = st.empty()
    slot.markdown(markup, unsafe_allow_html=True)
    return slot


def render_toolbar(plot_name: str, meta) -> tuple[bool, object]:
    with st.container(key="plot-toolbar"):
        return _toolbar_row(plot_name, meta)


def _toolbar_row(plot_name: str, meta) -> tuple[bool, object]:
    generate_col, settings_col, data_col, help_col = st.columns(
        [1.25, 1.15, 0.9, 0.9]
    )

    with generate_col:
        generate_clicked = st.button(
            "生成图形",
            type="primary",
            width="stretch",
            key=f"generate_{plot_name}",
        )

    style_applied = False
    with settings_col:
        with st.popover("设置与导出", width="stretch"):
            style_applied = render_export_popover(meta, scope="toolbar")
            st.markdown("---")
            if st.button(
                "重置当前模块参数",
                width="stretch",
                key=f"reset_{plot_name}",
            ):
                reset_plot_params(plot_name)

    with data_col:
        with st.popover("数据", width="stretch"):
            render_data_preview()

    with help_col:
        with st.popover("帮助", width="stretch"):
            render_help(meta)

    pending_slot = st.empty()
    render_toolbar_status(pending_slot)
    render_action_notice()
    return generate_clicked or style_applied, pending_slot


def describe_data(data) -> str:
    if isinstance(data, pd.DataFrame):
        return f"{len(data):,} 行 × {data.shape[1]} 列"
    if isinstance(data, pd.Series):
        return f"{len(data):,} 行"
    if isinstance(data, dict):
        parts = []
        for key, value in data.items():
            if isinstance(value, pd.DataFrame):
                parts.append(f"{key} {len(value):,} 行")
            elif isinstance(value, pd.Series):
                parts.append(f"{key} {len(value):,} 行")
            if len(parts) >= 3:
                break
        return " / ".join(parts) if parts else "结构化数据"
    if data is not None:
        return str(type(data).__name__)
    return "—"


def render_status() -> None:
    message = st.session_state.get("status")
    if not message:
        return
    kind = st.session_state.get("status_kind", "info")
    renderer = {
        "success": st.success,
        "warning": st.warning,
        "error": st.error,
    }.get(kind, st.info)
    renderer(str(message))


def resolve_module_output(result, shared):
    fig = shared.get("last_fig")
    plotly_fig = shared.get("last_plotly")
    data = shared.get("data")
    status = shared.get("status")
    help_text = shared.get("help_text")

    if result is None:
        return fig, plotly_fig, data, status, help_text

    if isinstance(result, tuple):
        if len(result) >= 1 and fig is None and plotly_fig is None:
            first = result[0]
            if isinstance(first, plt.Figure):
                fig = first
            elif hasattr(first, "to_plotly_json"):
                plotly_fig = first

        if len(result) >= 2 and data is None:
            data = result[1]

        if len(result) >= 3 and status is None:
            status = result[2]

        if len(result) >= 4 and help_text is None:
            help_text = result[3]

    else:
        if fig is None and plotly_fig is None:
            if isinstance(result, plt.Figure):
                fig = result
            elif hasattr(result, "to_plotly_json"):
                plotly_fig = result

    return fig, plotly_fig, data, status, help_text


def run_module_generation(module_name: str, module_obj) -> None:
    shared = st.session_state
    clear_cached_outputs()
    shared["last_plot_key"] = module_name
    shared["figure_revision"] = int(shared.get("figure_revision", 0)) + 1

    try:
        if hasattr(module_obj, "build") and callable(module_obj.build):
            result = module_obj.build(shared)
        elif hasattr(module_obj, "render") and callable(module_obj.render):
            result = module_obj.render(shared)
        else:
            shared["status"] = f"{module_name} 模块没有可调用的 build()/render() 方法。"
            shared["status_kind"] = "error"
            shared["status_time"] = datetime.now().strftime("%H:%M:%S")
            return
    except Exception as exc:
        shared["status"] = f"{module_name} 生成失败：{exc}"
        shared["status_kind"] = "error"
        shared["status_time"] = datetime.now().strftime("%H:%M:%S")
        return

    fig, plotly_fig, data, status, help_text = resolve_module_output(result, shared)

    if plotly_fig is not None:
        apply_figure_style(plotly_fig, shared)
        prevent_label_clipping(plotly_fig)
        shared["last_style_signature"] = plot_style_signature(shared)

    shared["last_fig"] = fig
    shared["last_plotly"] = plotly_fig
    shared["data"] = data
    shared["status"] = str(status) if status else f"{module_name} 已生成。"
    shared["help_text"] = str(help_text) if help_text else f"{module_name} 的帮助信息会显示在这里。"
    shared["status_kind"] = "success" if (fig is not None or plotly_fig is not None) else "warning"
    shared["status_time"] = datetime.now().strftime("%H:%M:%S")


def render_plot_tabs(meta) -> None:
    """图形 / 数据预览 / 使用说明 三个 Tab（架构 §6.5）。"""
    tab_fig, tab_data, tab_help = st.tabs(["图形", "数据预览", "使用说明"])
    with tab_fig:
        render_plot_panel()
    with tab_data:
        render_data_preview()
    with tab_help:
        render_help(meta)


def render_plot_panel() -> None:
    fig = st.session_state.get("last_fig")
    plotly_fig = st.session_state.get("last_plotly")

    if isinstance(fig, plt.Figure):
        try:
            st.pyplot(fig, width="stretch")
        except Exception as exc:
            st.error(f"图形渲染失败：{exc}")
    elif plotly_fig is not None:
        try:
            # 按图形自身设计尺寸显示：width/height 同时取 content，
            # 避免只横向拉满容器而高度不变，导致圆、弧和节点被压扁。
            if plotly_fig.layout.width is None:
                plotly_fig.update_layout(width=960)
            if plotly_fig.layout.height is None:
                plotly_fig.update_layout(height=560)
            with st.container(key="plot-canvas"):
                st.plotly_chart(
                    plotly_fig,
                    width="content",
                    height="content",
                    theme=None,
                )
        except Exception as exc:
            st.error(f"图形渲染失败：{exc}")
    else:
        st.markdown(
            """
            <div class="empty-state">
                <div class="icon">◎</div>
                <h3>还没有可显示的图形</h3>
                <p>点击上方「生成图形」，或先在左侧确认示例数据与参数。</p>
                <div class="hint">首次进入模块时，会自动使用内置示例数据生成一次预览。</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_footer() -> None:
    st.markdown(
        f"""
        <div class="app-foot">
            <span>{BRAND} · 生物数据可视化工作台</span>
            <span>{len(MODULES)} 图形 · {len(CATEGORY_ORDER)} 分类 · {len(SAMPLE_PATHS)} 份示例数据</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_plot() -> None:
    plot_name = st.session_state.plot_type
    if not plot_name or plot_name not in MODULES:
        st.warning("未找到图形模块，已返回图形库。")
        go_home()
        return

    module_obj = MODULES[plot_name]
    meta = meta_for(plot_name)

    render_plot_sidebar(module_obj, meta)
    render_plot_header(meta)

    has_output = (
        st.session_state.get("last_fig") is not None
        or st.session_state.get("last_plotly") is not None
    )
    auto_need_generate = (
        st.session_state.get("last_plot_key") != plot_name
        or (not has_output and st.session_state.get("status_kind") == "info")
    )

    if auto_need_generate:
        run_module_generation(plot_name, module_obj)

    generate_clicked, pending_slot = render_toolbar(plot_name, meta)

    if generate_clicked:
        run_module_generation(plot_name, module_obj)

    render_toolbar_status(pending_slot)
    render_status()
    render_plot_tabs(meta)
    render_footer()


# -------- 主入口 --------
boot_slot = None if st.session_state.get("_boot_done") else mount_boot_loader()
try:
    init_state()
    sync_theme_widget_state()
    install_project_uploader()
    sync_route_from_query()
    sync_doc_state()
    inject_css()
    render_topbar()

    if st.session_state.page == "home":
        render_home_sidebar()
        show_home()
    else:
        show_plot()
finally:
    if boot_slot is not None:
        boot_slot.empty()
    st.session_state["_boot_done"] = True
