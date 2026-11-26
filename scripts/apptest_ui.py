"""AppTest suite for the phase-3 UI refactor (T4).

Covers what ``apptest_native_modules`` does not: the home page composition
(23 cards, search, category filter), routing into the 6 new modules, the
plot-page tabs, and the PNG resolution radio in the export popover.

    .venv\\Scripts\\python.exe scripts/apptest_ui.py
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
NEW_MODULES = ["Volcano Plot", "PCA", "Heatmap", "UpSet Plot", "Kaplan-Meier", "Manhattan Plot"]


def _state(at: AppTest, key: str, default=None):
    try:
        return at.session_state[key]
    except KeyError:
        return default


def _count_cards(at: AppTest) -> int:
    """Count rendered gallery anchors (the CSS block also mentions the class name)."""
    return sum(1 for block in at.markdown if 'class="gallery-card"' in str(block.value))


def new_app(**state) -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=200)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    return at


def check_home() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    at = new_app(page="home")

    card_count = _count_cards(at)
    checks.append((f"首页 {len(catalog.PLOTS)} 张卡片", card_count == len(catalog.PLOTS), f"cards={card_count}"))
    checks.append(("首页无异常", not at.exception, str(at.exception)))

    html = "\n".join(str(block.value) for block in at.markdown)
    checks.append(("页头 stat chip ×3", html.count("stat-chip") >= 3, f"chips={html.count('stat-chip')}"))
    checks.append(("顶栏存在", "topbar-brand" in html, "ok" if "topbar-brand" in html else "missing"))
    checks.append(("页脚模块数", f"{len(catalog.PLOTS)} 图形" in html, "ok"))
    checks.append(("无 hero 区块", "class=\"hero" not in html, "ok"))

    # 搜索筛选
    at.text_input(key="gallery_query").set_value("volcano").run()
    filtered = _count_cards(at)
    checks.append(("搜索 volcano 命中 1 张", filtered == 1, f"cards={filtered}"))
    total = len(catalog.PLOTS)
    checks.append((f"计数显示 1 / {total}", f"显示 1 / {total}" in "\n".join(str(b.value) for b in at.markdown), "ok"))

    # 分类筛选
    at2 = new_app(page="home")
    at2.radio(key="gallery_category").set_value("矩阵与热图").run()
    cat_cards = _count_cards(at2)
    checks.append(("分类筛选 矩阵与热图 = 3", cat_cards == 3, f"cards={cat_cards}"))

    return checks


def check_routing() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    for name in NEW_MODULES:
        at = new_app(page="home")
        at.button(key=f"nav_{name}").click().run()
        for _ in range(3):
            if len(at.get("plotly_chart")) >= 1:
                break
            at.run()
        ok = (not at.exception) and str(_state(at, "status_kind")) == "success"
        checks.append((f"进入 {name}", ok, str(_state(at, "status"))))
    return checks


def check_plot_page() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    at = new_app(page="home")
    at.button(key="nav_Volcano Plot").click().run()
    for _ in range(3):
        if len(at.get("plotly_chart")) >= 1:
            break
        at.run()

    html = "\n".join(str(block.value) for block in at.markdown)
    checks.append(("面包屑含分类", "统计与富集" in html, "ok"))
    tabs = [tab.label for tab in at.tabs]
    checks.append(("绘图页 3 个 Tab", tabs == ["图形", "数据预览", "使用说明"], str(tabs)))
    checks.append(("绘图页有图", len(at.get("plotly_chart")) >= 1, f"charts={len(at.get('plotly_chart'))}"))
    checks.append(("绘图页无异常", not at.exception, str(at.exception)))
    return checks


def check_export_code_path() -> list[tuple[str, bool, str]]:
    """导出面板的规格换算在源码层断言（AppTest 看不到 canvas 尺寸细节）。"""
    s_export = Path(APP_FILE).read_text(encoding="utf-8")
    checks: list[tuple[str, bool, str]] = [
        (
            "导出：PNG 才有 dpi 选择",
            'raster=(fmt == "PNG")' in s_export and '"输出精度"' in s_export,
            "dpi 只对位图生效",
        ),
        (
            "导出：静态图支持 PNG/SVG/PDF",
            '{"PNG", "SVG", "PDF"}' in s_export,
            "ok",
        ),
        (
            "导出：尺寸与 scale 传入渲染器",
            "render_static_image(" in s_export and "round(scale, 4)" in s_export and "css_w," in s_export,
            "ok",
        ),
        (
            "导出：矢量也按 mm 定画布",
            "矢量输出，可无损放大" in s_export and "_css_size(width_mm, height_mm" in s_export,
            "ok",
        ),
        (
            "导出：无 kaleido 时只给 HTML/JSON",
            'if static_ready else []) + ["HTML", "JSON"]' in s_export,
            "ok",
        ),
    ]
    return checks


def check_card_style() -> list[tuple[str, bool, str]]:
    css = (PROJECT_ROOT / "app" / "assets" / "styles.css").read_text(encoding="utf-8")
    return [
        ("卡片悬停说明层存在", ".gallery-hover" in css, "ok"),
        ("卡片悬停上浮与描边", "transform: translateY(-3px)" in css and "border-color: var(--accent)" in css, "ok"),
        ("预览悬停轻缩放", "transform: scale(1.03)" in css, "ok"),
        ("侧栏折叠容器 12px 圆角", "border-radius: 12px;" in css and "margin-bottom: 0.5rem;" in css, "ok"),
        ("减少动态效果降级", "prefers-reduced-motion: reduce" in css, "ok"),
    ]


def main() -> int:
    all_checks: list[tuple[str, bool, str]] = []
    all_checks += check_home()
    all_checks += check_plot_page()
    all_checks += check_export_code_path()
    all_checks += check_card_style()
    all_checks += check_routing()

    failures = 0
    for label, ok, detail in all_checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        if not ok:
            failures += 1

    print()
    print(f"ui-apptest: {len(all_checks) - failures}/{len(all_checks)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
