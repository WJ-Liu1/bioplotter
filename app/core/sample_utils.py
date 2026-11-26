from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Iterable

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = PROJECT_ROOT / "sample_data"

SAMPLE_PATHS = {
    "arc": SAMPLE_DIR / "arc_edgelist.csv",
    "arc_nodes": SAMPLE_DIR / "arc_nodes.csv",
    "beeswarm": SAMPLE_DIR / "beeswarm_sample.txt",
    "chord": SAMPLE_DIR / "chord_sample.csv",
    "go_bar": SAMPLE_DIR / "go_bar_sample.txt",
    "go_bubble": SAMPLE_DIR / "go_bubble_sample.txt",
    "heb": SAMPLE_DIR / "heb_sample.csv",
    "mantel_spec": SAMPLE_DIR / "mantel_spec_sample.csv",
    "mantel_env": SAMPLE_DIR / "mantel_env_sample.csv",
    "nodelink": SAMPLE_DIR / "nodelink_sample.csv",
    "pirate_cont": SAMPLE_DIR / "pirate_continuous_sample.csv",
    "pirate_cat": SAMPLE_DIR / "pirate_categorical_sample.csv",
    "raincloud": SAMPLE_DIR / "raincloud_sample.txt",
    "sankey_links": SAMPLE_DIR / "sankey_links.txt",
    "sankey_nodes": SAMPLE_DIR / "sankey_nodes.txt",
    "scaboxden": SAMPLE_DIR / "scaboxden_sample.txt",
    "splitviolin": SAMPLE_DIR / "splitviolin_sample.txt",
    # 原生融合模块（5 个外部应用重写）
    "bubble_country": SAMPLE_DIR / "bubble_country.csv",
    "bubble_aqi": SAMPLE_DIR / "bubble_aqi.csv",
    "gmp_matrix": SAMPLE_DIR / "gmp_matrix.csv",
    "circleviz_cis_ctrl": SAMPLE_DIR / "circleviz_cis_ctrl.csv",
    "circularbar_genes": SAMPLE_DIR / "circularbar_genes.csv",
    "genvar_feature": SAMPLE_DIR / "genvar_feature.csv",
    "genvar_snp_upper": SAMPLE_DIR / "genvar_snp_upper.csv",
    "genvar_snp_lower": SAMPLE_DIR / "genvar_snp_lower.csv",
    # 新增 6 个生信模块
    "volcano_degs": SAMPLE_DIR / "volcano_degs.csv",
    "pca_samples": SAMPLE_DIR / "pca_samples.csv",
    "heatmap_expression": SAMPLE_DIR / "heatmap_expression.csv",
    "upset_genesets": SAMPLE_DIR / "upset_genesets.csv",
    "km_survival": SAMPLE_DIR / "km_survival.csv",
    "manhattan_gwas": SAMPLE_DIR / "manhattan_gwas.csv",
    # 双树比较
    "pt_tree1": SAMPLE_DIR / "pt_tree1.nwk",
    "pt_tree2": SAMPLE_DIR / "pt_tree2.nwk",
    "pt_pairing": SAMPLE_DIR / "pt_pairing.csv",
    "pt_groups": SAMPLE_DIR / "pt_groups.csv",
}


def get_sample_path(key: str) -> Path:
    try:
        override = (st.session_state.get("_project_sample_paths") or {}).get(key)
    except Exception:
        override = None
    if override:
        candidate = Path(override)
        if candidate.exists():
            return candidate

    path = SAMPLE_PATHS[key]
    if not path.exists():
        raise FileNotFoundError(f"Sample data file not found: {path}")
    return path


def sample_bytes(key: str) -> bytes:
    return get_sample_path(key).read_bytes()


def sample_text(key: str, encoding: str = "utf-8") -> str:
    return get_sample_path(key).read_text(encoding=encoding)


def sample_zip_bytes(keys: Iterable[str]) -> bytes:
    """Bundle one or more sample files into a single zip download."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for key in keys:
            path = get_sample_path(key)
            archive.write(path, arcname=path.name)
    buffer.seek(0)
    return buffer.getvalue()


def _rel_path_text(keys: Iterable[str]) -> str:
    rels = []
    for key in keys:
        path = get_sample_path(key)
        try:
            rels.append(str(path.relative_to(PROJECT_ROOT)))
        except ValueError:
            rels.append(path.name)
    return "; ".join(rels)


def sample_loader_control(
    use_key: str,
    sample_keys: str | list[str],
    button_key: str,
    *,
    label: str = "载入示例数据并绘图",
    checkbox_label: str = "使用示例数据",
    extra_state: dict | None = None,
) -> None:
    keys = [sample_keys] if isinstance(sample_keys, str) else list(sample_keys)

    if st.button(label, key=button_key, width="stretch"):
        st.session_state[use_key] = True
        if extra_state:
            for state_key, state_value in extra_state.items():
                st.session_state[state_key] = state_value

    # Keep the default in session state only once, so the widget owns the value afterwards.
    if use_key not in st.session_state:
        st.session_state[use_key] = True
    st.checkbox(checkbox_label, key=use_key)
    st.caption(f"示例数据路径：{_rel_path_text(keys)}")
