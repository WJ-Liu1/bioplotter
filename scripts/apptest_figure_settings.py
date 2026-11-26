from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import plotly.graph_objects as go
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.core.catalog as catalog  # noqa: E402
from app.core.catalog import meta_for  # noqa: E402
from app.core.figure_style import (  # noqa: E402
    FIGURE_STYLE_DEFAULTS,
    apply_figure_style,
    normalized_export_stem,
    restore_figure_style,
)
from app.core.layout_guard import prevent_label_clipping  # noqa: E402
from app.core.project_io import build_project_bundle, restore_project_bundle  # noqa: E402


APP_FILE = str(PROJECT_ROOT / "app.py")


def style_state(**overrides):
    state = dict(FIGURE_STYLE_DEFAULTS)
    state.update(overrides)
    return state


def open_plot(name: str) -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state["page"] = "home"
    at.run()
    at.button(key=f"nav_{name}").click().run()
    return at


def session_value(at: AppTest, key: str, default=None):
    try:
        return at.session_state[key]
    except KeyError:
        return default


def visible_html(at: AppTest) -> str:
    return "\n".join(str(block.value) for block in at.markdown)


def figure_data(fig) -> list[tuple[list, list]]:
    return [
        (list(trace.x) if trace.x is not None else [], list(trace.y) if trace.y is not None else [])
        for trace in fig.data
    ]


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[4, 5, 6], name="A"))
    fig.update_layout(
        title=dict(text="Old", font=dict(size=20)),
        font=dict(size=10),
        legend=dict(font=dict(size=10)),
    )
    fig.update_xaxes(title=dict(font=dict(size=12)), tickfont=dict(size=10))
    fig.update_yaxes(title=dict(font=dict(size=12)), tickfont=dict(size=10))
    before = figure_data(fig)
    state = style_state(fs_font_family="Arial", fs_font_scale=1.2)
    apply_figure_style(fig, state)
    checks.append((
        "字体族应用到标题/坐标轴/图例",
        fig.layout.title.font.family == "Arial, Helvetica, sans-serif"
        and fig.layout.xaxis.title.font.family == "Arial, Helvetica, sans-serif"
        and fig.layout.yaxis.tickfont.family == "Arial, Helvetica, sans-serif"
        and fig.layout.legend.font.family == "Arial, Helvetica, sans-serif",
        str(fig.layout.font.family),
    ))
    checks.append((
        "全局字号按比例缩放",
        (fig.layout.title.font.size, fig.layout.xaxis.title.font.size, fig.layout.yaxis.tickfont.size)
        == (24, 14, 12),
        str((fig.layout.title.font.size, fig.layout.xaxis.title.font.size, fig.layout.yaxis.tickfont.size)),
    ))
    checks.append(("外观设置不修改数据", figure_data(fig) == before, f"traces={len(fig.data)}"))

    fig2 = go.Figure(go.Scatter(x=[1], y=[2], name="A"))
    fig2.update_layout(title="Old")
    fig2.update_xaxes(title=dict(text="X"))
    state = style_state(
        fs_title_size=18,
        fs_axis_title_size=11,
        fs_tick_size=9,
        fs_legend_size=8,
        fs_title_override=True,
        fs_legend_position="顶部",
        fs_grid_mode="隐藏",
        figure_title="统一标题",
    )
    state["figure_title"] = "统一标题"
    apply_figure_style(fig2, state)
    checks.append((
        "标题覆盖与分级字号",
        fig2.layout.title.text == "统一标题"
        and fig2.layout.title.font.size == 18
        and fig2.layout.xaxis.title.font.size == 11
        and fig2.layout.xaxis.tickfont.size == 9
        and fig2.layout.legend.font.size == 8,
        str(fig2.layout.title.text),
    ))
    checks.append((
        "图例位置与网格开关",
        fig2.layout.legend.orientation == "h"
        and fig2.layout.legend.y > 1
        and fig2.layout.xaxis.showgrid is False
        and fig2.layout.yaxis.showgrid is False,
        f"legend_y={fig2.layout.legend.y}",
    ))
    prevent_label_clipping(fig2)
    checks.append((
        "顶部图例预留边距",
        fig2.layout.margin.t >= 70,
        f"top={fig2.layout.margin.t}",
    ))

    checks.append((
        "导出文件名清理扩展名与非法字符",
        normalized_export_stem(
            {"fs_export_name": "Figure 1.png", "figure_title": "ignored"},
            "Volcano Plot",
        )
        == "Figure 1"
        and normalized_export_stem(
            {"fs_export_name": "A/B: C.pdf", "figure_title": ""},
            "Volcano Plot",
        )
        == "A_B_ C",
        "ok",
    ))

    restored = style_state()
    restore_figure_style(
        {
            "font_family": "Times New Roman",
            "font_scale": 9,
            "title_size": -5,
            "legend_position": "未知",
            "grid_mode": "显示",
        },
        restored,
    )
    checks.append((
        "项目外观字段校验与夹取",
        restored["fs_font_family"] == "Times New Roman"
        and restored["fs_font_scale"] == 1.6
        and restored["fs_title_size"] == 0
        and restored["fs_legend_position"] == "跟随模块"
        and restored["fs_grid_mode"] == "显示",
        str(restored),
    ))

    at = open_plot("Volcano Plot")
    baseline = figure_data(at.session_state["last_plotly"])
    at.selectbox(key="fs_font_family").set_value("Arial").run()
    at.selectbox(key="fs_legend_position").set_value("顶部").run()
    at.selectbox(key="fs_grid_mode").set_value("隐藏").run()
    at.checkbox(key="fs_title_override").set_value(True).run()
    at.text_input(key="figure_title").set_value("统一标题").run()
    at.button(key="style_apply_Volcano Plot").click().run()
    styled = at.session_state["last_plotly"]
    checks.append((
        "AppTest 应用统一外观并重新生成",
        not at.exception
        and styled.layout.font.family == "Arial, Helvetica, sans-serif"
        and styled.layout.title.text == "统一标题"
        and styled.layout.legend.orientation == "h"
        and styled.layout.xaxis.showgrid is False,
        f"exception={at.exception}",
    ))
    checks.append((
        "AppTest 重新生成后数据不变",
        figure_data(styled) == baseline,
        f"traces={len(styled.data)}",
    ))
    checks.append((
        "应用外观后工具栏提示消失",
        "外观尚未应用" not in visible_html(at),
        "ok",
    ))

    at.number_input(key="fs_tick_size").set_value(13).run()
    warnings = "\n".join(str(item.value) for item in at.warning)
    checks.append((
        "未应用外观在导出页提示",
        "外观设置尚未应用" in warnings,
        warnings or "no warning",
    ))
    checks.append((
        "未应用外观在工具栏提示",
        "style-dirty-chip" in visible_html(at)
        and "外观尚未应用" in visible_html(at),
        "ok",
    ))
    at.button(key="generate_Volcano Plot").click().run()
    checks.append((
        "重新生成后工具栏提示自动清除",
        "外观尚未应用" not in visible_html(at),
        "ok",
    ))

    at.text_input(key="fs_export_name").set_value("paper-figure-1.png").run()
    checks.append((
        "导出文件名写入会话",
        at.session_state["fs_export_name"] == "paper-figure-1.png",
        at.session_state["fs_export_name"],
    ))

    bundle, _, _ = build_project_bundle("Volcano Plot", meta_for("Volcano Plot"), at.session_state)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    stored = manifest.get("figure_style") or {}
    checks.append((
        "项目包保存统一外观与文件名",
        stored.get("font_family") == "Arial"
        and stored.get("legend_position") == "顶部"
        and stored.get("grid_mode") == "隐藏"
        and stored.get("export_name") == "paper-figure-1.png",
        str(stored),
    ))

    fresh = AppTest.from_file(APP_FILE, default_timeout=180)
    fresh.session_state["page"] = "home"
    fresh.run()
    restore_project_bundle(bundle, fresh.session_state, {"Volcano Plot"})
    fresh.query_params["page"] = "plot"
    fresh.query_params["plot"] = "Volcano Plot"
    fresh.run()
    checks.append((
        "项目包恢复统一外观与文件名",
        fresh.session_state["fs_font_family"] == "Arial"
        and fresh.session_state["fs_legend_position"] == "顶部"
        and fresh.session_state["fs_grid_mode"] == "隐藏"
        and fresh.session_state["fs_export_name"] == "paper-figure-1.png"
        and fresh.session_state["last_plotly"].layout.font.family == "Arial, Helvetica, sans-serif",
        f"exception={fresh.exception}",
    ))

    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state["page"] = "home"
    at.run()
    at.session_state["fs_font_family"] = "Arial"
    at.session_state["fs_font_scale"] = 1.15
    at.session_state["fs_legend_position"] = "底部"
    at.session_state["fs_grid_mode"] = "隐藏"
    at.session_state["fs_title_override"] = True
    at.session_state["figure_title"] = "统一标题"
    failures_detail: list[str] = []
    for module_name in catalog.PLOTS:
        at.query_params["page"] = "plot"
        at.query_params["plot"] = module_name
        at.session_state["last_plot_key"] = None
        at.session_state["last_fig"] = None
        at.session_state["last_plotly"] = None
        at.run()
        for _ in range(2):
            if session_value(at, "last_plotly") is not None or session_value(at, "last_fig") is not None:
                break
            at.run()
        fig = session_value(at, "last_plotly")
        ok = (
            not at.exception
            and str(session_value(at, "status_kind")) == "success"
            and fig is not None
            and fig.layout.title.text == "统一标题"
            and fig.layout.font.family == "Arial, Helvetica, sans-serif"
        )
        if not ok:
            failures_detail.append(f"{module_name}: {at.exception or session_value(at, 'status')}")
    checks.append((
        "24 模块应用非默认统一外观",
        not failures_detail,
        "; ".join(failures_detail) if failures_detail else f"{len(catalog.PLOTS)}/{len(catalog.PLOTS)}",
    ))

    failures = 0
    for label, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        failures += 0 if ok else 1
    print(f"figure-settings-apptest: {len(checks) - failures}/{len(checks)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
