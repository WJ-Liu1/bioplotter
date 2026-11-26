"""Project bundle acceptance suite: save, restore, upload data, sample overrides.

    .venv\\Scripts\\python.exe scripts/apptest_project.py
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit.testing.v1 import AppTest  # noqa: E402

from app.core.catalog import meta_for  # noqa: E402
from app.core.project_io import (  # noqa: E402
    ProjectFile,
    UPLOAD_CACHE_KEY,
    build_project_bundle,
    collect_params,
    collect_upload_entries,
    project_signature,
    restore_project_bundle,
)

APP_FILE = str(Path(__file__).resolve().parents[1] / "app.py")


def new_app() -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=200)
    at.session_state["page"] = "home"
    at.run()
    return at


def open_plot(at: AppTest, name: str) -> None:
    at.button(key=f"nav_{name}").click().run()
    for _ in range(3):
        if len(at.get("plotly_chart")) >= 1 or len(at.get("pyplot")) >= 1:
            break
        at.run()


def _state(at: AppTest, key: str, default=None):
    try:
        return at.session_state[key]
    except KeyError:
        return default


def check_panel(checks: list) -> None:
    at = new_app()
    checks.append(
        (
            "首页有项目包入口",
            "project_restore_btn" in {b.key for b in at.button},
            str(sorted(k for k in (b.key for b in at.button) if k and k.startswith("project_"))),
        )
    )
    checks.append(("首页无异常", not at.exception, str(at.exception)))

    plot = new_app()
    open_plot(plot, "Volcano Plot")
    keys = {b.key for b in plot.button}
    restore_keys = {b.key for b in at.button}
    checks.append(
        (
            "绘图页有准备/载入按钮",
            "project_prepare_Volcano Plot" in keys and "project_restore_btn" in keys,
            str(sorted(k for k in keys if k and k.startswith("project_"))),
        )
    )
    checks.append((
        "首页仅恢复入口无准备按钮",
        "project_restore_btn" in restore_keys and not any(
            k and k.startswith("project_prepare_") for k in restore_keys
        ),
        str(sorted(k for k in restore_keys if k and k.startswith("project_"))),
    ))
    checks.append(("绘图页无异常", not plot.exception, str(plot.exception)))


def check_prepare_button(checks: list) -> None:
    at = new_app()
    open_plot(at, "Volcano Plot")
    at.button(key="project_prepare_Volcano Plot").click().run()
    bundle = _state(at, "_project_bundle_bytes")
    checks.append(("准备按钮生成项目包", isinstance(bundle, bytes) and len(bundle) > 1000, f"{len(bundle or b'')} bytes"))
    checks.append(("准备后无异常", not at.exception, str(at.exception)))
    if not isinstance(bundle, bytes):
        return

    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        names = set(zf.namelist())
    checks.append(("manifest 格式", manifest.get("format") == "bioplotter-project", str(manifest.get("format"))))
    checks.append(("manifest 模块", manifest.get("module") == "Volcano Plot", str(manifest.get("module"))))
    checks.append(("包含 figure.json", "figure.json" in names, str(sorted(n for n in names if not n.startswith(("samples/", "data/"))))))
    checks.append(("包含示例快照", any(n.startswith("samples/") for n in names), f"samples={sum(1 for n in names if n.startswith('samples/'))}"))


def check_roundtrip(checks: list) -> None:
    at = new_app()
    open_plot(at, "Volcano Plot")
    at.session_state["theme"] = "Dark"
    at.session_state["sci_palette"] = "No.013"
    at.session_state["sci_palette_applied"] = "No.013"
    at.session_state["volcano_fc_thr"] = 1.5
    bundle, filename, signature = build_project_bundle(
        "Volcano Plot", meta_for("Volcano Plot"), at.session_state
    )
    checks.append(("项目包文件名", filename.endswith(".bioplot.zip"), filename))
    checks.append(("签名稳定", signature == project_signature("Volcano Plot", at.session_state), signature[:12]))

    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    checks.append(("保存参数", manifest["params"].get("volcano_fc_thr") == 1.5, str(manifest["params"].get("volcano_fc_thr"))))
    checks.append(("保存主题/配色", manifest.get("theme") == "Dark" and manifest.get("sci_palette") == "No.013", f"{manifest.get('theme')}/{manifest.get('sci_palette')}"))

    fresh = new_app()
    restore_project_bundle(bundle, fresh.session_state, {"Volcano Plot", "PCA"})
    fresh.query_params["page"] = "plot"
    fresh.query_params["plot"] = "Volcano Plot"
    fresh.run()
    checks.append(("恢复模块", _state(fresh, "plot_type") == "Volcano Plot", str(_state(fresh, "plot_type"))))
    checks.append(("恢复参数", _state(fresh, "volcano_fc_thr") == 1.5, str(_state(fresh, "volcano_fc_thr"))))
    checks.append(("恢复主题", _state(fresh, "theme") == "Dark", str(_state(fresh, "theme"))))
    checks.append(("恢复配色", _state(fresh, "sci_palette") == "No.013", str(_state(fresh, "sci_palette"))))
    checks.append(("恢复后出图", _state(fresh, "status_kind") == "success" and len(fresh.get("plotly_chart")) >= 1, str(_state(fresh, "status"))))
    checks.append(("恢复无异常", not fresh.exception, str(fresh.exception)))


def check_upload_roundtrip(checks: list) -> None:
    csv = b"gene,log2FC,pvalue\nA,1.2,0.01\n"
    fake_state = {
        "plot_type": "Volcano Plot",
        "figure_title": "uploaded volcano",
        "theme": "Light",
        "sci_palette": "Auto",
        "volcano_fc_thr": 0.8,
        "volcano_use_sample": False,
        "last_plotly": None,
        UPLOAD_CACHE_KEY: {
            "volcano_file_upload": {
                "key": "volcano_file_upload",
                "module": "Volcano Plot",
                "name": "mine.csv",
                "type": "text/csv",
                "size": len(csv),
                "sha256": "test",
                "bytes": csv,
            }
        },
    }
    bundle, _, _ = build_project_bundle("Volcano Plot", meta_for("Volcano Plot"), fake_state)
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    checks.append(
        (
            "上传数据进入项目包",
            manifest["uploads"].get("volcano_file_upload", {}).get("name") == "mine.csv",
            str(manifest["uploads"].get("volcano_file_upload")),
        )
    )

    fresh = new_app()
    restore_project_bundle(bundle, fresh.session_state, {"Volcano Plot"})
    fresh.query_params["page"] = "plot"
    fresh.query_params["plot"] = "Volcano Plot"
    fresh.run()
    checks.append(
        (
            "恢复上传数据并出图",
            _state(fresh, "status_kind") == "success" and "1 行" in str(_state(fresh, "status")),
            str(_state(fresh, "status")),
        )
    )
    checks.append(("恢复上传数据无异常", not fresh.exception, str(fresh.exception)))

    rebundle, _, _ = build_project_bundle(
        "Volcano Plot", meta_for("Volcano Plot"), fresh.session_state
    )
    with zipfile.ZipFile(io.BytesIO(rebundle)) as zf:
        rebound_manifest = json.loads(zf.read("manifest.json"))
    checks.append(
        (
            "恢复后再次保存仍带上传数据",
            rebound_manifest["uploads"].get("volcano_file_upload", {}).get("name") == "mine.csv",
            str(rebound_manifest["uploads"].keys()),
        )
    )


def check_multi_file_roundtrip(checks: list) -> None:
    links = Path("sample_data/sankey_links.txt").read_bytes()
    nodes = Path("sample_data/sankey_nodes.txt").read_bytes()
    fake_state = {
        "plot_type": "Sankey",
        "figure_title": "uploaded sankey",
        "theme": "Light",
        "sci_palette": "Auto",
        "sk_use_sample": False,
        "sk_input_mode": "Upload data",
        "last_plotly": None,
        UPLOAD_CACHE_KEY: {
            "sk_links_file": {
                "key": "sk_links_file",
                "module": "Sankey",
                "name": "links.txt",
                "type": "text/plain",
                "size": len(links),
                "sha256": "links",
                "bytes": links,
            },
            "sk_nodes_file": {
                "key": "sk_nodes_file",
                "module": "Sankey",
                "name": "nodes.txt",
                "type": "text/plain",
                "size": len(nodes),
                "sha256": "nodes",
                "bytes": nodes,
            },
        },
    }
    bundle, _, _ = build_project_bundle("Sankey", meta_for("Sankey"), fake_state)

    fresh = new_app()
    restore_project_bundle(bundle, fresh.session_state, {"Sankey"})
    fresh.query_params["page"] = "plot"
    fresh.query_params["plot"] = "Sankey"
    fresh.run()
    checks.append(
        (
            "多文件模块恢复上传数据",
            _state(fresh, "status_kind") == "success" and len(fresh.get("plotly_chart")) >= 1,
            str(_state(fresh, "status")),
        )
    )


def check_sample_override(checks: list) -> None:
    at = new_app()
    open_plot(at, "Volcano Plot")
    bundle, _, _ = build_project_bundle(
        "Volcano Plot", meta_for("Volcano Plot"), at.session_state
    )
    with zipfile.ZipFile(io.BytesIO(bundle)) as source:
        members = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(members["manifest.json"])
    sample_arc = next(
        info["archive"]
        for key, info in manifest["samples"].items()
        if key == "volcano_degs"
    )
    members[sample_arc] = b"gene,log2FC,pvalue\nA,1.5,0.01\nB,-1.5,0.02\n"
    patched = io.BytesIO()
    with zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)

    fresh = new_app()
    restore_project_bundle(patched.getvalue(), fresh.session_state, {"Volcano Plot"})
    fresh.query_params["page"] = "plot"
    fresh.query_params["plot"] = "Volcano Plot"
    fresh.run()
    checks.append(
        (
            "项目内示例数据优先",
            _state(fresh, "status_kind") == "success" and "2 行" in str(_state(fresh, "status")),
            str(_state(fresh, "status")),
        )
    )


def check_dataframe_param_roundtrip(checks: list) -> None:
    at = new_app()
    open_plot(at, "Genomic Variation Viewer")
    table = pd.DataFrame(
        {"label": ["rs1", "rs2"], "size": [1.2, 0.8], "color": ["#ff0000", "#00ff00"]}
    )
    at.session_state["genvar_override_table"] = table
    bundle, _, _ = build_project_bundle(
        "Genomic Variation Viewer",
        meta_for("Genomic Variation Viewer"),
        at.session_state,
    )
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    stored = manifest["params"].get("genvar_override_table")
    checks.append(
        (
            "DataFrame 参数写入项目包",
            isinstance(stored, dict)
            and stored.get("__bioplot_type__") == "dataframe"
            and len(stored.get("rows", [])) == 2,
            str(stored)[:160],
        )
    )

    fresh = new_app()
    restore_project_bundle(bundle, fresh.session_state, {"Genomic Variation Viewer"})
    fresh.query_params["page"] = "plot"
    fresh.query_params["plot"] = "Genomic Variation Viewer"
    fresh.run()
    restored = _state(fresh, "genvar_override_table")
    checks.append(
        (
            "DataFrame 参数恢复为表格",
            isinstance(restored, pd.DataFrame)
            and restored.shape == (2, 3)
            and restored.iloc[0]["label"] == "rs1",
            f"{type(restored).__name__} {getattr(restored, 'shape', None)}",
        )
    )
    checks.append(("表格参数恢复后无异常", not fresh.exception, str(fresh.exception)))


def check_stale_upload_cleanup(checks: list) -> None:
    fake_state = {
        "plot_type": "Volcano Plot",
        UPLOAD_CACHE_KEY: {
            "volcano_file_upload": {
                "key": "volcano_file_upload",
                "module": "Volcano Plot",
                "name": "old.csv",
                "type": "text/csv",
                "size": 3,
                "sha256": "old",
                "bytes": b"old",
            },
            "volcano_other_upload": {
                "key": "volcano_other_upload",
                "module": "Volcano Plot",
                "name": "other.csv",
                "type": "text/csv",
                "size": 5,
                "sha256": "other",
                "bytes": b"other",
            },
        },
    }
    params = collect_params(fake_state)
    checks.append(
        (
            "瞬态按钮状态不进入参数",
            "genvar_reset_range_btn" not in params
            and "genvar_override_editor_state" not in params,
            str(sorted(params.keys())[:5]),
        )
    )

    from app.core.project_io import _forget_upload

    _forget_upload("volcano_file_upload", fake_state)
    uploads = collect_upload_entries("Volcano Plot", fake_state)
    checks.append(
        (
            "清空上传会移除旧缓存",
            "volcano_file_upload" not in uploads
            and "volcano_other_upload" in uploads,
            str(sorted(uploads)),
        )
    )


def check_bundle_helpers(checks: list) -> None:
    file_obj = ProjectFile("x.csv", b"abc", "text/csv")
    checks.append(("ProjectFile 读取", file_obj.getvalue() == b"abc" and file_obj.size == 3, f"{file_obj.name}/{file_obj.size}"))
    file_obj.seek(1)
    chunk = file_obj.read()
    checks.append(("ProjectFile seek/read", chunk == b"bc", str(chunk)))

    invalid = False
    try:
        restore_project_bundle(b"not a zip", {}, {"Volcano Plot"})
    except Exception:
        invalid = True
    checks.append(("无效项目包被拒绝", invalid, "ok"))

    at = new_app()
    open_plot(at, "Volcano Plot")
    first = project_signature("Volcano Plot", at.session_state)
    at.session_state["volcano_fc_thr"] = 2.0
    second = project_signature("Volcano Plot", at.session_state)
    checks.append(("参数变化会改变签名", first != second, f"{first[:8]} -> {second[:8]}"))


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    check_panel(checks)
    check_prepare_button(checks)
    check_roundtrip(checks)
    check_upload_roundtrip(checks)
    check_multi_file_roundtrip(checks)
    check_sample_override(checks)
    check_dataframe_param_roundtrip(checks)
    check_stale_upload_cleanup(checks)
    check_bundle_helpers(checks)

    failures = 0
    for label, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        if not ok:
            failures += 1

    print()
    print(f"project-apptest: {len(checks) - failures}/{len(checks)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
