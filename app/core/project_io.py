"""Project bundle save/restore for BioPlotter.

The bundle is a self-contained ``.bioplot.zip`` containing:

* ``manifest.json``: app version, module, parameters, theme, data metadata
* ``data/``: raw files uploaded by the user
* ``samples/``: built-in sample files, so old projects stay reproducible
* ``figure.json``: Plotly figure configuration (when available)
* ``help.md`` / ``README.txt``: human-readable context

Restoring happens in two layers:

1. Sample overrides are written to a temporary directory and picked up by
   :func:`app.core.sample_utils.get_sample_path`.
2. Uploaded files are kept in ``session_state`` and returned by a transparent
   wrapper around ``st.file_uploader`` when the widget itself is empty.

That keeps the existing 24 modules untouched while still restoring the exact
data they originally used.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import plotly.io as pio
import streamlit as st

from app.core.palettes import SCI_PALETTES
from app.core.sample_utils import SAMPLE_PATHS, get_sample_path
from app.core.theme import THEMES
from app.core.figure_style import (
    figure_style_manifest,
    restore_figure_style,
)


PROJECT_FORMAT = "bioplotter-project"
PROJECT_FORMAT_VERSION = 1
APP_VERSION = "3.0"
MAX_PROJECT_BYTES = 200 * 1024 * 1024

# Keep this list in sync with ``app.py::reset_plot_params``.
MODULE_PREFIXES = (
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
)

GLOBAL_KEYS = {
    "page",
    "plot_type",
    "figure_title",
    "theme",
    "sci_palette",
    "sci_palette_applied",
}

EXCLUDED_KEYS = {
    "last_fig",
    "last_plotly",
    "data",
    "status",
    "status_kind",
    "status_time",
    "help_text",
    "last_plot_key",
    "gallery_query",
    "gallery_category",
    "gallery_shape",
    "home_category_anchor",
}

EXCLUDED_PREFIXES = (
    "export_",
    "fs_",
    "dl_",
    "generate_",
    "reset_",
    "nav_",
    "theme_selector_",
    "gallery_",
    "project_",
)

TRANSIENT_SUFFIXES = (
    "_btn",
    "_button",
    "_editor_state",
)

UPLOAD_CACHE_KEY = "_project_uploaded_files"
RESTORED_FILES_KEY = "_project_restored_files"
SAMPLE_OVERRIDES_KEY = "_project_sample_paths"
TMPDIR_KEY = "_project_tmpdir"
BUNDLE_KEY = "_project_bundle_bytes"
BUNDLE_NAME_KEY = "_project_bundle_name"
BUNDLE_SIG_KEY = "_project_bundle_signature"
BUNDLE_MODULE_KEY = "_project_bundle_module"

_VALUE_TYPE_KEY = "__bioplot_type__"
_UNSUPPORTED = object()


class ProjectFile:
    """Small in-memory stand-in for ``streamlit.runtime.UploadedFile``."""

    def __init__(self, name: str, data: bytes, file_type: str | None = None) -> None:
        self.name = name
        self.type = file_type or "application/octet-stream"
        self.size = len(data)
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            pos = offset
        elif whence == 1:
            pos = self._pos + offset
        elif whence == 2:
            pos = len(self._data) + offset
        else:
            raise ValueError(f"unsupported whence: {whence}")
        self._pos = max(0, min(len(self._data), pos))
        return self._pos

    def tell(self) -> int:
        return self._pos

    def getvalue(self) -> bytes:
        return self._data

    def __len__(self) -> int:
        return len(self._data)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _suffix(name: str | None) -> str:
    suffix = Path(str(name or "")).suffix.lower()
    return suffix if suffix else ".csv"


def _safe_name(value: Any, fallback: str = "item") -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or fallback)).strip("._")
    return text or fallback


def _jsonable(value: Any) -> Any:
    """Convert common widget values to JSON-safe primitives."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    if value is pd.NA or value is pd.NaT:
        return None
    try:
        if pd.isna(value) is True:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, pd.DataFrame):
        rows: list[list[Any]] = []
        for row in value.itertuples(index=False, name=None):
            converted_row: list[Any] = []
            for cell in row:
                converted = _jsonable(cell)
                converted_row.append(None if converted is _UNSUPPORTED else converted)
            rows.append(converted_row)
        return {
            _VALUE_TYPE_KEY: "dataframe",
            "columns": [str(column) for column in value.columns],
            "rows": rows,
        }
    if isinstance(value, pd.Series):
        items = []
        for item in value.tolist():
            converted = _jsonable(item)
            items.append(None if converted is _UNSUPPORTED else converted)
        return {
            _VALUE_TYPE_KEY: "series",
            "name": str(value.name) if value.name is not None else None,
            "data": items,
        }
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            converted = _jsonable(item)
            if converted is not _UNSUPPORTED:
                items.append(converted)
        return items
    if isinstance(value, dict):
        items = {}
        for key, item in value.items():
            converted = _jsonable(item)
            if converted is not _UNSUPPORTED:
                items[str(key)] = converted
        return items
    if isinstance(value, set):
        return _jsonable(sorted(value, key=str))
    return _UNSUPPORTED


def _decode_value(value: Any) -> Any:
    """Reverse :func:`_jsonable` for table/series values stored in a bundle."""
    if isinstance(value, dict):
        kind = value.get(_VALUE_TYPE_KEY)
        if kind == "dataframe":
            columns = value.get("columns")
            rows = value.get("rows")
            if not isinstance(columns, list) or not isinstance(rows, list):
                return pd.DataFrame()
            safe_rows = [row if isinstance(row, list) else [row] for row in rows]
            return pd.DataFrame(safe_rows, columns=[str(column) for column in columns])
        if kind == "series":
            items = value.get("data")
            if not isinstance(items, list):
                items = []
            return pd.Series(items, name=value.get("name"))
        return {key: _decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    return value


def _state_keys(session_state: Mapping[str, Any]) -> list[str]:
    """Return keys for both real Streamlit state and AppTest's SafeSessionState."""
    filtered = getattr(session_state, "filtered_state", None)
    if isinstance(filtered, Mapping):
        return [str(key) for key in filtered.keys()]
    try:
        return [str(key) for key in session_state.keys()]
    except Exception:
        return []


def _state_get(session_state: Mapping[str, Any], key: str, default: Any = None) -> Any:
    filtered = getattr(session_state, "filtered_state", None)
    if isinstance(filtered, Mapping):
        return filtered.get(key, default)
    try:
        return session_state.get(key, default)
    except Exception:
        try:
            return session_state[key]
        except Exception:
            return default


def collect_params(session_state: Mapping[str, Any]) -> dict[str, Any]:
    """Collect module widget values, excluding transient/UI-only state."""
    params: dict[str, Any] = {}
    for key in _state_keys(session_state):
        if not isinstance(key, str):
            continue
        if key in GLOBAL_KEYS or key in EXCLUDED_KEYS:
            continue
        if key.startswith("_") or key.startswith(EXCLUDED_PREFIXES):
            continue
        if key.endswith(TRANSIENT_SUFFIXES):
            continue
        if not key.startswith(MODULE_PREFIXES):
            continue
        converted = _jsonable(session_state[key])
        if converted is not _UNSUPPORTED:
            params[key] = converted
    return params


def _read_upload_bytes(uploaded: Any) -> bytes:
    if hasattr(uploaded, "getvalue"):
        return uploaded.getvalue()
    if hasattr(uploaded, "read"):
        data = uploaded.read()
        try:
            uploaded.seek(0)
        except Exception:
            pass
        return data
    raise TypeError("不支持的文件对象")


def _record_upload(key: str, uploaded: Any, session_state: Mapping[str, Any]) -> None:
    data = _read_upload_bytes(uploaded)
    entry = {
        "key": key,
        "module": _state_get(session_state, "plot_type"),
        "name": getattr(uploaded, "name", f"{key}.csv"),
        "type": getattr(uploaded, "type", None),
        "size": len(data),
        "sha256": _sha256(data),
        "bytes": data,
    }
    cache = dict(_state_get(session_state, UPLOAD_CACHE_KEY) or {})
    cache[key] = entry
    session_state[UPLOAD_CACHE_KEY] = cache


def _forget_upload(key: str, session_state: Mapping[str, Any]) -> None:
    cache = dict(_state_get(session_state, UPLOAD_CACHE_KEY) or {})
    if key in cache:
        del cache[key]
        session_state[UPLOAD_CACHE_KEY] = cache


def install_project_uploader() -> None:
    """Wrap ``st.file_uploader`` so restored project files behave like uploads."""
    if getattr(st, "_bioplotter_project_uploader_installed", False):
        return

    original = st.file_uploader

    def wrapper(*args: Any, key: str | None = None, **kwargs: Any):
        uploaded = original(*args, key=key, **kwargs)
        if not key or key.startswith("project_"):
            return uploaded

        if uploaded is not None:
            if not isinstance(uploaded, (list, tuple)):
                _record_upload(key, uploaded, st.session_state)
            return uploaded

        restored = (_state_get(st.session_state, RESTORED_FILES_KEY) or {}).get(key)
        if restored:
            return ProjectFile(
                restored.get("name") or f"{key}.csv",
                restored["bytes"],
                restored.get("type"),
            )
        _forget_upload(key, st.session_state)
        return None

    wrapper.__wrapped__ = original  # type: ignore[attr-defined]
    st.file_uploader = wrapper

    # Some modules read ``st.session_state.get(uploader_key)`` directly instead
    # of using the return value of ``st.file_uploader``.  Streamlit marks this
    # widget key read-only, so we transparently answer with the restored file
    # while the widget itself has no new upload.
    try:
        from streamlit.runtime.state.session_state_proxy import SessionStateProxy

        original_getitem = SessionStateProxy.__getitem__

        def project_getitem(self, key):
            value = original_getitem(self, key)
            if value is None:
                restored = (_state_get(self, RESTORED_FILES_KEY) or {}).get(str(key))
                if restored and restored.get("bytes") is not None:
                    return ProjectFile(
                        restored.get("name") or f"{key}.csv",
                        restored["bytes"],
                        restored.get("type"),
                    )
            return value

        SessionStateProxy.__getitem__ = project_getitem
    except Exception:
        pass

    st._bioplotter_project_uploader_installed = True


def collect_upload_entries(module_name: str, session_state: Mapping[str, Any]) -> dict[str, dict]:
    uploads: dict[str, dict] = {}
    for key, entry in (_state_get(session_state, UPLOAD_CACHE_KEY) or {}).items():
        if entry.get("module") == module_name and entry.get("bytes") is not None:
            uploads[key] = entry
    for key, entry in (_state_get(session_state, RESTORED_FILES_KEY) or {}).items():
        if key in uploads:
            continue
        if entry.get("module") == module_name and entry.get("bytes") is not None:
            uploads[key] = entry
    return uploads


def project_signature(module_name: str, session_state: Mapping[str, Any]) -> str:
    uploads = collect_upload_entries(module_name, session_state)
    payload = {
        "module": module_name,
        "theme": _state_get(session_state, "theme"),
        "sci_palette": _state_get(session_state, "sci_palette"),
        "figure_title": _state_get(session_state, "figure_title"),
        "figure_style": figure_style_manifest(session_state),
        "params": collect_params(session_state),
        "uploads": [
            (
                key,
                entry.get("name"),
                entry.get("size"),
                entry.get("sha256"),
            )
            for key, entry in sorted(uploads.items())
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def project_filename(module_name: str, session_state: Mapping[str, Any]) -> str:
    title = str(_state_get(session_state, "figure_title") or module_name)
    title = re.sub(r'[\\/:*?"<>|]+', "_", title).strip() or module_name
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return f"{title}_{stamp}.bioplot.zip"


def _unique_arcname(used: set[str], prefix: str, key: str, suffix: str) -> str:
    base = _safe_name(key)
    candidate = f"{prefix}/{base}{suffix}"
    index = 2
    while candidate in used:
        candidate = f"{prefix}/{base}_{index}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def build_project_bundle(
    module_name: str,
    meta: Any,
    session_state: Mapping[str, Any],
) -> tuple[bytes, str, str]:
    """Return ``(zip_bytes, suggested_filename, signature)``."""
    params = collect_params(session_state)
    uploads = collect_upload_entries(module_name, session_state)
    upload_meta: dict[str, dict] = {}
    sample_meta: dict[str, dict] = {}
    used_names: set[str] = set()

    payloads: list[tuple[str, bytes]] = []
    for key, entry in sorted(uploads.items()):
        arcname = _unique_arcname(used_names, "data", key, _suffix(entry.get("name")))
        data = entry["bytes"]
        payloads.append((arcname, data))
        upload_meta[key] = {
            "archive": arcname,
            "name": entry.get("name") or f"{key}.csv",
            "type": entry.get("type"),
            "size": len(data),
            "sha256": _sha256(data),
            "uploaded_module": entry.get("module"),
        }

    for key in SAMPLE_PATHS:
        try:
            path = get_sample_path(key)
        except Exception:
            path = SAMPLE_PATHS[key]
        if not path.exists():
            continue
        arcname = _unique_arcname(used_names, "samples", key, path.suffix.lower() or ".csv")
        data = path.read_bytes()
        payloads.append((arcname, data))
        sample_meta[key] = {
            "archive": arcname,
            "name": path.name,
            "sha256": _sha256(data),
        }

    figure_json: str | None = None
    plotly_fig = _state_get(session_state, "last_plotly")
    if plotly_fig is not None:
        try:
            figure_json = pio.to_json(plotly_fig, pretty=True)
        except Exception:
            figure_json = None

    help_text = str(_state_get(session_state, "help_text") or "").strip()
    theme = _state_get(session_state, "theme")
    if theme not in THEMES:
        theme = "Light"
    palette = _state_get(session_state, "sci_palette")
    if palette not in {"Auto", *SCI_PALETTES.keys()}:
        palette = "Auto"

    manifest = {
        "format": PROJECT_FORMAT,
        "format_version": PROJECT_FORMAT_VERSION,
        "app": {"name": "BioPlotter", "version": APP_VERSION},
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "module": module_name,
        "category": getattr(meta, "category", ""),
        "figure_title": _state_get(session_state, "figure_title") or module_name,
        "theme": theme,
        "sci_palette": palette,
        "figure_style": figure_style_manifest(session_state),
        "params": params,
        "uploads": upload_meta,
        "samples": sample_meta,
        "figure": {"engine": "plotly", "archive": "figure.json"} if figure_json else None,
        "help": {"archive": "help.md"} if help_text else None,
        "status": _state_get(session_state, "status"),
    }

    readme = (
        "BioPlotter 项目包\n"
        "================\n\n"
        f"模块：{module_name}\n"
        f"图形标题：{manifest['figure_title']}\n"
        f"创建时间：{manifest['created_at']}\n"
        f"应用版本：{APP_VERSION}\n\n"
        "此 zip 包含原始数据、示例数据、参数与图形配置。\n"
        "在 BioPlotter 绘图页左侧「项目包」中上传此文件即可恢复。\n"
        "请勿手动修改 manifest.json，否则可能无法载入。\n"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        archive.writestr("README.txt", readme)
        if figure_json:
            archive.writestr("figure.json", figure_json)
        if help_text:
            archive.writestr("help.md", help_text)
        for arcname, data in payloads:
            archive.writestr(arcname, data)

    bundle = buffer.getvalue()
    if len(bundle) > MAX_PROJECT_BYTES:
        raise ValueError("项目包超过 200 MB 限制，请先裁剪数据或拆分为多个项目")

    return bundle, project_filename(module_name, session_state), project_signature(
        module_name, session_state
    )


def _validated_manifest(zip_file: zipfile.ZipFile, valid_modules: Iterable[str]) -> dict:
    try:
        manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
    except KeyError as exc:
        raise ValueError("项目包缺少 manifest.json") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("manifest.json 不是有效 JSON") from exc

    if not isinstance(manifest, dict):
        raise ValueError("manifest.json 结构无效")
    if manifest.get("format") != PROJECT_FORMAT:
        raise ValueError("不是 BioPlotter 项目包")
    try:
        version = int(manifest.get("format_version", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("项目包格式版本无效") from exc
    if version > PROJECT_FORMAT_VERSION:
        raise ValueError("项目包由更新版本的 BioPlotter 创建，请升级后再打开")

    module = manifest.get("module")
    if module not in set(valid_modules):
        raise ValueError(f"项目包中的模块不可用：{module}")
    return manifest


def _safe_archive_member(name: Any) -> str | None:
    if not isinstance(name, str) or not name:
        return None
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        return None
    return name


def restore_project_bundle(
    zip_bytes: bytes,
    session_state: Mapping[str, Any],
    valid_modules: Iterable[str],
) -> dict:
    """Restore a bundle into ``session_state`` and return its manifest."""
    if len(zip_bytes) > MAX_PROJECT_BYTES:
        raise ValueError("项目包超过 200 MB 限制")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        total_size = sum(info.file_size for info in archive.infolist())
        if total_size > MAX_PROJECT_BYTES:
            raise ValueError("项目包解压后超过 200 MB 限制")

        manifest = _validated_manifest(archive, valid_modules)
        module = manifest["module"]
        samples = manifest.get("samples") or {}
        uploads = manifest.get("uploads") or {}
        params = manifest.get("params") or {}
        if not isinstance(samples, dict):
            samples = {}
        if not isinstance(uploads, dict):
            uploads = {}
        if not isinstance(params, dict):
            params = {}

        old_tmpdir = _state_get(session_state, TMPDIR_KEY)
        if old_tmpdir is not None:
            try:
                old_tmpdir.cleanup()
            except Exception:
                pass
        tmpdir = tempfile.TemporaryDirectory(prefix="bioplotter_project_")
        sample_paths: dict[str, str] = {}
        for key, info in samples.items():
            if not isinstance(info, dict):
                continue
            arcname = _safe_archive_member(info.get("archive"))
            if not arcname:
                continue
            try:
                data = archive.read(arcname)
            except KeyError:
                continue
            filename = f"{_safe_name(key)}{Path(arcname).suffix or '.csv'}"
            path = Path(tmpdir.name) / filename
            path.write_bytes(data)
            sample_paths[key] = str(path)

        restored_files: dict[str, dict] = {}
        for key, info in uploads.items():
            if not isinstance(info, dict):
                continue
            arcname = _safe_archive_member(info.get("archive"))
            if not arcname:
                continue
            try:
                data = archive.read(arcname)
            except KeyError:
                continue
            restored_files[key] = {
                "key": key,
                "module": module,
                "name": info.get("name") or f"{key}.csv",
                "type": info.get("type"),
                "size": len(data),
                "sha256": _sha256(data),
                "bytes": data,
            }

    # Remove stale uploads for this module; restored files must win.
    cache = dict(_state_get(session_state, UPLOAD_CACHE_KEY) or {})
    for key in list(cache):
        if cache[key].get("module") == module:
            del cache[key]

    session_state[UPLOAD_CACHE_KEY] = cache
    session_state[RESTORED_FILES_KEY] = restored_files
    session_state[SAMPLE_OVERRIDES_KEY] = sample_paths
    session_state[TMPDIR_KEY] = tmpdir

    for key, value in params.items():
        if isinstance(key, str) and key.startswith(MODULE_PREFIXES):
            try:
                session_state[key] = _decode_value(value)
            except (TypeError, ValueError):
                continue

    theme = manifest.get("theme")
    if theme in THEMES:
        session_state["theme"] = theme
    palette = manifest.get("sci_palette")
    if palette in {"Auto", *SCI_PALETTES.keys()}:
        session_state["sci_palette"] = palette
        session_state["sci_palette_applied"] = palette

    restore_figure_style(manifest.get("figure_style"), session_state)

    session_state["page"] = "plot"
    session_state["plot_type"] = module
    session_state["figure_title"] = manifest.get("figure_title") or module
    session_state["last_plot_key"] = None
    session_state["last_fig"] = None
    session_state["last_plotly"] = None
    session_state["data"] = None
    session_state["status"] = f"已载入项目：{session_state['figure_title']}"
    session_state["status_kind"] = "success"
    session_state["status_time"] = datetime.now().strftime("%H:%M:%S")
    session_state["help_text"] = None
    session_state[BUNDLE_KEY] = None
    session_state[BUNDLE_NAME_KEY] = None
    session_state[BUNDLE_SIG_KEY] = None
    session_state[BUNDLE_MODULE_KEY] = None

    try:
        st.query_params["page"] = "plot"
        st.query_params["plot"] = module
    except Exception:
        pass

    return manifest
