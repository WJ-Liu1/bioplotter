"""AppTest suite for the in-home documentation split view.

Covers: clicking a home card opens the doc pane (?page=home&doc=...),
card/detail counts, per-document detail, filters, bundled data downloads,
Python code, and env assets.

    .venv\\Scripts\\python.exe scripts/apptest_docs_hub.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

import app.core.catalog as catalog  # noqa: E402
from app.core.docs_content import RECIPES  # noqa: E402
from app.core.py_recipes import PY_RECIPES, module_source_for, py_code_for  # noqa: E402
from app.core.sample_utils import SAMPLE_PATHS  # noqa: E402

APP_FILE = str(PROJECT_ROOT / "app.py")


def new_docs_app(doc: str | None = None) -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=240)
    at.query_params["page"] = "home"
    if doc:
        at.query_params["doc"] = doc
    at.run()
    return at


def _html(at: AppTest) -> str:
    return "\n".join(str(block.value) for block in at.markdown)


def _count(html_text: str, card_class: str) -> int:
    """统计卡片元素；注入的 <style> 只含 `.class {`，不会误命中。"""
    return html_text.count(f'class="{card_class}"') + html_text.count(f'class="{card_class} ')


def _state(at: AppTest, key: str, default=None):
    try:
        return at.session_state[key]
    except KeyError:
        return default


def check_shell() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    at = new_docs_app()
    checks.append(("文档页无异常", not at.exception, str(at.exception)))
    checks.append(("路由 page=home", _state(at, "page") == "home", str(_state(at, "page"))))

    html = _html(at)
    checks.append(
        (
            f"默认首页图库 {len(catalog.PLOTS)} 张",
            _count(html, "gallery-card") == len(catalog.PLOTS),
            f"cards={_count(html, 'gallery-card')}",
        )
    )
    checks.append(
        (
            "默认首页不显示文档栏",
            '<div class="docs-detail-head">' not in html,
            "ok" if '<div class="docs-detail-head">' not in html else "detail leaked",
        )
    )
    checks.append(
        (
            "卡片可点击打开文档",
            any(str(btn.label) == "查看 Chord Diagram 的说明" for btn in at.button),
            "ok",
        )
    )
    return checks


def check_split_view() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    at = new_docs_app("Heatmap")
    html = _html(at)
    checks.append(
        (
            "展开态不再有左侧目录",
            _count(html, "docs-toc-item") == 0,
            f"toc_items={_count(html, 'docs-toc-item')}",
        )
    )
    checks.append(
        (
            f"展开态卡片 {len(catalog.PLOTS)} 张",
            _count(html, "docs-card") == len(catalog.PLOTS),
            f"cards={_count(html, 'docs-card')}",
        )
    )
    checks.append(
        (
            "左侧卡片与右侧详情同屏",
            _count(html, "docs-card") == len(catalog.PLOTS)
            and '<div class="docs-detail-head">' in html,
            "ok",
        )
    )
    checks.append(
        (
            "文档卡片仅保留名称与分类",
            html.count('<div class="docs-card-top"><span class="pill">') == len(catalog.PLOTS)
            and 'class="docs-card-file"' not in html
            and all(
                'class="tag-row"' not in str(block.value)
                for block in at.markdown
                if '<div class="docs-card' in str(block.value)
            ),
            "ok",
        )
    )
    checks.append(
        (
            "文档卡片含悬停说明",
            html.count('class="gallery-hover"') == len(catalog.PLOTS),
            f"hover_notes={html.count('class=\"gallery-hover\"')}",
        )
    )
    checks.append(
        (
            "提供收起文档入口",
            any("收起文档" in str(btn.label) for btn in at.button),
            "ok",
        )
    )
    checks.append(
        (
            "右侧四个文档页签",
            [tab.label for tab in at.tabs][:4] == ["说明", "数据", "Python 代码", "环境"],
            str([tab.label for tab in at.tabs][:4]),
        )
    )
    return checks


def check_default_detail() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    at = new_docs_app("Heatmap")
    html = _html(at)
    checks.append(("默认文档标题", "<h2>Heatmap</h2>" in html, "ok" if "<h2>Heatmap</h2>" in html else "missing"))
    checks.append(("文档摘要存在", catalog.PLOTS["Heatmap"].summary[:12] in html, "ok"))
    codes = "\n".join(str(block.value) for block in at.code)
    checks.append(("说明含输入格式", "第 1 列行名" in codes or "第 1 列行名" in html, "ok"))
    checks.append(("代码默认 Python", "import pandas" in codes and "clustermap" in codes, "ok"))
    checks.append(("模块源码入口", "app/modules/heatmap.py" in html, "ok"))
    return checks


def check_card_navigation() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    at = new_docs_app("Chord Diagram")
    html = _html(at)
    checks.append(
        (
            "卡片高亮当前项",
            'class="docs-card selected"' in html
            and '<div class="gallery-hover">' in html,
            "ok",
        )
    )
    codes = "\n".join(str(block.value) for block in at.code)
    checks.append(("Chord Python 示例", "import plotly" in codes and "chord_sample.csv" in codes, "ok"))
    checks.append(("Chord 完整源码", "def _chord_centerline" in codes, "ok"))
    return checks


def check_filters() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    at = new_docs_app("Heatmap")
    at.text_input(key="gallery_query").set_value("volcano").run()
    html = _html(at)
    cards = _count(html, "docs-card")
    checks.append(("搜索 volcano 命中 1 张", cards == 1, f"cards={cards}"))
    checks.append(("搜索后右侧同步", "<h2>Volcano Plot</h2>" in html, "ok"))

    at2 = new_docs_app("Heatmap")
    at2.radio(key="gallery_category").set_value("环形与极坐标").run()
    html2 = _html(at2)
    expected = sum(1 for meta in catalog.PLOTS.values() if meta.category == "环形与极坐标")
    cards2 = _count(html2, "docs-card")
    checks.append((f"分类筛选 {expected} 张", cards2 == expected, f"cards={cards2}"))
    checks.append(
        (
            "分类后右侧落在该分类",
            ">环形与极坐标<" in html2,
            "ok",
        )
    )
    return checks


def check_downloads() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    at = new_docs_app("Sankey")
    try:
        buttons = at.get("download_button")
    except Exception:
        buttons = []
    checks.append(("数据下载按钮 >= 3", len(buttons) >= 3, f"buttons={len(buttons)}"))

    sankey_files = [SAMPLE_PATHS[key] for key in catalog.PLOTS["Sankey"].sample_keys]
    checks.append(
        (
            "Sankey 内置数据齐全",
            all(path.exists() for path in sankey_files),
            ", ".join(path.name for path in sankey_files),
        )
    )
    return checks


def check_content_coverage() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    missing = [name for name in catalog.PLOTS if name not in RECIPES]
    checks.append(("每个图形都有说明要点", not missing, f"missing={missing}"))
    empty_notes = [name for name, recipe in RECIPES.items() if not recipe.notes.strip()]
    checks.append(("说明要点非空", not empty_notes, f"empty={empty_notes}"))
    missing_py = [name for name in catalog.PLOTS if name not in PY_RECIPES]
    checks.append(("每个图形都有 Python 示例", not missing_py, f"missing={missing_py}"))
    empty_py = [name for name in PY_RECIPES if not py_code_for(name).strip()]
    checks.append(("Python 示例非空", not empty_py, f"empty={empty_py}"))
    no_source = [name for name in catalog.PLOTS if module_source_for(name) is None]
    checks.append(("完整模块源码可读", not no_source, f"missing={no_source}"))
    bad = [
        name
        for name in catalog.PLOTS
        if not any(path.name in py_code_for(name) for path in (SAMPLE_PATHS[k] for k in catalog.PLOTS[name].sample_keys))
    ]
    checks.append(("Python 代码引用同名示例数据", not bad, f"bad={bad}"))

    env_files = [
        PROJECT_ROOT / "env" / "requirements-lock.txt",
        PROJECT_ROOT / "env" / "README.md",
    ]
    checks.append(("依赖环境文件存在", all(path.exists() for path in env_files), "ok"))

    site_source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    docs_source = (PROJECT_ROOT / "app" / "docs_hub.py").read_text(encoding="utf-8")
    checks.append(
        (
            "文档页仅保留 Python 代码入口",
            "R 代码" not in docs_source and "install_r_deps" not in docs_source
            and "复制 R 代码" not in site_source,
            "ok",
        )
    )
    checks.append(
        (
            "依赖环境仅包含 Python",
            not (PROJECT_ROOT / "env" / "install_r_deps.R").exists(),
            "ok",
        )
    )
    return checks


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    for checker in (
        check_shell,
        check_split_view,
        check_default_detail,
        check_card_navigation,
        check_filters,
        check_downloads,
        check_content_coverage,
    ):
        try:
            results.extend(checker())
        except Exception as exc:  # noqa: BLE001
            results.append((f"{checker.__name__} 异常", False, repr(exc)))

    passed = 0
    for label, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        passed += 1 if ok else 0
    print(f"\ndocs-hub-apptest: {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
