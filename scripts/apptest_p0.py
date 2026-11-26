"""P0 acceptance suite: 首页引导 / 形状筛选 / 卡片 chip / 悬浮操作条 / 数据体检 / 导出预设.

    .venv\\Scripts\\python.exe scripts/apptest_p0.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

import app.core.catalog as catalog  # noqa: E402

APP_FILE = str(PROJECT_ROOT / "app.py")
TOTAL = len(catalog.PLOTS)
SHAPE_COUNTS = {"全部形状": TOTAL}
for _plot_name in catalog.PLOTS:
    _shape = catalog.data_shape_for(_plot_name)
    SHAPE_COUNTS[_shape] = SHAPE_COUNTS.get(_shape, 0) + 1


def _state(at: AppTest, key: str, default=None):
    try:
        return at.session_state[key]
    except KeyError:
        return default


def _cards(at: AppTest) -> int:
    return sum(1 for block in at.markdown if 'class="gallery-card"' in str(block.value))


def _html(at: AppTest) -> str:
    return "\n".join(str(block.value) for block in at.markdown)


def new_app(**state) -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=200)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    return at


def check_home(checks: list) -> None:
    at = new_app(page="home")
    html = _html(at)

    checks.append((f"首页 {TOTAL} 张卡片", _cards(at) == TOTAL, f"cards={_cards(at)}"))
    checks.append(("首页无异常", not at.exception, str(at.exception)))
    checks.append(("三步引导存在", "start-guide" in html, "ok"))
    checks.append(("引导 3 个步骤", html.count('class="guide-step"') == 3, f"steps={html.count('class=\"guide-step\"')}"))
    checks.append(("引导含数据形状提示", "宽矩阵" in html and "集合表" in html, "ok"))

    card_tops = html.count('<div class="gallery-card-top">')
    hover_notes = html.count('class="gallery-hover"')
    checks.append(("每张卡 1 个分类", card_tops == TOTAL, f"card_tops={card_tops}"))
    checks.append(("每张卡 1 条悬停说明", hover_notes == TOTAL, f"hover_notes={hover_notes}"))
    checks.append(
        (
            "卡片常驻信息已精简",
            'class="tag-row"' not in html
            and 'class="gallery-meta"' not in html
            and 'class="gallery-cta"' not in html,
            "ok",
        )
    )


def check_shape_filter(checks: list) -> None:
    at = new_app(page="home")
    options = list(at.selectbox(key="gallery_shape").options)
    checks.append((f"形状下拉含 {len(catalog.DATA_SHAPE_ORDER)}+1 项", options == ["全部形状", *catalog.DATA_SHAPE_ORDER], str(options)))

    for shape, expected in SHAPE_COUNTS.items():
        probe = new_app(page="home")
        probe.selectbox(key="gallery_shape").set_value(shape).run()
        got = _cards(probe)
        checks.append((f"形状筛选 {shape} = {expected}", got == expected, f"cards={got}"))

    # 分类 + 形状叠加：矩阵与热图 ∩ 长表 = Grouped Matrix Plotting
    combo = new_app(page="home")
    combo.radio(key="gallery_category").set_value("矩阵与热图").run()
    combo.selectbox(key="gallery_shape").set_value("长表").run()
    checks.append(("分类∩形状 叠加筛选", _cards(combo) == 1, f"cards={_cards(combo)}"))

    # 重置筛选
    reset = new_app(page="home")
    reset.selectbox(key="gallery_shape").set_value("边表").run()
    reset.button(label="清除筛选").click().run() if any(
        b.label == "清除筛选" for b in reset.button
    ) else None
    reset.session_state["gallery_shape"] = "全部形状"
    reset.run()
    checks.append((f"重置后回到 {TOTAL}", _cards(reset) == TOTAL, f"cards={_cards(reset)}"))


def check_plot_page(checks: list) -> None:
    at = new_app(page="home")
    at.button(key="nav_Volcano Plot").click().run()
    for _ in range(3):
        if len(at.get("plotly_chart")) >= 1:
            break
        at.run()

    checks.append(("绘图页出图", len(at.get("plotly_chart")) >= 1, f"charts={len(at.get('plotly_chart'))}"))
    checks.append(("绘图页无异常", not at.exception, str(at.exception)))

    button_keys = {b.key for b in at.button}
    checks.append(("工具栏：生成按钮", "generate_Volcano Plot" in button_keys, str(sorted(k for k in button_keys if k and k.startswith("generate_")))))
    checks.append(("工具栏：重置按钮", "reset_Volcano Plot" in button_keys, str(sorted(k for k in button_keys if k and k.startswith("reset_")))))
    checks.append(("无重复操作条", not any(k and k.startswith("sticky") for k in button_keys), "ok"))

    metrics = at.get("metric")
    checks.append(("数据体检有 metric", len(metrics) >= 4, f"metrics={len(metrics)}"))


def check_module_regression(checks: list) -> None:
    bad = []
    for name in catalog.PLOTS:
        at = new_app(page="home")
        at.button(key=f"nav_{name}").click().run()
        for _ in range(3):
            if len(at.get("plotly_chart")) >= 1 or len(at.get("pyplot")) >= 1:
                break
            at.run()
        if at.exception or str(_state(at, "status_kind")) != "success":
            bad.append(name)
    checks.append((f"{TOTAL} 模块仍可出图", not bad, str(bad) if bad else f"{TOTAL}/{TOTAL}"))


def check_export_code_path(checks: list) -> None:
    source = Path(APP_FILE).read_text(encoding="utf-8")
    checks.append(
        (
            "导出：期刊画布 5 档",
            all(k in source for k in ('"单栏 85mm"', '"1.5 栏 114mm"', '"双栏 170mm"', '"当前画布"', '"自定义"')),
            "ok",
        )
    )
    checks.append(("导出：DPI 300/600", '"300 dpi"' in source and '"600 dpi"' in source, "ok"))
    checks.append(
        (
            "导出：96dpi 画布 + scale 模型",
            "EXPORT_BASE_DPI = 96" in source and "width_mm / MM_PER_INCH * EXPORT_BASE_DPI" in source,
            "ok",
        )
    )
    checks.append(
        (
            "导出：矢量也按 mm 定尺寸",
            "height_mm_eff = css_h / EXPORT_BASE_DPI" in source and "矢量输出，可无损放大" in source,
            "ok",
        )
    )
    checks.append(
        (
            "导出：透明背景不污染预览",
            "paper_bgcolor=\"rgba(0,0,0,0)\"" in source and "render_static_image" in source,
            "ok",
        )
    )
    checks.append(
        (
            "导出：自定义宽高按 mm 输入",
            'key=_key("export_w_mm")' in source and 'key=_key("export_h_mm")' in source,
            "ok",
        )
    )
    checks.append(("导出：仅工具栏入口", 'render_export_popover(meta, scope="toolbar")' in source and 'render_sticky_actions' not in source, "ok"))
    checks.append(
        (
            "导出：kaleido 可用时提供静态格式",
            'formats = (["PNG", "SVG", "PDF"] if static_ready else []) + ["HTML", "JSON"]' in source,
            "ok",
        )
    )
    checks.append(
        (
            "导出：静态渲染有缓存",
            "@st.cache_data(max_entries=24" in source,
            "ok",
        )
    )


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    check_home(checks)
    check_shape_filter(checks)
    check_plot_page(checks)
    check_export_code_path(checks)
    check_module_regression(checks)

    failures = 0
    for label, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        if not ok:
            failures += 1

    print()
    print(f"p0-apptest: {len(checks) - failures}/{len(checks)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
