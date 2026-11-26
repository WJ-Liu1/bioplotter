"""Toolbar refactor regression: four entries, merged status strip, feedback.

    .venv\\Scripts\\python.exe -X utf8 scripts/apptest_toolbar_refactor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP_FILE = str(Path(__file__).resolve().parents[1] / "app.py")


def new_app() -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=200)
    at.session_state["page"] = "home"
    at.run()
    return at


def open_plot(at: AppTest, name: str) -> AppTest:
    at.button(key=f"nav_{name}").click().run()
    for _ in range(3):
        if len(at.get("plotly_chart")) >= 1 or len(at.get("pyplot")) >= 1:
            break
        at.run()
    return at


def status_html(at: AppTest) -> str:
    for item in at.markdown:
        value = str(item.value)
        if value.startswith('<div class="plot-status-strip">'):
            return value
    return ""


def success_text(at: AppTest) -> str:
    return "\n".join(str(item.value) for item in at.success)


def control_keys(at: AppTest) -> set[str]:
    keys: set[str] = set()
    for element_type in (
        "checkbox",
        "radio",
        "slider",
        "selectbox",
        "number_input",
        "text_input",
    ):
        keys |= {item.key for item in at.get(element_type)}
    return keys


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    source = Path(APP_FILE).read_text(encoding="utf-8")

    at = open_plot(new_app(), "Volcano Plot")
    popovers = at.get("popover")
    popover_buttons = {button.key for button in popovers[0].get("button")} if popovers else set()

    checks.append((
        "工具栏：生成 + 3 个弹层",
        len(popovers) == 3 and any(
            button.key == "generate_Volcano Plot" for button in at.button
        ),
        f"popovers={len(popovers)}",
    ))
    checks.append((
        "设置弹层含外观/导出/重置",
        {
            "style_apply_Volcano Plot",
            "style_site_Volcano Plot",
            "reset_Volcano Plot",
        }
        <= popover_buttons,
        str(sorted(popover_buttons)),
    ))

    html = status_html(at)
    checks.append((
        "状态条合并为一行",
        all(token in html for token in ("状态", "样式来源", "数据", "更新"))
        and "引擎" not in html
        and "meta-strip" not in html,
        html[:180],
    ))
    checks.append((
        "旧 meta-strip 已移除",
        "def render_meta_strip" not in source and "meta-strip" not in source,
        "ok",
    ))
    checks.append((
        "状态条显示数据规模",
        "3,000 行" in html and "更新" in html,
        html[:180],
    ))

    at.number_input(key="fs_tick_size").set_value(13).run()
    html = status_html(at)
    checks.append((
        "未应用外观提示",
        'class="style-dirty-chip"' in html and "外观尚未应用" in html,
        html[:180],
    ))
    at.button(key="generate_Volcano Plot").click().run()
    checks.append((
        "重新生成后提示消失",
        "外观尚未应用" not in status_html(at),
        "ok",
    ))

    at.button(key="style_site_Volcano Plot").click().run()
    for _ in range(3):
        if len(at.get("plotly_chart")) >= 1:
            break
        at.run()
    checks.append((
        "恢复网站外观：反馈 + 重绘",
        not at.exception
        and "已恢复网站默认外观" in success_text(at)
        and len(at.get("plotly_chart")) >= 1,
        success_text(at),
    ))

    at.button(key="reset_Volcano Plot").click().run()
    for _ in range(3):
        if len(at.get("plotly_chart")) >= 1:
            break
        at.run()
    checks.append((
        "重置参数：反馈 + 重绘",
        not at.exception
        and "参数已重置" in success_text(at)
        and len(at.get("plotly_chart")) >= 1,
        success_text(at),
    ))

    checks.append((
        "导出按钮接入完成回调",
        source.count("on_click=mark_export_complete") == 2,
        str(source.count("on_click=mark_export_complete")),
    ))
    at.session_state["_action_notice"] = (
        "导出完成：demo.png（PNG）已生成并开始下载。"
    )
    at.run()
    checks.append((
        "导出完成提示渲染",
        "导出完成" in success_text(at) and "demo.png" in success_text(at),
        success_text(at),
    ))

    theme_app = new_app()
    theme_app.selectbox(key="theme_selector_top").set_value("Midnight").run()
    theme_css = "\n".join(str(block.value) for block in theme_app.markdown)
    checks.append((
        "顶栏主题切换生效",
        theme_app.session_state["theme"] == "Midnight" and "#0b1220" in theme_css,
        f"{theme_app.session_state['theme']} / dark={'#0b1220' in theme_css}",
    ))

    advanced_cases = {
        "Heatmap": "heatmap_cluster_rows",
        "Volcano Plot": "volcano_topn",
        "PCA": "pca_scale_mode",
        "Kaplan-Meier": "km_show_ci",
        "Node-link Diagram": "ndl_detail_layer",
        "Sankey": "sk_node_width",
    }
    for name, key in advanced_cases.items():
        target = open_plot(new_app(), name)
        labels = {item.label for item in target.get("expander")}
        checks.append((
            f"{name}：常用/高级参数分区",
            "常用参数" in labels
            and "高级参数" in labels
            and key in control_keys(target)
            and not target.exception,
            str(sorted(labels)),
        ))

    failures = 0
    for label, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        failures += 0 if ok else 1
    print(f"toolbar-refactor-apptest: {len(checks) - failures}/{len(checks)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
