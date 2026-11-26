from __future__ import annotations

import numpy as np
import pandas as pd


def arc_example() -> pd.DataFrame:
    nodes = [f"Node_{i}" for i in range(1, 9)]
    rng = np.random.default_rng(42)
    m = rng.integers(0, 10, size=(8, 8)).astype(float)
    m = np.triu(m, 1)
    m = m + m.T
    np.fill_diagonal(m, 0)
    df = pd.DataFrame(m, columns=nodes)
    df.insert(0, "from", nodes)
    return df


def beeswarm_example() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = []
    for g in ["A", "B", "C"]:
        for _ in range(40):
            rows.append({"Groups": g, "Value": rng.normal(loc={"A": 1, "B": 2, "C": 3}[g], scale=0.5), "Group2": g})
    return pd.DataFrame(rows)


def chord_example() -> pd.DataFrame:
    return pd.DataFrame({
        "from": ["A", "A", "B", "C", "D", "E"],
        "to": ["B", "C", "D", "D", "E", "A"],
        "value": [5, 7, 4, 3, 8, 6],
        "color": ["#4e79a7", "#59a14f", "#e15759", "#f28e2b", "#76b7b2", "#edc948"],
    })


def heb_example() -> pd.DataFrame:
    return pd.DataFrame({
        "from": ["Root_A", "Root_A", "Root_B", "Root_B", "Root_C", "Root_C"],
        "to": ["Leaf_1", "Leaf_2", "Leaf_3", "Leaf_4", "Leaf_5", "Leaf_6"],
        "value": [3, 5, 2, 6, 4, 7],
    })


def nodelink_example() -> pd.DataFrame:
    return pd.DataFrame({
        "from": ["Hub", "Hub", "Hub", "Branch1", "Branch2", "Branch3"],
        "to": ["A", "B", "C", "D", "E", "F"],
        "value": [10, 8, 6, 5, 3, 4],
        "color": ["#1f77b4", "#1f77b4", "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"],
    })


def pirate_example() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(42)
    cont = pd.DataFrame({"score": np.r_[rng.normal(2, 0.6, 30), rng.normal(3.2, 0.7, 30)]})
    cat = pd.DataFrame({"group": ["G1"] * 30 + ["G2"] * 30})
    return cont, cat


def raincloud_example() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    return pd.DataFrame({
        "Group_1": rng.normal(0, 1, 60),
        "Group_2": rng.normal(1.2, 1, 60),
        "Group_3": rng.normal(2.1, 1, 60),
        "Group_4": rng.normal(2.9, 1, 60),
    })


def mantel_example() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(11)
    spec = pd.DataFrame(rng.normal(size=(18, 5)), columns=[f"S{i}" for i in range(1, 6)])
    env = spec + rng.normal(scale=0.35, size=spec.shape)
    env.columns = [f"E{i}" for i in range(1, 6)]
    return spec, env


def go_bar_example() -> pd.DataFrame:
    return pd.DataFrame({
        "GO_Class": ["BP"] * 4 + ["CC"] * 4 + ["MF"] * 4,
        "GO_Term": [f"GO:{i:04d}" for i in range(1, 13)],
        "number_of_out": [15, 22, 11, 9, 17, 8, 13, 7, 25, 14, 10, 6],
    })


def go_bubble_example() -> pd.DataFrame:
    return pd.DataFrame({
        "Richfactor": [0.12, 0.18, 0.23, 0.31, 0.42, 0.55],
        "GO_desc": [f"GO term {i}" for i in range(1, 7)],
        "Corrected_P": [0.04, 0.03, 0.01, 0.008, 0.002, 0.0008],
        "Expressed_GO": [6, 10, 13, 17, 22, 30],
    })


def sankey_example() -> tuple[pd.DataFrame, pd.DataFrame]:
    links = pd.DataFrame({
        "source": ["A", "A", "B", "C"],
        "target": ["B", "C", "D", "D"],
        "value": [8, 5, 6, 7],
        "colorlink": ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"],
    })
    nodes = pd.DataFrame({
        "nodes": ["A", "B", "C", "D"],
        "colornode": ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"],
    })
    return links, nodes


def scaboxden_example() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    x = rng.normal(size=120)
    y = x * 0.8 + rng.normal(scale=0.8, size=120)
    g = np.where(x > 0, "G1", "G2")
    return pd.DataFrame({"x": x, "y": y, "group": g})


def splitviolin_example() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "value": np.r_[rng.normal(2.0, 0.4, 40), rng.normal(2.5, 0.5, 40), rng.normal(3.0, 0.45, 40), rng.normal(3.4, 0.55, 40)],
        "Group": ["A"] * 80 + ["B"] * 80,
        "Attribute": ["Treat1"] * 40 + ["Treat2"] * 40 + ["Treat1"] * 40 + ["Treat2"] * 40,
    })
