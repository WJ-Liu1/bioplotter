from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import streamlit as st


REQUIRED_EDGE_COLS = ["from", "to", "value"]
REQUIRED_CHORD_COLS = ["from", "to", "value", "color"]
REQUIRED_NODELINK_COLS = ["from", "to", "value", "color"]
REQUIRED_SANKEY_LINK_COLS = ["source", "target", "value", "colorlink"]
REQUIRED_SANKEY_NODE_COLS = ["nodes", "colornode"]


def _read_bytes(uploaded) -> bytes:
    if uploaded is None:
        raise ValueError("未提供文件")
    if hasattr(uploaded, "read"):
        data = uploaded.read()
        try:
            uploaded.seek(0)
        except Exception:
            pass
        return data
    if isinstance(uploaded, (str, Path)):
        return Path(uploaded).read_bytes()
    raise TypeError("不支持的文件对象")


def _detect_sep(name: str) -> str | None:
    name = name.lower()
    if name.endswith(".tsv") or name.endswith(".txt"):
        return None
    return ","


def _parse_table_bytes(data: bytes, suffix: str, sep: str | None) -> pd.DataFrame:
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(io.BytesIO(data))
    return pd.read_csv(io.BytesIO(data), sep=sep, engine="python")


@st.cache_data(show_spinner=False, max_entries=64)
def _read_table_from_path(path_str: str, mtime: float, suffix: str, sep: str | None) -> pd.DataFrame:
    """磁盘文件读取结果缓存：mtime 变化即失效，返回副本避免上层改写污染缓存。"""
    return _parse_table_bytes(Path(path_str).read_bytes(), suffix, sep)


def read_table(uploaded, name: str | None = None) -> pd.DataFrame:
    if isinstance(uploaded, (str, Path)):
        path = Path(uploaded)
        return _read_table_from_path(
            str(path),
            path.stat().st_mtime,
            path.suffix.lower(),
            _detect_sep(path.name),
        )

    data = _read_bytes(uploaded)
    fname = name or getattr(uploaded, "name", "uploaded.csv")
    suffix = Path(fname).suffix.lower()
    return _parse_table_bytes(data, suffix, _detect_sep(fname))


def read_text_table_from_str(text: str) -> pd.DataFrame:
    if not text.strip():
        raise ValueError("粘贴内容为空")
    return pd.read_csv(io.StringIO(text), sep="\t", engine="python")


def normalize_edge_df(df: pd.DataFrame, cols: Iterable[str] = REQUIRED_EDGE_COLS) -> pd.DataFrame:
    cols = list(cols)
    if not all(c in df.columns for c in cols):
        raise ValueError(f"数据必须包含列: {', '.join(cols)}")
    out = df.copy()
    out[cols[0]] = out[cols[0]].astype(str).str.strip()
    out[cols[1]] = out[cols[1]].astype(str).str.strip()
    out[cols[2]] = pd.to_numeric(out[cols[2]], errors="coerce")
    out = out[(out[cols[0]] != "") & (out[cols[1]] != "") & out[cols[2]].notna()]
    return out


def read_matrix_like(uploaded, name: str | None = None) -> pd.DataFrame:
    df = read_table(uploaded, name=name)
    if df.shape[1] < 2:
        raise ValueError("矩阵数据至少需要 2 列")
    rn = df.iloc[:, 0].astype(str).str.strip().replace("", np.nan).fillna("NA_row")
    mat = df.iloc[:, 1:].copy()
    mat.index = rn
    mat.columns = [str(c).strip() if str(c).strip() else f"col_{i+1}" for i, c in enumerate(mat.columns)]
    for c in mat.columns:
        mat[c] = pd.to_numeric(mat[c], errors="coerce")
    return mat.fillna(0)


def matrix_to_edgelist(mat: pd.DataFrame) -> pd.DataFrame:
    long = mat.stack(dropna=False).reset_index()
    long.columns = ["from", "to", "value"]
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long[long["value"].notna() & (long["value"] > 0) & (long["from"] != long["to"])]
    return long


def edgelist_to_square_matrix(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_edge_df(df)
    nodes = sorted(set(df["from"]).union(df["to"]))
    mat = pd.DataFrame(0.0, index=nodes, columns=nodes)
    for _, row in df.iterrows():
        mat.loc[row["from"], row["to"]] = float(row["value"])
    return mat


def read_arc_input(uploaded, name: str | None = None) -> tuple[str, pd.DataFrame]:
    df = read_table(uploaded, name=name)
    lower_cols = [str(c).strip().lower() for c in df.columns]
    if all(c in lower_cols for c in REQUIRED_EDGE_COLS):
        tmp = df.copy()
        tmp.columns = lower_cols
        return "edgelist", edgelist_to_square_matrix(tmp[["from", "to", "value"]])
    return "matrix", read_matrix_like(uploaded, name=name)


def winsorize_series(s: pd.Series, p: float = 0.0) -> pd.Series:
    if p <= 0:
        return s
    lo = s.quantile(p)
    hi = s.quantile(1 - p)
    return s.clip(lo, hi)
