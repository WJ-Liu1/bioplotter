"""Python 代码配方：每个图形的可运行示例 + 本站完整模块源码文件名。"""

from __future__ import annotations

from textwrap import dedent


PY_RECIPES: dict[str, str] = {
    "Arc Diagram": """
        import numpy as np
        import pandas as pd
        import plotly.graph_objects as go

        edges = pd.read_csv("arc_edgelist.csv")
        nodes = list(dict.fromkeys(pd.concat([edges["from"], edges["to"]])))
        x = {name: i for i, name in enumerate(nodes)}

        fig = go.Figure()
        for _, row in edges.iterrows():
            x0, x1 = x[row["from"]], x[row["to"]]
            peak = 0.25 + 0.55 * abs(x1 - x0) / max(len(nodes) - 1, 1)
            t = np.linspace(0.0, 1.0, 40)
            xs = (1 - t) * x0 + t * x1
            ys = np.sin(np.pi * t) * peak
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", hoverinfo="skip", showlegend=False,
                line=dict(color="#4C78A8", width=0.8 + 0.6 * row["value"]),
            ))

        fig.add_trace(go.Scatter(
            x=list(x.values()), y=[0] * len(x), mode="markers+text",
            text=nodes, textposition="bottom center",
            marker=dict(size=7, color="#2B3A55"), showlegend=False,
        ))
        fig.update_layout(
            template="simple_white", height=520,
            margin=dict(l=20, r=20, t=20, b=40),
            xaxis=dict(visible=False), yaxis=dict(visible=False),
        )
        fig.show()
    """,
    "Hierarchical Edge Bundling": """
        import numpy as np
        import pandas as pd
        import plotly.graph_objects as go

        edges = pd.read_csv("heb_sample.csv")
        paths = set(edges["from"]) | set(edges["to"])

        def leaf(path):
            return str(path).split(".")[-1]

        def depth(path):
            return str(path).count(".")

        leaves = sorted({leaf(p) for p in paths})
        angles = {name: 2 * np.pi * i / len(leaves) for i, name in enumerate(leaves)}

        def xy(path):
            radius = 0.42 + 0.11 * depth(path)
            angle = angles[leaf(path)]
            return radius * np.cos(angle), radius * np.sin(angle)

        t = np.linspace(0.0, 1.0, 36)
        fig = go.Figure()
        for _, row in edges.iterrows():
            x0, y0 = xy(row["from"])
            x1, y1 = xy(row["to"])
            # 控制点向圆心收拢，模拟层级捆绑
            cx, cy = 0.35 * (x0 + x1), 0.35 * (y0 + y1)
            xs = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
            ys = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", hoverinfo="skip", showlegend=False,
                line=dict(color="rgba(76,120,168,0.5)", width=0.6),
            ))

        fig.add_trace(go.Scatter(
            x=[np.cos(a) for a in angles.values()],
            y=[np.sin(a) for a in angles.values()],
            mode="markers+text", text=list(angles), textposition="middle right",
            marker=dict(size=5, color="#2B3A55"), showlegend=False,
        ))
        fig.update_layout(template="simple_white", height=680,
                          xaxis=dict(visible=False), yaxis=dict(visible=False))
        fig.show()
    """,
    "Pirate Plot": """
        import numpy as np
        import pandas as pd
        import matplotlib.pyplot as plt

        df = pd.read_csv("pirate_continuous_sample.csv")
        rng = np.random.default_rng(0)

        fig, ax = plt.subplots(figsize=(7, 4.5))
        for i, (column, values) in enumerate(df.items(), start=1):
            values = values.dropna().to_numpy()
            if values.size == 0:
                continue
            parts = ax.violinplot(values, positions=[i], widths=0.7,
                                  showextrema=False, showmedians=False)
            for body in parts["bodies"]:
                body.set_alpha(0.32)
            ax.boxplot(values, positions=[i], widths=0.12, showfliers=False)
            ax.scatter(i + rng.normal(0, 0.045, values.size), values,
                       s=9, alpha=0.55, color="#3C5488", linewidths=0)

        ax.set_xticks(range(1, len(df.columns) + 1))
        ax.set_xticklabels(df.columns)
        ax.spines[["top", "right"]].set_visible(False)
        plt.show()
    """,
    "Chord Diagram": """
        # 最小可运行示例：单向弦图（弧带 + 中心线 + 目标端箭头）。
        # 完整的扇区分配 / 飘带宽度 / 参数面板见 app/modules/chord_edgelist.py。
        import numpy as np
        import pandas as pd
        import plotly.graph_objects as go

        edges = pd.read_csv("chord_sample.csv")
        nodes = list(dict.fromkeys(pd.concat([edges["from"], edges["to"]])))

        total = {name: 0.0 for name in nodes}
        for _, row in edges.iterrows():
            total[row["from"]] += row["value"]
            total[row["to"]] += row["value"]

        gap = np.deg2rad(2)
        usable = 2 * np.pi - gap * len(nodes)
        starts, cursor = {}, np.pi / 2
        for name in nodes:
            span = usable * total[name] / sum(total.values())
            starts[name] = (cursor, cursor + span)
            cursor += span + gap

        fig = go.Figure()
        for name in nodes:
            angle = np.linspace(*starts[name], 80)
            fig.add_trace(go.Scatter(
                x=np.cos(angle), y=np.sin(angle), mode="lines",
                line=dict(width=16, color="#8fbcd4"),
                hoverinfo="skip", showlegend=False,
            ))

        t = np.linspace(0.0, 1.0, 60)
        for _, row in edges.iterrows():
            a0 = np.mean(starts[row["from"]])
            a1 = np.mean(starts[row["to"]])
            p0 = 0.99 * np.array([np.cos(a0), np.sin(a0)])
            p1 = 0.99 * np.array([np.cos(a1), np.sin(a1)])
            c0, c1 = 0.18 * p0, 0.18 * p1
            xs = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * c0[0] \\
                 + 3 * (1 - t) * t ** 2 * c1[0] + t ** 3 * p1[0]
            ys = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * c0[1] \\
                 + 3 * (1 - t) * t ** 2 * c1[1] + t ** 3 * p1[1]
            width = 0.8 + 2.6 * row["value"] / max(edges["value"].max(), 1)
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", line=dict(color="rgba(76,120,168,0.6)",
                                                   width=width),
                hoverinfo="skip", showlegend=False,
            ))
            fig.add_annotation(
                x=p1[0], y=p1[1], ax=xs[-4], ay=ys[-4],
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=3, arrowsize=1.2,
                arrowwidth=1.2, arrowcolor="#2B3A55", text="",
            )

        fig.update_layout(template="simple_white", height=680,
                          xaxis=dict(visible=False, scaleanchor="y", scaleratio=1),
                          yaxis=dict(visible=False))
        fig.show()
    """,
    "Node-link Diagram": """
        import networkx as nx
        import pandas as pd
        import plotly.graph_objects as go

        # 示例文件无表头：from / to / value / color
        edges = pd.read_csv("nodelink_sample.csv", header=None,
                            names=["from", "to", "value", "color"])
        graph = nx.Graph()
        graph.add_weighted_edges_from(edges[["from", "to", "value"]].itertuples(index=False))
        pos = nx.spring_layout(graph, seed=1, weight="weight")

        ex, ey = [], []
        for u, v in graph.edges():
            ex += [pos[u][0], pos[v][0], None]
            ey += [pos[u][1], pos[v][1], None]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", hoverinfo="skip",
                                 line=dict(color="rgba(120,130,145,0.55)", width=1),
                                 showlegend=False))
        fig.add_trace(go.Scatter(
            x=[pos[n][0] for n in graph], y=[pos[n][1] for n in graph],
            mode="markers+text", text=list(graph.nodes),
            textposition="top center", hoverinfo="skip",
            marker=dict(size=9, color="#3C5488", line=dict(width=1, color="white")),
            showlegend=False,
        ))
        fig.update_layout(template="simple_white", height=620,
                          xaxis=dict(visible=False), yaxis=dict(visible=False))
        fig.show()
    """,
    "Raincloud Plot": """
        import pandas as pd
        import seaborn as sns
        import matplotlib.pyplot as plt

        # 示例文件：制表符分隔 + 逗号小数
        wide = pd.read_csv("raincloud_sample.txt", sep="\\t", decimal=",")
        long = wide.melt(var_name="group", value_name="value").dropna()

        fig, ax = plt.subplots(figsize=(7.5, 4.6))
        sns.violinplot(data=long, x="group", y="value", hue="group",
                       inner=None, cut=0, density_norm="width",
                       palette="Set2", legend=False, ax=ax)
        sns.boxplot(data=long, x="group", y="value", width=0.12,
                    showfliers=False, color="white", ax=ax)
        sns.stripplot(data=long, x="group", y="value", size=3,
                      color="#2B3A55", alpha=0.45, ax=ax)
        ax.spines[["top", "right"]].set_visible(False)
        plt.show()
    """,
    "Mantel Test": """
        import numpy as np
        import pandas as pd
        from scipy.spatial.distance import pdist
        from scipy.stats import pearsonr

        # Data 1 前两行分别是站点分组与变量名，之后每行是一个站点
        raw = pd.read_csv("mantel_spec_sample.csv", header=None)
        group_labels = raw.iloc[0].astype(str).tolist()
        var_names = raw.iloc[1].astype(str).tolist()
        spec = raw.iloc[2:].copy()
        spec.columns = var_names
        spec = spec.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")

        groups = {}
        for label, var in zip(group_labels, var_names):
            groups.setdefault(label, []).append(var)
        groups = {key: [c for c in cols if c in spec.columns] for key, cols in groups.items()}
        site_spec = spec[groups[next(iter(groups))]].fillna(0)

        env = pd.read_csv("mantel_env_sample.csv")
        env = env.apply(pd.to_numeric, errors="coerce").fillna(0)

        n = min(len(site_spec), len(env))
        site_spec, env = site_spec.iloc[:n], env.iloc[:n]

        d_spec = pdist(site_spec.to_numpy(dtype=float), metric="braycurtis")
        z = (env - env.mean()) / env.std(ddof=0).replace(0, 1)
        d_env = pdist(z.to_numpy(dtype=float), metric="euclidean")

        r, p = pearsonr(d_spec, d_env)
        rng = np.random.default_rng(1)
        hits = 0
        for _ in range(999):
            order = rng.permutation(n)
            d_perm = pdist(z.to_numpy(dtype=float)[order], metric="euclidean")
            hits += abs(pearsonr(d_spec, d_perm)[0]) >= abs(r)
        p_perm = (hits + 1) / 1000
        print(f"Mantel r = {r:.3f}, p(perm) = {p_perm:.4f}, p(t) = {p:.4f}")
    """,
    "Beeswarm": """
        import pandas as pd
        import seaborn as sns
        import matplotlib.pyplot as plt

        df = pd.read_csv("beeswarm_sample.txt", sep=r"\\s+")

        fig, ax = plt.subplots(figsize=(7, 4.6))
        sns.swarmplot(data=df, x="Groups", y="Value", hue="Group2",
                      size=4, dodge=False, ax=ax)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(title="Group2", bbox_to_anchor=(1.02, 1), frameon=False)
        plt.show()
    """,
    "GO Enrichment": """
        import pandas as pd
        import plotly.express as px

        df = pd.read_csv("go_bar_sample.txt", sep="\\t")
        df = df.sort_values("number_of_out")

        fig = px.bar(
            df, x="number_of_out", y="GO_Term", color="GO_Class",
            orientation="h", template="simple_white",
            labels={"number_of_out": "基因数", "GO_Term": "", "GO_Class": "GO 类别"},
            height=max(420, 26 * len(df)),
        )
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=20))
        fig.show()
    """,
    "Sankey": """
        import re

        import pandas as pd
        import plotly.graph_objects as go

        links = pd.read_csv("sankey_links.txt", sep="\\t")
        nodes = pd.read_csv("sankey_nodes.txt", sep="\\t")
        index = {name: i for i, name in enumerate(nodes["nodes"])}

        def safe_color(value):
            text = str(value)
            if re.match(r"^(#|rgb|hsl)", text):
                return text
            return {"black": "black", "white": "white", "red": "red",
                    "blue": "blue", "green": "green", "grey": "grey"}.get(
                        text.lower(), "#9aa5b1")

        node_colors = [safe_color(value) for value in nodes["colornode"]]

        fig = go.Figure(go.Sankey(
            node=dict(label=nodes["nodes"], color=node_colors,
                      pad=12, thickness=14, line=dict(color="white", width=0.5)),
            link=dict(source=links["source"].map(index),
                      target=links["target"].map(index),
                      value=links["value"], color=links["colorlink"]),
        ))
        fig.update_layout(template="simple_white", height=520,
                          margin=dict(l=20, r=20, t=30, b=20))
        fig.show()
    """,
    "ScaBoxDen": """
        import numpy as np

        import pandas as pd
        import plotly.graph_objects as go
        import plotly.express as px

        df = pd.read_csv("scaboxden_sample.txt", sep="\\t")

        fig = px.scatter(
            df, x="x", y="y", color="group",
            marginal_x="box", marginal_y="box",
            template="simple_white", height=620,
        )
        fig.update_traces(marker=dict(size=5, opacity=0.7),
                          selector=dict(mode="markers"))
        slope, intercept = np.polyfit(df["x"], df["y"], 1)
        xs = np.linspace(df["x"].min(), df["x"].max(), 50)
        fig.add_trace(go.Scatter(
            x=xs, y=slope * xs + intercept, mode="lines",
            line=dict(color="#E64B35", width=1.4), showlegend=False,
        ))
        fig.show()
    """,
    "Split Violin": """
        import pandas as pd
        import seaborn as sns
        import matplotlib.pyplot as plt

        df = pd.read_csv("splitviolin_sample.txt", sep="\\t")
        two_sides = df["Attribute"].nunique() == 2

        fig, ax = plt.subplots(figsize=(7, 4.6))
        sns.violinplot(
            data=df, x="Group", y="Value", hue="Attribute",
            split=two_sides, inner="quart", cut=0,
            palette="Set2", ax=ax,
        )
        ax.spines[["top", "right"]].set_visible(False)
        plt.show()
    """,
    "BubbleViz": """
        import pandas as pd
        import plotly.express as px

        df = pd.read_csv("bubble_country.csv")

        fig = px.scatter(
            df, x="GDP per capita", y="Life expectancy",
            size="Population", color="Continent", animation_frame="Year",
            size_max=45, log_x=True, template="simple_white", height=620,
            hover_name="Country",
        )
        fig.update_layout(margin=dict(l=20, r=20, t=30, b=20))
        fig.show()
    """,
    "Grouped Matrix Plotting": """
        import pandas as pd
        import plotly.express as px

        df = pd.read_csv("gmp_matrix.csv")

        fig = px.scatter(
            df, x="column", y="row", color="category", symbol="category",
            facet_col="group", facet_col_wrap=2, template="simple_white",
        )
        fig.update_traces(marker=dict(size=13, line=dict(width=1, color="white")))
        fig.update_yaxes(matches=None, showticklabels=True)
        fig.update_layout(height=680, margin=dict(l=20, r=20, t=40, b=30))
        fig.show()
    """,
    "CircleViz": """
        # 最小可运行示例：多层同心环（分类 + 数值环）。
        # 完整的环带 / 网络连线 / 径向柱见 app/modules/circle_viz.py。
        import numpy as np
        import pandas as pd
        import plotly.graph_objects as go

        df = pd.read_csv("circleviz_cis_ctrl.csv")
        theta = np.arange(len(df)) / len(df) * 360
        width = 360 / len(df) * 0.9

        fig = go.Figure()
        rings = [("data1", "#E64B35"), ("data2", "#4DBBD5"),
                 ("data3", "#00A087"), ("data4", "#3C5488")]
        for i, (column, color) in enumerate(rings):
            base = i * 0.25
            values = pd.to_numeric(df[column], errors="coerce").fillna(0)
            fig.add_trace(go.Barpolar(
                r=base + values / max(values.max(), 1) * 0.22,
                base=[base] * len(df), theta=theta, width=width,
                marker_color=color, marker_line_color="white",
                marker_line_width=0.5, name=column,
            ))

        fig.update_layout(
            template="simple_white", height=640,
            polar=dict(radialaxis=dict(visible=False, range=[0, 1.05]),
                       angularaxis=dict(visible=False, direction="clockwise")),
            legend=dict(orientation="h", y=1.05),
        )
        fig.show()
    """,
    "CircularBarPlot": """
        import numpy as np
        import pandas as pd
        import plotly.graph_objects as go

        df = pd.read_csv("circularbar_genes.csv").reset_index(drop=True)
        step = 360 / len(df)
        theta = [i * step for i in range(len(df))]

        fig = go.Figure(go.Barpolar(
            r=df["data"].abs(), theta=theta, width=step * 0.86,
            marker_color=["#E64B35" if value >= 0 else "#4DBBD5"
                          for value in df["data"]],
            marker_line_color="white", marker_line_width=0.6,
            hovertext=df["Name"], hoverinfo="text+r",
        ))
        fig.update_layout(
            template="simple_white", height=680,
            polar=dict(radialaxis=dict(visible=True, showticklabels=True),
                       angularaxis=dict(visible=False, direction="clockwise")),
        )
        fig.show()
    """,
    "Genomic Variation Viewer": """
        # 最小可运行示例：基因结构块 + 上下轨 SNP 棒棒糖。
        # 完整的轨道 / 缩放 / 参数面板见 app/modules/genomic_variation.py。
        import pandas as pd
        import plotly.graph_objects as go

        feature = pd.read_csv("genvar_feature.csv")
        upper = pd.read_csv("genvar_snp_upper.csv")
        lower = pd.read_csv("genvar_snp_lower.csv")

        fig = go.Figure()
        for _, row in feature.iterrows():
            fig.add_shape(type="rect", x0=row["start"], x1=row["end"],
                          y0=-0.16, y1=0.16, fillcolor="#4DBBD5",
                          line=dict(width=0))
            fig.add_annotation(x=(row["start"] + row["end"]) / 2, y=0.32,
                               text=row["name"], showarrow=False, font=dict(size=9))

        for frame, sign, color in ((upper, 1, "#E64B35"), (lower, -1, "#3C5488")):
            fig.add_trace(go.Scatter(
                x=frame["position"], y=frame["score"] * sign,
                mode="markers", marker=dict(size=6, color=color),
                name="upper" if sign > 0 else "lower", hovertext=frame["name"],
            ))

        fig.update_layout(template="simple_white", height=460,
                          xaxis_title="基因组位置", yaxis_title="score",
                          margin=dict(l=20, r=20, t=40, b=30))
        fig.show()
    """,
    "Volcano Plot": """
        import numpy as np
        import pandas as pd
        import plotly.express as px

        df = pd.read_csv("volcano_degs.csv")
        df["logp"] = -np.log10(df["pvalue"].clip(lower=1e-300))
        df["state"] = np.where(
            (df["log2FC"].abs() >= 1) & (df["pvalue"] < 0.05),
            np.where(df["log2FC"] > 0, "上调", "下调"), "不显著",
        )

        fig = px.scatter(
            df, x="log2FC", y="logp", color="state",
            color_discrete_map={"上调": "#E64B35", "下调": "#4DBBD5", "不显著": "#B8C2CC"},
            hover_name="gene", template="simple_white", height=600,
        )
        top = df[df["state"] != "不显著"].nlargest(10, "logp")
        fig.add_trace(px.scatter(top, x="log2FC", y="logp", text="gene").data[0])
        fig.update_traces(mode="markers", selector=dict(type="scatter"))
        fig.for_each_trace(lambda t: t.update(textposition="top center"))
        fig.add_vline(x=1, line_dash="dash", line_color="#94a3b8")
        fig.add_vline(x=-1, line_dash="dash", line_color="#94a3b8")
        fig.add_hline(y=-np.log10(0.05), line_dash="dash", line_color="#94a3b8")
        fig.show()
    """,
    "PCA": """
        import numpy as np
        import pandas as pd
        import plotly.express as px

        df = pd.read_csv("pca_samples.csv")
        matrix = df.iloc[:, 2:].apply(pd.to_numeric, errors="coerce").fillna(0)
        matrix = matrix.loc[:, matrix.std(ddof=0) > 0]

        z = (matrix - matrix.mean()) / matrix.std(ddof=0)
        u, s, vt = np.linalg.svd(z.to_numpy(), full_matrices=False)
        scores = u * s
        explained = s ** 2 / np.sum(s ** 2)

        fig = px.scatter(
            x=scores[:, 0], y=scores[:, 1], color=df["group"],
            hover_name=df["sample"], template="simple_white", height=560,
            labels={"x": f"PC1 ({explained[0]:.1%})",
                    "y": f"PC2 ({explained[1]:.1%})", "color": "group"},
        )
        fig.update_traces(marker=dict(size=9, line=dict(width=1, color="white")))
        fig.show()
    """,
    "Heatmap": """
        import pandas as pd
        import seaborn as sns
        import matplotlib.pyplot as plt

        df = pd.read_csv("heatmap_expression.csv", index_col=0)
        matrix = df.drop(columns=["group"]).apply(pd.to_numeric, errors="coerce").dropna()
        z = matrix.sub(matrix.mean(axis=1), axis=0).div(
            matrix.std(axis=1).replace(0, 1), axis=0
        )

        sns.clustermap(
            z, cmap="RdBu_r", center=0, figsize=(9, 7),
            row_cluster=True, col_cluster=True,
            cbar_kws={"label": "row z-score"},
        )
        plt.show()
    """,
    "UpSet Plot": """
        import pandas as pd
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        df = pd.read_csv("upset_genesets.csv")
        elements = sorted(df["element"].unique())
        sets = list(dict.fromkeys(df["set"]))
        membership = pd.DataFrame(
            {name: [element in set(df.loc[df["set"] == name, "element"])
                    for element in elements]
             for name in sets},
            index=elements,
        )
        counts = membership.groupby(sets).size().sort_values(ascending=False).head(15)

        labels = [f"组合 {i + 1}" for i in range(len(counts))]
        fig = make_subplots(rows=2, cols=1, row_heights=[0.65, 0.35],
                            shared_xaxes=True, vertical_spacing=0.04)
        fig.add_trace(go.Bar(x=labels, y=counts.values, marker_color="#3C5488"),
                      row=1, col=1)
        for i, combination in enumerate(counts.index):
            for j, value in enumerate(combination):
                if value:
                    fig.add_trace(go.Scatter(
                        x=[labels[i]], y=[sets[j]], mode="markers",
                        marker=dict(size=10, color="#3C5488"), showlegend=False,
                    ), row=2, col=1)
        fig.update_yaxes(type="category", row=2, col=1, autorange="reversed")
        fig.update_layout(template="simple_white", height=560, showlegend=False,
                          margin=dict(l=20, r=20, t=30, b=30))
        fig.show()
    """,
    "Kaplan-Meier": """
        import pandas as pd
        import matplotlib.pyplot as plt

        df = pd.read_csv("km_survival.csv")
        fig, ax = plt.subplots(figsize=(6.6, 4.4))

        for group, sub in df.groupby("group"):
            sub = sub.sort_values("time")
            times, survival, current = [0.0], [1.0], 1.0
            for _, row in sub.iterrows():
                if row["status"] == 1:
                    at_risk = (sub["time"] >= row["time"]).sum()
                    if at_risk > 0:
                        current *= 1 - 1 / at_risk
                    times += [row["time"], row["time"]]
                    survival += [survival[-1], current]
                else:
                    times.append(row["time"])
                    survival.append(survival[-1])
            ax.step(times, survival, where="post", label=str(group))
            censored = sub[sub["status"] == 0]
            ax.plot(censored["time"], [1.0] * len(censored), "|",
                    color="grey", alpha=0, label=None)

        ax.set_ylim(0, 1.02)
        ax.set_xlabel("time")
        ax.set_ylabel("survival probability")
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False)
        plt.show()
    """,
    "Manhattan Plot": """
        import numpy as np
        import pandas as pd
        import plotly.express as px

        df = pd.read_csv("manhattan_gwas.csv")
        df["chr"] = df["chr"].astype(str)
        df["logp"] = -np.log10(df["pvalue"].clip(lower=1e-300))

        order = sorted(df["chr"].unique())
        offsets, cursor = {}, 0
        for chrom in order:
            offsets[chrom] = cursor
            cursor += df.loc[df["chr"] == chrom, "pos"].max()
        df["xpos"] = df.apply(lambda row: offsets[row["chr"]] + row["pos"], axis=1)
        palette = {chrom: ("#4DBBD5" if i % 2 == 0 else "#3C5488")
                   for i, chrom in enumerate(order)}
        df["color"] = df["chr"].map(palette)

        fig = px.scatter(df, x="xpos", y="logp", color="chr",
                         color_discrete_map=palette, template="simple_white",
                         hover_name="snp", height=560)
        fig.update_traces(marker=dict(size=4))
        fig.add_hline(y=-np.log10(5e-8), line_dash="dash", line_color="#E64B35")
        fig.update_layout(showlegend=False,
                          xaxis_title="chromosome", yaxis_title="-log10(p)",
                          margin=dict(l=20, r=20, t=30, b=30))
        fig.show()
    """,
    "Paired Tree Comparison": """
        # 最小可运行示例：解析 Newick 并以两棵镜像树并排展示。
        # 完整的配对连线 / 分组着色 / 高亮见 app/modules/paired_tree.py。
        import re
        import matplotlib.pyplot as plt

        def parse(newick):
            text = re.sub(r"\\s+", "", newick.strip().rstrip(";"))
            tokens = re.findall(r"\\(|\\)|,|:[0-9.eE+-]+|[A-Za-z0-9_.-]+", text)
            pos = 0

            def node():
                nonlocal pos
                if tokens[pos] == "(":
                    pos += 1
                    kids = [node()]
                    while tokens[pos] == ",":
                        pos += 1
                        kids.append(node())
                    pos += 1
                    current = {"kids": kids, "len": 0.0, "name": ""}
                else:
                    current = {"kids": [], "len": 0.0, "name": tokens[pos]}
                    pos += 1
                if pos < len(tokens) and tokens[pos].startswith(":"):
                    current["len"] = float(tokens[pos][1:])
                    pos += 1
                return current

            return node()

        def layout(node_obj, cursor=0.0):
            if not node_obj["kids"]:
                node_obj["y"] = cursor
                return cursor + 1.0
            for kid in node_obj["kids"]:
                cursor = layout(kid, cursor)
            node_obj["y"] = sum(kid["y"] for kid in node_obj["kids"]) / len(node_obj["kids"])
            return cursor

        def draw(node_obj, x, ax, leaves):
            if not node_obj["kids"]:
                leaves.append((node_obj["name"], node_obj["y"], x))
                return
            for kid in node_obj["kids"]:
                x2 = x + max(kid["len"], 0.02)
                ax.plot([x, x, x2, x2], [node_obj["y"], kid["y"], kid["y"], kid["y"]],
                        color="#3C5488", linewidth=0.8)
                draw(kid, x2, ax, leaves)

        fig, axes = plt.subplots(1, 2, figsize=(9, 6))
        for ax, path in zip(axes, ["pt_tree1.nwk", "pt_tree2.nwk"]):
            tree = parse(open(path, encoding="utf-8").read())
            layout(tree)
            leaves = []
            draw(tree, 0.0, ax, leaves)
            for name, y, x in leaves:
                ax.text(x + 0.01, y, name, va="center", fontsize=7)
            ax.axis("off")
        plt.tight_layout()
        plt.show()
    """,
}


# 图形 → 本站实现文件（app/modules/）
MODULE_SOURCES: dict[str, str] = {
    "Arc Diagram": "arc.py",
    "Hierarchical Edge Bundling": "heb.py",
    "Pirate Plot": "pirate.py",
    "Chord Diagram": "chord_edgelist.py",
    "Node-link Diagram": "nodelink.py",
    "Raincloud Plot": "raincloud.py",
    "Mantel Test": "mantel.py",
    "Beeswarm": "beeswarm.py",
    "GO Enrichment": "goenrich.py",
    "Sankey": "sankey_d3.py",
    "ScaBoxDen": "scaboxden.py",
    "Split Violin": "splitviolin.py",
    "BubbleViz": "bubble.py",
    "Grouped Matrix Plotting": "grouped_matrix.py",
    "CircleViz": "circle_viz.py",
    "CircularBarPlot": "circular_bar.py",
    "Genomic Variation Viewer": "genomic_variation.py",
    "Volcano Plot": "volcano.py",
    "PCA": "pca.py",
    "Heatmap": "heatmap.py",
    "UpSet Plot": "upset.py",
    "Kaplan-Meier": "kaplan_meier.py",
    "Manhattan Plot": "manhattan.py",
    "Paired Tree Comparison": "paired_tree.py",
}


def py_code_for(name: str) -> str:
    code = PY_RECIPES.get(name)
    if not code:
        return ""
    return dedent(code).strip() + "\n"


def module_source_for(name: str) -> tuple[str, str] | None:
    """返回 (文件名, 源码)；未登记时返回 None。"""
    from pathlib import Path

    filename = MODULE_SOURCES.get(name)
    if not filename:
        return None
    path = Path(__file__).resolve().parents[1] / "modules" / filename
    if not path.exists():
        return None
    return filename, path.read_text(encoding="utf-8")
