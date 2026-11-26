"""Generate the sample datasets used by the 5 migrated native modules.

Run from the project root::

    .venv\\Scripts\\python.exe scripts/generate_sample_data.py

This script is **never imported at runtime** (architecture §4.2).  It only
depends on ``numpy`` / ``pandas`` and resolves paths through
``app/core/sample_utils.SAMPLE_DIR``.

Spec sources
------------
* ``bubble_country.csv`` / ``bubble_aqi.csv`` — verbatim copy of the original
  Vue app (``static/apps/bubbleviz/data1.csv`` / ``data2.csv``).
* ``gmp_matrix.csv`` — long-table expansion of the original
  ``VIRUS_MATRIX_DATA``: **22 viruses x 8 Seg columns = 176 rows**, 6 groups.
* ``circleviz_cis_ctrl.csv`` — exact 51-row sample from
  ``shiny_apps/circleviz/app.R`` (``data_ex``).
* ``circularbar_genes.csv`` — ``default_rng(42)`` replica of
  ``shiny_apps/circularbar/app.R`` ``generate_random_data()``.
* ``genvar_*.csv`` — the three built-in tables from ``shiny_apps/genvar/app.R``
  with an explicit ``name,start,end`` / ``name,position,score`` header.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.sample_utils import SAMPLE_DIR  # noqa: E402

STATIC_BUBBLE = PROJECT_ROOT / "static" / "apps" / "bubbleviz"

# --------------------------------------------------------------------------
# 1. BubbleViz: copy the two original CSV files verbatim
# --------------------------------------------------------------------------
BUBBLE_FILES = {
    "data1.csv": "bubble_country.csv",
    "data2.csv": "bubble_aqi.csv",
}


def copy_bubble_samples() -> None:
    for source_name, target_name in BUBBLE_FILES.items():
        source = STATIC_BUBBLE / source_name
        target = SAMPLE_DIR / target_name
        if not source.exists():
            raise FileNotFoundError(f"missing original bubble sample: {source}")
        shutil.copyfile(source, target)
        rows = sum(1 for _ in target.open(encoding="utf-8")) - 1
        print(f"[bubble] {target.name}: {rows} data rows")


# --------------------------------------------------------------------------
# 2. Grouped Matrix Plotting: 22 viruses x 8 columns = 176 long rows
# --------------------------------------------------------------------------
GMP_COLUMNS = [f"Seg{i}" for i in range(1, 9)]

# Original ``VIRUS_MATRIX_DATA`` (22 x 8) extracted from
# static/apps/gmp/assets/index-*.js.
GMP_MATRIX = [
    ["Known", "Novel_Not_Annotated", "Novel_Annotated", "Known", "Novel_Annotated", "Known", "Novel_Not_Annotated", "Novel_Annotated"],
    ["Novel_Annotated", "Known", "", "Known", "Known", "Novel_Not_Annotated", "Novel_Annotated", "Known"],
    ["", "Novel_Annotated", "Novel_Not_Annotated", "Novel_Annotated", "Novel_Annotated", "Novel_Annotated", "Novel_Annotated", "Known"],
    ["Novel_Not_Annotated", "", "Novel_Not_Annotated", "Known", "Novel_Annotated", "Known", "", "Novel_Annotated"],
    ["Novel_Annotated", "Known", "", "Novel_Not_Annotated", "Novel_Annotated", "Novel_Annotated", "Novel_Annotated", "Known"],
    ["Known", "Known", "Novel_Not_Annotated", "Novel_Annotated", "Known", "Novel_Annotated", "", "Novel_Annotated"],
    ["Known", "Novel_Annotated", "Known", "Novel_Annotated", "Known", "Novel_Not_Annotated", "", "Known"],
    ["Novel_Not_Annotated", "Known", "", "Novel_Annotated", "Novel_Annotated", "Novel_Not_Annotated", "Novel_Not_Annotated", ""],
    ["Novel_Annotated", "Known", "", "Novel_Not_Annotated", "Known", "Novel_Annotated", "Known", "Novel_Annotated"],
    ["Known", "Novel_Annotated", "Novel_Annotated", "Known", "Novel_Annotated", "Known", "", "Novel_Not_Annotated"],
    ["Novel_Not_Annotated", "Novel_Annotated", "Known", "", "", "Known", "Novel_Not_Annotated", "Known"],
    ["", "Known", "Known", "Novel_Not_Annotated", "Novel_Not_Annotated", "Novel_Annotated", "Known", "Novel_Annotated"],
    ["Novel_Not_Annotated", "Novel_Annotated", "Known", "Novel_Not_Annotated", "Novel_Not_Annotated", "", "Known", ""],
    ["", "Known", "Novel_Annotated", "Novel_Not_Annotated", "Novel_Not_Annotated", "Known", "", "Novel_Annotated"],
    ["Known", "", "Novel_Annotated", "Novel_Annotated", "Known", "Novel_Annotated", "", "Novel_Not_Annotated"],
    ["", "Novel_Not_Annotated", "", "Known", "Novel_Annotated", "Novel_Not_Annotated", "Novel_Annotated", "Known"],
    ["Novel_Annotated", "", "Known", "Novel_Annotated", "", "Novel_Not_Annotated", "Known", "Novel_Not_Annotated"],
    ["", "Novel_Annotated", "Novel_Not_Annotated", "Known", "Known", "Novel_Annotated", "", ""],
    ["Known", "Known", "Novel_Not_Annotated", "Novel_Annotated", "", "", "Known", "Novel_Annotated"],
    ["Novel_Not_Annotated", "", "", "Known", "Novel_Not_Annotated", "Known", "", ""],
    ["Novel_Annotated", "Known", "Novel_Annotated", "Novel_Not_Annotated", "", "Novel_Not_Annotated", "Known", ""],
    ["Novel_Annotated", "Known", "", "", "Known", "", "Novel_Annotated", "Novel_Not_Annotated"],
]

# ``Y_AXIS_GROUP_DATA`` order (6 groups / 22 viruses).  The original bundle
# lists "Virus 9" twice (Group2 + Group5); the second occurrence is renamed to
# "Virus 11" so that every row entity stays unique —— 6 组 / 22 virus 定稿。
GMP_GROUPS = [
    ("Group1", ["Virus 24", "Virus 4", "Virus 8"]),
    ("Group2", ["Virus 1", "Virus 9"]),
    ("Group3", ["Virus 16", "Virus 2", "Virus 3", "Virus 14", "Virus 12"]),
    ("Group4", ["Virus 5"]),
    ("Group5", ["Virus 10", "Virus 17", "Virus 11", "Virus 6"]),
    ("Group6", ["Virus 7", "Virus 13", "Virus 15", "Virus 19", "Virus 22", "Virus 26", "Virus 20"]),
]


def build_gmp_sample() -> None:
    row_names: list[str] = []
    row_groups: list[str] = []
    for group, children in GMP_GROUPS:
        for child in children:
            row_names.append(child)
            row_groups.append(group)

    if len(row_names) != len(GMP_MATRIX):
        raise ValueError(
            f"gmp group/virus count ({len(row_names)}) does not match matrix rows ({len(GMP_MATRIX)})"
        )

    records: list[dict[str, str]] = []
    for row_name, group, row_values in zip(row_names, row_groups, GMP_MATRIX):
        for column, category in zip(GMP_COLUMNS, row_values):
            records.append({"row": row_name, "group": group, "column": column, "category": category})

    frame = pd.DataFrame(records)
    target = SAMPLE_DIR / "gmp_matrix.csv"
    frame.to_csv(target, index=False, encoding="utf-8", lineterminator="\n")
    print(
        f"[gmp] {target.name}: {frame.shape[0]} rows, "
        f"{len(row_names)} viruses x {len(GMP_COLUMNS)} columns, "
        f"{frame['group'].nunique()} groups"
    )


# --------------------------------------------------------------------------
# 3. CircleViz: exact 51-row sample from shiny_apps/circleviz/app.R
# --------------------------------------------------------------------------
CIRCLE_NAMES = [f"Cis-{i}" for i in range(1, 43)] + [f"Ctrl-{i}" for i in range(1, 10)]

CIRCLE_DATA1 = [
    "d", "c", "", "", "c", "a", "", "b", "c", "",
    "c", "c", "b", "d", "c", "", "c", "", "b", "b",
    "a", "b", "d", "b", "d", "c", "d", "a", "", "c",
    "d", "a", "d", "d", "a", "a", "d", "d", "a", "d",
    "", "c",
    "", "c", "b", "c", "d", "c", "b", "d", "c",
]

CIRCLE_DATA2 = [
    9, 15, 2, 10, 1, 10, 2, 10, 14, 6, 7, 15, 19, 8, 15, 14, 4, 16, 18, 11,
    7, 5, 20, 7, 7, 5, 14, 3, 9, 10, 5, 19, 5, 9, 18, 15, 7, 5, 19, 9,
    7, 16,
    3, 10, 15, 19, 19, 8, 6, 1, 9,
]

CIRCLE_DATA3 = [
    12, 9, 4, 5, 6, 3, 1, 11, 5, 19, 16, 14, 8, 10, 12, 15, 16, 16, 1, 3,
    4, 11, 10, 5, 15, 2, 6, 10, 1, 16, 11, 11, 3, 1, 8, 13, 8, 3, 3, 1,
    7, 10,
    20, 11, 2, 3, 12, 13, 12, 1, 6,
]

CIRCLE_DATA4 = [
    2, 11, 4, 5, 1, 6, 8, 19, 2, 11, 11, 7, 18, 10, 3, 17, 15, 18, 14, 13,
    13, 3, 3, 2, 20, 18, 5, 14, 5, 1, 9, 2, 10, 18, 2, 9, 6, 10, 12, 18,
    11, 17,
    20, 10, 14, 3, 7, 6, 2, 10, 7,
]


def build_circle_sample() -> None:
    lengths = {
        "name": len(CIRCLE_NAMES),
        "data1": len(CIRCLE_DATA1),
        "data2": len(CIRCLE_DATA2),
        "data3": len(CIRCLE_DATA3),
        "data4": len(CIRCLE_DATA4),
    }
    if len(set(lengths.values())) != 1:
        raise ValueError(f"circleviz sample length mismatch: {lengths}")

    frame = pd.DataFrame(
        {
            "id": list(range(1, len(CIRCLE_NAMES) + 1)),
            "name": CIRCLE_NAMES,
            "data1": CIRCLE_DATA1,
            "data2": CIRCLE_DATA2,
            "data3": CIRCLE_DATA3,
            "data4": CIRCLE_DATA4,
        }
    )
    target = SAMPLE_DIR / "circleviz_cis_ctrl.csv"
    frame.to_csv(target, index=False, encoding="utf-8", lineterminator="\n")
    print(f"[circleviz] {target.name}: {frame.shape[0]} rows x {frame.shape[1]} columns")


# --------------------------------------------------------------------------
# 4. CircularBarPlot: 36 genes x 3 groups, ~10% NA
# --------------------------------------------------------------------------
CBAR_GENES = 36
CBAR_GROUPS = ["A", "B", "C"]
CBAR_RANDOM_SEED = 42


def _stars_from_p(p_value: float) -> int:
    if p_value is None or (isinstance(p_value, float) and np.isnan(p_value)):
        return 0
    if p_value < 0.001:
        return 3
    if p_value < 0.01:
        return 2
    if p_value < 0.05:
        return 1
    return 0


def build_circularbar_sample() -> None:
    rng = np.random.default_rng(CBAR_RANDOM_SEED)

    per_group = CBAR_GENES // len(CBAR_GROUPS)
    types: list[str] = []
    for group in CBAR_GROUPS[:-1]:
        types.extend([group] * per_group)
    types.extend([CBAR_GROUPS[-1]] * (CBAR_GENES - len(types)))

    # The original draws group C from a slightly tighter range.
    values: np.ndarray = np.empty(CBAR_GENES, dtype=float)
    for index, group in enumerate(types):
        low, high = (-0.6, 0.6) if group == "C" else (-0.8, 0.8)
        values[index] = rng.uniform(low, high)
    pvalues = rng.uniform(0.0, 0.2, CBAR_GENES)

    n_na = max(1, int(np.floor(CBAR_GENES * 0.1)))
    na_index = set(rng.choice(CBAR_GENES, size=n_na, replace=False).tolist())

    rows = []
    for i in range(CBAR_GENES):
        if i in na_index:
            rows.append({"Name": f"G{i + 1}", "type": types[i], "data": np.nan, "p_value": np.nan, "num_stars": 0})
        else:
            pv = round(float(pvalues[i]), 4)
            rows.append(
                {
                    "Name": f"G{i + 1}",
                    "type": types[i],
                    "data": round(float(values[i]), 4),
                    "p_value": pv,
                    "num_stars": _stars_from_p(pv),
                }
            )

    frame = pd.DataFrame(rows, columns=["Name", "type", "data", "p_value", "num_stars"])
    target = SAMPLE_DIR / "circularbar_genes.csv"
    frame.to_csv(target, index=False, encoding="utf-8", lineterminator="\n", na_rep="")
    print(
        f"[circularbar] {target.name}: {frame.shape[0]} rows, "
        f"{frame['type'].nunique()} groups, {n_na} NA values"
    )


# --------------------------------------------------------------------------
# 5. Genomic Variation Viewer: three tables straight from the R app
# --------------------------------------------------------------------------
GVAR_FEATURES = [
    ("block1", 1, 80),
    ("block2", 261, 360),
    ("block3", 501, 830),
]

# shiny_apps/genvar/app.R: snp10/102/106/108/400/410/420/600/700/805, score = 1
GVAR_SNP_UPPER = [(f"snp{pos}", pos, 1) for pos in (10, 102, 106, 108, 400, 410, 420, 600, 700, 805)]

# shiny_apps/genvar/app.R: snp206/208/210/510/520/630/680/682/688, score = 1
GVAR_SNP_LOWER = [(f"snp{pos}", pos, 1) for pos in (206, 208, 210, 510, 520, 630, 680, 682, 688)]


def build_genvar_samples() -> None:
    targets = [
        ("genvar_feature.csv", ["name", "start", "end"], GVAR_FEATURES),
        ("genvar_snp_upper.csv", ["name", "position", "score"], GVAR_SNP_UPPER),
        ("genvar_snp_lower.csv", ["name", "position", "score"], GVAR_SNP_LOWER),
    ]
    for filename, columns, records in targets:
        frame = pd.DataFrame(records, columns=columns)
        target = SAMPLE_DIR / filename
        frame.to_csv(target, index=False, encoding="utf-8", lineterminator="\n")
        print(f"[genvar] {target.name}: {frame.shape[0]} rows")


# --------------------------------------------------------------------------
# 6. Volcano Plot: 3000 DEGs (architecture §4.2 #9, seed 42)
# --------------------------------------------------------------------------
VOLCANO_SEED = 42
VOLCANO_UP = 1500
VOLCANO_DOWN = 1200
VOLCANO_NS = 300


def build_volcano_sample() -> None:
    rng = np.random.default_rng(VOLCANO_SEED)

    up_fc = rng.normal(1.8, 0.9, VOLCANO_UP)
    down_fc = rng.normal(-1.6, 0.8, VOLCANO_DOWN)
    ns_fc = rng.normal(0.0, 0.3, VOLCANO_NS)
    log2fc = np.concatenate([up_fc, down_fc, ns_fc])

    # p correlates with |log2FC|: log10(p) = -(|fc| * 1.2 + |N(0, 0.6)|)
    log10_p = -np.abs(log2fc) * 1.2 - np.abs(rng.normal(0.0, 0.6, log2fc.size))
    pvalue = np.clip(10.0**log10_p, 1e-15, 1.0)

    total = log2fc.size
    order = np.argsort(pvalue)
    ranks = np.empty(total, dtype=float)
    ranks[order] = np.arange(1, total + 1)
    padj = np.clip(pvalue * total / ranks, 0.0, 1.0)

    frame = pd.DataFrame(
        {
            "gene": [f"GENE{index:04d}" for index in range(1, total + 1)],
            "log2FC": np.round(log2fc, 4),
            "pvalue": pvalue,
            "padj": np.round(padj, 6),
        }
    )
    target = SAMPLE_DIR / "volcano_degs.csv"
    frame.to_csv(target, index=False, encoding="utf-8", lineterminator="\n", float_format="%.6g")
    n_up = int((frame["log2FC"] > 1.0).sum())
    print(f"[volcano] {target.name}: {frame.shape[0]} rows; |log2FC|>1: {n_up}")


# --------------------------------------------------------------------------
# 7. PCA: 3 groups x 10 samples x 500 features (architecture §4.2 #10, seed 7)
# --------------------------------------------------------------------------
PCA_SEED = 7
PCA_SAMPLES = 30
PCA_FEATURES = 500
PCA_GROUPS = ("Ctrl", "Treat1", "Treat2")


def build_pca_sample() -> None:
    rng = np.random.default_rng(PCA_SEED)

    matrix = rng.normal(0.0, 1.0, (PCA_SAMPLES, PCA_FEATURES))
    groups: list[str] = []
    # A pure N(0, 1.6) group *noise* cannot separate clusters in PCA, so each
    # group also gets a distinct mean shift on the first 50 features (this is
    # what makes PC1/PC2 show three clear clouds).
    for group_index, group in enumerate(PCA_GROUPS):
        rows = slice(group_index * 10, (group_index + 1) * 10)
        shift = (group_index - 1) * 2.0
        matrix[rows, :50] += shift + rng.normal(0.0, 0.8, (10, 50))
        groups.extend([group] * 10)

    frame = pd.DataFrame(matrix, columns=[f"F{index:03d}" for index in range(1, PCA_FEATURES + 1)])
    frame.insert(0, "group", groups)
    frame.insert(0, "sample", [f"S{index:02d}" for index in range(1, PCA_SAMPLES + 1)])
    target = SAMPLE_DIR / "pca_samples.csv"
    frame.to_csv(target, index=False, encoding="utf-8", lineterminator="\n", float_format="%.4f")
    print(f"[pca] {target.name}: {frame.shape[0]} rows x {frame.shape[1]} cols")


# --------------------------------------------------------------------------
# 8. Heatmap: 200 genes x 20 samples, block expression (architecture §4.2 #11)
# --------------------------------------------------------------------------
HEATMAP_SEED = 11
HEATMAP_GENES = 200
HEATMAP_SAMPLES = 20
HEATMAP_MODULES = ("M1", "M2", "M3", "M4")


def build_heatmap_sample() -> None:
    rng = np.random.default_rng(HEATMAP_SEED)

    genes_per_module = HEATMAP_GENES // len(HEATMAP_MODULES)
    samples_per_module = HEATMAP_SAMPLES // len(HEATMAP_MODULES)

    matrix = rng.normal(0.0, 0.35, (HEATMAP_GENES, HEATMAP_SAMPLES))
    for module_index in range(len(HEATMAP_MODULES)):
        gene_rows = slice(module_index * genes_per_module, (module_index + 1) * genes_per_module)
        sample_cols = slice(module_index * samples_per_module, (module_index + 1) * samples_per_module)
        matrix[gene_rows, sample_cols] += 2.0

    gene_groups = [
        HEATMAP_MODULES[min(index // genes_per_module, len(HEATMAP_MODULES) - 1)]
        for index in range(HEATMAP_GENES)
    ]
    frame = pd.DataFrame(
        matrix,
        columns=[f"S{index:02d}" for index in range(1, HEATMAP_SAMPLES + 1)],
    )
    frame.insert(0, "group", gene_groups)
    frame.insert(0, "gene", [f"G{index:04d}" for index in range(1, HEATMAP_GENES + 1)])
    target = SAMPLE_DIR / "heatmap_expression.csv"
    frame.to_csv(target, index=False, encoding="utf-8", lineterminator="\n", float_format="%.3f")
    print(f"[heatmap] {target.name}: {frame.shape[0]} rows x {frame.shape[1]} cols")


# --------------------------------------------------------------------------
# 9. UpSet: 5 sets / nested membership (architecture §4.2 #12)
# --------------------------------------------------------------------------
UPSET_SETS = ("SetA", "SetB", "SetC", "SetD", "SetE")


def build_upset_sample() -> None:
    """Build a nested set system with a strictly decreasing top-8 intersection ranking.

    Nested tiers keep the demo readable and reproducible:
    5-way=15, 4-way(ABCD)=25, 3-way(ABC)=40, 2-way(AB)=30, then set-private
    blocks sized so the top-8 intersections descend and all are >= 2.
    """
    cursor = 1

    def _take(count: int) -> list[str]:
        nonlocal cursor
        values = [f"G{index:04d}" for index in range(cursor, cursor + count)]
        cursor += count
        return values

    five = _take(15)
    four = _take(25)
    three = _take(40)
    two = _take(30)
    private = {name: _take(size) for name, size in zip(UPSET_SETS, (52, 31, 57, 73, 90))}

    memberships = {
        "SetA": five + four + three + two + private["SetA"],
        "SetB": five + four + three + two + private["SetB"],
        "SetC": five + four + three + private["SetC"],
        "SetD": five + four + private["SetD"],
        "SetE": five + private["SetE"],
    }

    records = [{"set": name, "element": element} for name in UPSET_SETS for element in memberships[name]]
    frame = pd.DataFrame(records, columns=["set", "element"])
    target = SAMPLE_DIR / "upset_genesets.csv"
    frame.to_csv(target, index=False, encoding="utf-8", lineterminator="\n")

    counts = frame.groupby("element")["set"].apply(frozenset).value_counts()
    top = counts.head(8)
    print(
        f"[upset] {target.name}: {frame.shape[0]} rows; "
        f"top-8 intersections={[int(v) for v in top.tolist()]}"
    )


# --------------------------------------------------------------------------
# 10. Kaplan-Meier: 2 groups x 90 patients (architecture §4.2 #13, seed 31)
# --------------------------------------------------------------------------
KM_SEED = 31
KM_PER_GROUP = 90
KM_GROUPS = ("A", "B")
# NOTE: the architecture doc suggests Exponential(45) vs Exponential(32); with
# 20% censoring and a 60-unit observation window that pair yields log-rank
# p ~= 0.51 (no visible separation), so the scales are widened to 70 / 25
# (p ~= 7.5e-5) to make the demo meaningful. Structure is unchanged.
KM_SCALES = {"A": 70.0, "B": 25.0}
KM_MAX_TIME = 60.0


def build_km_sample() -> None:
    rng = np.random.default_rng(KM_SEED)

    rows: list[dict] = []
    index = 1
    for group in KM_GROUPS:
        times = rng.exponential(KM_SCALES[group], KM_PER_GROUP)
        times = np.clip(np.round(times, 2), 0.5, KM_MAX_TIME)
        censored = rng.random(KM_PER_GROUP) < 0.20
        for time_value, is_censored in zip(times, censored):
            rows.append(
                {
                    "sample": f"P{index:03d}",
                    "time": float(time_value),
                    "status": 0 if is_censored else 1,
                    "group": group,
                }
            )
            index += 1

    frame = pd.DataFrame(rows, columns=["sample", "time", "status", "group"])
    target = SAMPLE_DIR / "km_survival.csv"
    frame.to_csv(target, index=False, encoding="utf-8", lineterminator="\n")
    events = int(frame["status"].sum())
    print(f"[km] {target.name}: {frame.shape[0]} rows; {events} events / {len(frame) - events} censored")


# --------------------------------------------------------------------------
# 11. Manhattan: 5000 SNPs over 5 chromosomes (architecture §4.2 #14, seed 42)
# --------------------------------------------------------------------------
MANHATTAN_SEED = 42
MANHATTAN_SNPS = 5000
MANHATTAN_CHROMS = (("1", 120_000_000), ("2", 95_000_000), ("3", 80_000_000), ("4", 70_000_000), ("5", 60_000_000))
MANHATTAN_SIG = 6
MANHATTAN_SUGGESTIVE = 40


def build_manhattan_sample() -> None:
    rng = np.random.default_rng(MANHATTAN_SEED)

    total_length = sum(length for _, length in MANHATTAN_CHROMS)
    rows: list[dict] = []
    for chrom, length in MANHATTAN_CHROMS:
        snp_count = int(round(MANHATTAN_SNPS * length / total_length))
        positions = np.sort(rng.integers(1, length, snp_count))
        for pos in positions:
            rows.append({"snp": "", "chr": chrom, "pos": int(pos), "pvalue": float(rng.random()), "gene": ""})

    frame = pd.DataFrame(rows, columns=["snp", "chr", "pos", "pvalue", "gene"])
    frame = frame.sort_values(["chr", "pos"], kind="mergesort").reset_index(drop=True)

    sig_index = rng.choice(len(frame), size=MANHATTAN_SIG, replace=False)
    frame.loc[sig_index, "pvalue"] = rng.uniform(1e-12, 5e-8, MANHATTAN_SIG)
    frame.loc[sig_index, "gene"] = [f"GENE{index}" for index in range(1, MANHATTAN_SIG + 1)]

    remaining = frame.index.difference(sig_index)
    sug_index = rng.choice(remaining, size=MANHATTAN_SUGGESTIVE, replace=False)
    frame.loc[sug_index, "pvalue"] = rng.uniform(5e-8, 1e-5, MANHATTAN_SUGGESTIVE)

    frame["snp"] = [f"rs{index:07d}" for index in range(1, len(frame) + 1)]
    frame["pvalue"] = frame["pvalue"].clip(1e-15, 1.0)

    target = SAMPLE_DIR / "manhattan_gwas.csv"
    frame.to_csv(target, index=False, encoding="utf-8", lineterminator="\n", float_format="%.6g")
    print(
        f"[manhattan] {target.name}: {frame.shape[0]} rows; "
        f"{int((frame['pvalue'] < 5e-8).sum())} significant (p<5e-8)"
    )


def main() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    copy_bubble_samples()
    build_gmp_sample()
    build_circle_sample()
    build_circularbar_sample()
    build_genvar_samples()
    build_volcano_sample()
    build_pca_sample()
    build_heatmap_sample()
    build_upset_sample()
    build_km_sample()
    build_manhattan_sample()
    print("done.")


if __name__ == "__main__":
    main()
