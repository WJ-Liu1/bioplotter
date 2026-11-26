"""首页内嵌文档：左侧窄卡片列 + 右侧说明 / 数据 / 代码 / 环境。"""

from __future__ import annotations

import html
import platform
import re
from importlib import metadata
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st

from app.core.catalog import (
    CATEGORY_ORDER,
    DATA_SHAPE_ORDER,
    PLOTS,
    data_shape_for,
    difficulty_for,
    figure_number,
    meta_for,
    preview_svg,
    search_plots,
)
from app.core.docs_content import (
    PYTHON_PACKAGES,
    install_python_snippet,
    recipe_for,
)
from app.core.py_recipes import module_source_for, py_code_for
from app.core.sample_utils import SAMPLE_PATHS, get_sample_path, sample_zip_bytes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = PROJECT_ROOT / "env"

DOCS_URL = "?page=home&doc="
PLOT_URL = "?page=plot&plot="


def _q(name: str) -> str:
    return quote(name, safe="")


@st.cache_data(show_spinner=False)
def _all_sample_zip() -> bytes:
    return sample_zip_bytes(tuple(SAMPLE_PATHS))


@st.cache_data(show_spinner=False)
def _zip_for(keys: tuple[str, ...]) -> bytes:
    return sample_zip_bytes(keys)


def _qp_value(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _selected_doc(names: list[str]) -> str:
    requested = _qp_value(st.query_params.get("doc"))
    if requested in PLOTS:
        return requested
    return names[0] if names else next(iter(PLOTS))


def _slug(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "-", name).strip("-").lower()


def select_doc(name: str) -> None:
    """卡片点击回调：只更新会话状态，不触发浏览器跳转。"""
    st.session_state["doc_selected"] = name
    st.session_state["_doc_param_seen"] = name
    st.query_params["doc"] = name


def close_doc() -> None:
    st.session_state["doc_selected"] = None
    st.session_state["_doc_param_seen"] = None
    if "doc" in st.query_params:
        del st.query_params["doc"]


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".csv": "text/csv",
        ".txt": "text/plain",
        ".tsv": "text/tab-separated-values",
        ".nwk": "text/plain",
        ".nex": "text/plain",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")


def _file_size(path: Path) -> str:
    size = path.stat().st_size
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{size / 1024:.1f} KB"


def _cards(names: list[str], selected: str) -> None:
    """中部图表卡片：点击卡片即在右侧显示对应图形的完整说明文档。"""
    if not names:
        st.markdown(
            """
            <div class="empty-state">
                <div class="icon">?</div>
                <h3>没有匹配的图形</h3>
                <p>换个关键词，或把分类切回「全部」。</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    for start in range(0, len(names), 2):
        columns = st.columns(2, gap="small")
        for column, name in zip(columns, names[start:start + 2]):
            with column:
                with st.container(key=f"doccard-{_slug(name)}"):
                    st.markdown(_card_html(name, selected), unsafe_allow_html=True)
                    st.button(
                        f"查看 {name} 的说明",
                        key=f"docpick_{_slug(name)}",
                        on_click=select_doc,
                        args=(name,),
                        width="stretch",
                    )


def _card_html(name: str, selected: str) -> str:
    meta = meta_for(name)
    active = " selected" if name == selected else ""
    return (
        f'<div class="docs-card{active}">'
        f'<div class="docs-card-preview">{preview_svg(name).strip()}'
        f'<div class="gallery-hover"><p>{html.escape(meta.summary)}</p></div></div>'
        '<div class="docs-card-body">'
        f'<div class="docs-card-top"><span class="pill">{html.escape(meta.category)}</span></div>'
        f"<h3>{html.escape(name)}</h3>"
        "</div></div>"
    )


def _preview_frame(path: Path) -> pd.DataFrame | None:
    if path.suffix.lower() in {".nwk", ".nex", ".tree"}:
        return None
    try:
        return pd.read_csv(
            path,
            sep=None,
            engine="python",
            nrows=8,
            encoding="utf-8",
            encoding_errors="replace",
        )
    except Exception:
        return None


def _render_data_tab(meta) -> None:
    keys = tuple(meta.sample_keys)
    total = sum(get_sample_path(key).stat().st_size for key in keys)
    st.caption(
        f"示例数据已内置在项目中 · {len(keys)} 个文件 · 合计 {total / 1024:.1f} KB。"
        "下方可直接预览与下载，无需再打开文件夹。"
    )
    st.download_button(
        f"打包下载全部示例数据（{len(keys)} 个文件 · ZIP）",
        data=_zip_for(keys),
        file_name=f"{meta.preview}_sample_data.zip",
        mime="application/zip",
        key=f"docs_zip_{meta.name}",
        width="stretch",
    )
    for key in keys:
        path = get_sample_path(key)
        st.markdown(f"**`{path.name}`** · {_file_size(path)}")
        frame = _preview_frame(path)
        if frame is not None:
            st.dataframe(frame, width="stretch", hide_index=True, height=min(300, 40 + 32 * len(frame)))
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            st.code(text[:600] + ("\n…" if len(text) > 600 else ""), language="text")
        st.download_button(
            f"下载 {path.name}",
            data=path.read_bytes(),
            file_name=path.name,
            mime=_mime_for(path),
            key=f"docs_file_{meta.name}_{key}",
            width="stretch",
        )


def _render_code_tab(meta) -> None:
    code = py_code_for(meta.name)
    if not code:
        st.info("该图形暂未提供 Python 示例。")
        return
    st.caption(
        "可运行示例：读取的就是上方可下载的示例文件，点击代码块右上角的复制按钮即可一键 Copy。"
        "标注「最小示例」的图形，完整参数实现见下方模块源码。"
    )
    st.markdown("**Python 示例**")
    st.code(code, language="python")
    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button(
            "下载 Python 脚本",
            data=code.encode("utf-8"),
            file_name=f"{meta.preview}_example.py",
            mime="text/plain",
            key=f"docs_py_{meta.name}",
            width="stretch",
        )
    with col_b:
        st.download_button(
            "下载示例数据 ZIP",
            data=_zip_for(tuple(meta.sample_keys)),
            file_name=f"{meta.preview}_sample_data.zip",
            mime="application/zip",
            key=f"docs_py_zip_{meta.name}",
            width="stretch",
        )
    source = module_source_for(meta.name)
    if source is not None:
        filename, text = source
        st.markdown(
            f"**完整模块源码**：`app/modules/{filename}`"
            f"（{len(text.splitlines())} 行，与站点运行的代码一致）"
        )
        with st.expander(f"查看 / 复制完整源码 app/modules/{filename}", expanded=True):
            st.code(text, language="python")
        st.download_button(
            f"下载 {filename}",
            data=text.encode("utf-8"),
            file_name=filename,
            mime="text/x-python",
            key=f"docs_py_src_{meta.name}",
            width="stretch",
        )


@st.cache_data(show_spinner=False)
def _installed_versions() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for package in PYTHON_PACKAGES:
        try:
            rows.append((package, metadata.version(package)))
        except metadata.PackageNotFoundError:
            rows.append((package, "未安装"))
    return rows


def _render_env_tab() -> None:
    rows = _installed_versions()
    installed = sum(1 for _, version in rows if version != "未安装")
    st.caption(
        "本站由 Python / Plotly 实现，运行只需要 Python 环境。"
        f"当前解释器：Python {platform.python_version()}；"
        f"依赖状态：{installed}/{len(rows)} 个包已安装。"
    )
    st.markdown("**Python 环境（网站运行所需）**")
    st.dataframe(
        pd.DataFrame(rows, columns=["包", "当前版本"]),
        width="stretch",
        hide_index=True,
        height=40 + 32 * len(rows),
    )
    st.markdown("**一键复制的安装命令**")
    st.code(install_python_snippet(), language="bash")
    st.markdown("**完整依赖与部署文件**")
    env_files = (
        ("requirements-lock.txt（锁定版本）", ENV_DIR / "requirements-lock.txt", "docs_env_lock"),
        ("requirements.txt（宽松版本）", PROJECT_ROOT / "requirements.txt", "docs_env_requirements"),
        ("env/README.md（部署说明）", ENV_DIR / "README.md", "docs_env_readme"),
    )
    for label, path, key in env_files:
        if not path.exists():
            continue
        st.download_button(
            f"下载 {label}",
            data=path.read_bytes(),
            file_name=path.name,
            mime="text/plain",
            key=key,
            width="stretch",
        )

def _render_detail(name: str) -> None:
    meta = meta_for(name)
    recipe = recipe_for(name)
    shape = data_shape_for(name)
    level = difficulty_for(name)
    chips = ""
    if shape:
        chips += f'<span class="tag-chip shape">{html.escape(shape)}</span>'
    if level:
        chips += f'<span class="tag-chip level-{html.escape(level)}">{html.escape(level)}</span>'
    st.markdown(
        f"""
        <div class="docs-detail-head">
            <div class="docs-detail-top">
                <span class="docs-fig">Fig. {figure_number(name):02d}</span>
                <span class="pill">{html.escape(meta.category)}</span>
                <div class="tag-row">{chips}</div>
            </div>
            <h2>{html.escape(meta.name)}</h2>
            <p>{html.escape(meta.summary)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.link_button("去绘制这张图 →", f"{PLOT_URL}{_q(name)}", width="stretch")
    st.caption("下方为「说明 / 数据 / Python 代码 / 环境」四个页签；Python 示例与完整模块源码均以代码块展示，支持一键 Copy。")

    tab_doc, tab_data, tab_code, tab_env = st.tabs(["说明", "数据", "Python 代码", "环境"])
    with tab_doc:
        if recipe and recipe.notes:
            st.markdown("**图形解读**")
            st.write(recipe.notes)
        st.markdown("**输入格式**")
        st.code(meta.inputs, language=None)
        if recipe and recipe.highlights:
            st.markdown("**图形要点**")
            st.markdown("\n".join(f"- {item}" for item in recipe.highlights))
        if recipe and recipe.params:
            st.markdown("**参数建议**")
            st.markdown("\n".join(f"- {item}" for item in recipe.params))
        if recipe and recipe.caveats:
            st.markdown("**注意事项**")
            st.markdown("\n".join(f"- {item}" for item in recipe.caveats))
    with tab_data:
        _render_data_tab(meta)
    with tab_code:
        _render_code_tab(meta)
    with tab_env:
        _render_env_tab()


def render_docs_cards(names: list[str], selected: str) -> None:
    """首页右栏展开时，左侧的窄卡片列（含结果行与整包数据下载）。"""
    st.markdown(
        f'<div class="docs-result-line">显示 {len(names)} / {len(PLOTS)} 个图形'
        f"<span>当前：{html.escape(selected)}</span></div>",
        unsafe_allow_html=True,
    )
    _cards(names, selected)
    st.download_button(
        "下载全部示例数据（ZIP）",
        data=_all_sample_zip(),
        file_name="bioplotter_sample_data.zip",
        mime="application/zip",
        key="docs_zip_all",
        width="stretch",
    )


def render_docs_detail(name: str) -> None:
    """右侧文档详情：说明 / 数据 / Python 代码 / 环境。"""
    with st.container(key="docs-detail-panel"):
        _render_detail(name)
