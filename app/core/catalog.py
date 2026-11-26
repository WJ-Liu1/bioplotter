from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PREVIEW_DIR = Path(__file__).resolve().parents[1] / "assets" / "previews"

CATEGORY_ORDER = (
    "网络关系",
    "分布比较",
    "矩阵与热图",
    "环形与极坐标",
    "统计与富集",
    "基因组与生存",
)


@dataclass(frozen=True)
class PlotMeta:
    name: str
    category: str
    summary: str
    inputs: str
    sample_keys: tuple[str, ...]
    preview: str
    engine: str
    tags: tuple[str, ...] = ()


# 数据形状：首页「按数据形状筛选」的六个桶，顺序即下拉顺序
DATA_SHAPE_ORDER = ("宽矩阵", "长表", "边表", "生存表", "集合表", "树文件")

# 模块 → 数据形状（与 PLOTS 一一对应）
PLOT_DATA_SHAPE: dict[str, str] = {
    # 边表：两份/三列连线关系
    "Arc Diagram": "边表",
    "Hierarchical Edge Bundling": "边表",
    "Chord Diagram": "边表",
    "Node-link Diagram": "边表",
    "Sankey": "边表",
    # 长表：一行一个观测
    "Raincloud Plot": "长表",
    "Beeswarm": "长表",
    "Split Violin": "长表",
    "ScaBoxDen": "长表",
    "Pirate Plot": "长表",
    "BubbleViz": "长表",
    "Grouped Matrix Plotting": "长表",
    "CircularBarPlot": "长表",
    "GO Enrichment": "长表",
    "Volcano Plot": "长表",
    "Genomic Variation Viewer": "长表",
    "Manhattan Plot": "长表",
    # 宽矩阵：行 × 列
    "CircleViz": "宽矩阵",
    "Mantel Test": "宽矩阵",
    "PCA": "宽矩阵",
    "Heatmap": "宽矩阵",
    # 生存表
    "Kaplan-Meier": "生存表",
    # 集合表
    "UpSet Plot": "集合表",
    # 树文件：Newick / Nexus
    "Paired Tree Comparison": "树文件",
}

# 上手难度：三档
DIFFICULTY_ORDER = ("入门", "中等", "进阶")

PLOT_DIFFICULTY: dict[str, str] = {
    "Arc Diagram": "入门",
    "Node-link Diagram": "入门",
    "Beeswarm": "入门",
    "ScaBoxDen": "入门",
    "BubbleViz": "入门",
    "Volcano Plot": "入门",
    "PCA": "入门",
    "Heatmap": "入门",
    "Raincloud Plot": "中等",
    "Split Violin": "中等",
    "Pirate Plot": "中等",
    "GO Enrichment": "中等",
    "Manhattan Plot": "中等",
    "CircularBarPlot": "中等",
    "Kaplan-Meier": "中等",
    "Hierarchical Edge Bundling": "进阶",
    "Chord Diagram": "进阶",
    "Sankey": "进阶",
    "Mantel Test": "进阶",
    "Grouped Matrix Plotting": "进阶",
    "CircleViz": "进阶",
    "Genomic Variation Viewer": "进阶",
    "UpSet Plot": "进阶",
    "Paired Tree Comparison": "进阶",
}


def data_shape_for(name: str) -> str:
    """模块的数据形状；未登记时返回空串。"""
    return PLOT_DATA_SHAPE.get(name, "")


def difficulty_for(name: str) -> str:
    """模块的上手难度（入门 / 中等 / 进阶）；未登记时返回空串。"""
    return PLOT_DIFFICULTY.get(name, "")


PLOTS: dict[str, PlotMeta] = {
    "Arc Diagram": PlotMeta(
        name="Arc Diagram",
        category="网络关系",
        summary="节点排成一条基线，用弧线表达连边，适合观察网络模块与连接强度。",
        inputs="边表 from / to / value，或邻接矩阵",
        sample_keys=("arc",),
        preview="arc",
        engine="plotly",
        tags=("network", "arc", "module"),
    ),
    "Hierarchical Edge Bundling": PlotMeta(
        name="Hierarchical Edge Bundling",
        category="网络关系",
        summary="沿层次树骨架捆绑定边，在保留层级结构的同时揭示跨分支关系。",
        inputs="边表 from / to / value，from 支持层级路径",
        sample_keys=("heb",),
        preview="heb",
        engine="plotly",
        tags=("network", "hierarchy", "bundle"),
    ),
    "Chord Diagram": PlotMeta(
        name="Chord Diagram",
        category="网络关系",
        summary="圆周弦图展示实体之间的流量或关联，适合有向/对称关系矩阵。",
        inputs="from / to / value / color",
        sample_keys=("chord",),
        preview="chord",
        engine="plotly",
        tags=("network", "chord", "flow"),
    ),
    "Node-link Diagram": PlotMeta(
        name="Node-link Diagram",
        category="网络关系",
        summary="经典节点—连边网络图，支持根节点、边宽与颜色映射。",
        inputs="from / to / value / color",
        sample_keys=("nodelink",),
        preview="nodelink",
        engine="plotly",
        tags=("network", "graph", "hub"),
    ),
    "Sankey": PlotMeta(
        name="Sankey",
        category="网络关系",
        summary="用流带展示多层级之间的数量流转，适合物质、能量或用户路径。",
        inputs="links(source/target/value/colorlink) + nodes(nodes/colornode)",
        sample_keys=("sankey_links", "sankey_nodes"),
        preview="sankey",
        engine="plotly",
        tags=("flow", "sankey", "stage"),
    ),
    "Raincloud Plot": PlotMeta(
        name="Raincloud Plot",
        category="分布比较",
        summary="半小提琴 + 箱线 + 散点的组合，兼顾分布形态与统计摘要。",
        inputs="宽表（每列一组）或长表 Group / Value",
        sample_keys=("raincloud",),
        preview="raincloud",
        engine="plotly",
        tags=("distribution", "raincloud", "compare"),
    ),
    "Beeswarm": PlotMeta(
        name="Beeswarm",
        category="分布比较",
        summary="蜂群图自动错开散点，直观呈现每组观测值的密度与离群值。",
        inputs="Groups / Value / Group2",
        sample_keys=("beeswarm",),
        preview="beeswarm",
        engine="plotly",
        tags=("distribution", "swarm", "dots"),
    ),
    "Split Violin": PlotMeta(
        name="Split Violin",
        category="分布比较",
        summary="左右半小提琴对比两组分布，适合处理前后、病例对照等设计。",
        inputs="value / Group / Attribute",
        sample_keys=("splitviolin",),
        preview="splitviolin",
        engine="plotly",
        tags=("distribution", "violin", "paired"),
    ),
    "ScaBoxDen": PlotMeta(
        name="ScaBoxDen",
        category="分布比较",
        summary="散点叠加边缘箱线与密度，同时展示双变量关系与边际分布。",
        inputs="x / y / group",
        sample_keys=("scaboxden",),
        preview="scaboxden",
        engine="plotly",
        tags=("scatter", "marginal", "density"),
    ),
    "Pirate Plot": PlotMeta(
        name="Pirate Plot",
        category="分布比较",
        summary="海盗图结合散点、箱线与密度，适合小样本、多组之间的细腻比较。",
        inputs="连续值列 + 分类列",
        sample_keys=("pirate_cont", "pirate_cat"),
        preview="pirate",
        engine="plotly",
        tags=("distribution", "pirate", "bayes"),
    ),
    "Mantel Test": PlotMeta(
        name="Mantel Test",
        category="统计与富集",
        summary="检验两个距离矩阵的相关性，并可视化置换检验结果与拟合趋势。",
        inputs="物种/特征矩阵 + 环境矩阵",
        sample_keys=("mantel_spec", "mantel_env"),
        preview="mantel",
        engine="plotly",
        tags=("statistics", "matrix", "correlation"),
    ),
    "GO Enrichment": PlotMeta(
        name="GO Enrichment",
        category="统计与富集",
        summary="GO 富集条形图与气泡图，展示功能条目的富集程度与显著性。",
        inputs="GO_Class / GO_Term / number_of_out，或 Richfactor / GO_desc / Corrected_P / Expressed_GO",
        sample_keys=("go_bar", "go_bubble"),
        preview="go",
        engine="plotly",
        tags=("enrichment", "go", "bubble"),
    ),
    "BubbleViz": PlotMeta(
        name="BubbleViz",
        category="分布比较",
        summary="四维气泡图：x / y / 气泡大小 / 颜色分组，可再叠加一维做逐帧动画播放。",
        inputs="x（数值）/ y（数值）/ size（数值>0）/ color（分类）/ animation（可选分类）",
        sample_keys=("bubble_country", "bubble_aqi"),
        preview="bubbleviz",
        engine="plotly",
        tags=("bubble", "scatter", "animation", "气泡图", "气泡", "动态气泡"),
    ),
    "Grouped Matrix Plotting": PlotMeta(
        name="Grouped Matrix Plotting",
        category="矩阵与热图",
        summary="分类矩阵点阵图：Y 轴实体按分组排列，单元格用形状与颜色表示类别。",
        inputs="长表 row / group / column / category",
        sample_keys=("gmp_matrix",),
        preview="gmp",
        engine="plotly",
        tags=("matrix", "heatmap", "group", "分组矩阵", "分类矩阵", "点阵"),
    ),
    "CircleViz": PlotMeta(
        name="CircleViz",
        category="环形与极坐标",
        summary="三层同心环（分类 + 双数值环）叠加环形网络与外圈径向柱。",
        inputs="固定 6 列：id / name / data1 / data2 / data3 / data4（列名不参与解析）",
        sample_keys=("circleviz_cis_ctrl",),
        preview="circleviz",
        engine="plotly",
        tags=("circular", "network", "ring", "环形网络", "环图", "同心环"),
    ),
    "CircularBarPlot": PlotMeta(
        name="CircularBarPlot",
        category="环形与极坐标",
        summary="环形柱（玫瑰图）与分面条形双视图，正负双色 + 显著性星号。",
        inputs="Name / type / data（可正可负）/ p_value 或 num_stars（可选）",
        sample_keys=("circularbar_genes",),
        preview="circularbar",
        engine="plotly",
        tags=("circular", "bar", "rose", "玫瑰图", "环形柱", "极坐标柱"),
    ),
    "Genomic Variation Viewer": PlotMeta(
        name="Genomic Variation Viewer",
        category="基因组与生存",
        summary="基因组坐标轴上的基因结构块 + SNP 棒棒糖轨道，支持 lollipop / dandelion 两种模式。",
        inputs="gene 结构 name/start/end + SNP name/position/score（上轨与下轨）",
        sample_keys=("genvar_feature", "genvar_snp_upper", "genvar_snp_lower"),
        preview="genvar",
        engine="plotly",
        tags=("genome", "track", "snp", "基因组轨道", "变异", "棒棒糖图"),
    ),
    "Volcano Plot": PlotMeta(
        name="Volcano Plot",
        category="统计与富集",
        summary="log2FC 对 -log10(p) 的差异表达散点，阈值线 + Top-N 基因标注。",
        inputs="gene / log2FC / pvalue（可选 padj、group）",
        sample_keys=("volcano_degs",),
        preview="volcano",
        engine="plotly",
        tags=("differential", "volcano", "火山图", "差异表达", "deg"),
    ),
    "PCA": PlotMeta(
        name="PCA",
        category="统计与富集",
        summary="样本主成分得分散点，轴标题带解释方差，可叠加分组置信椭圆。",
        inputs="宽表：第 1 列样本名 + 数值特征列（可选 group）",
        sample_keys=("pca_samples",),
        preview="pca",
        engine="plotly",
        tags=("ordination", "pca", "降维", "主成分", "qc"),
    ),
    "Heatmap": PlotMeta(
        name="Heatmap",
        category="矩阵与热图",
        summary="表达矩阵热图，支持按行 z-score、行/列层次聚类重排与分组色条。",
        inputs="宽表：第 1 列行名 + 数值列（可选行分组列）",
        sample_keys=("heatmap_expression",),
        preview="heatmap",
        engine="plotly",
        tags=("matrix", "heatmap", "cluster", "热图", "聚类", "表达矩阵"),
    ),
    "UpSet Plot": PlotMeta(
        name="UpSet Plot",
        category="矩阵与热图",
        summary="三面板集合交集图：交集柱 + 集合总量 + 成员点阵，替代韦恩图。",
        inputs="长表 set / element，或 0-1 宽表",
        sample_keys=("upset_genesets",),
        preview="upset",
        engine="plotly",
        tags=("set", "intersection", "upset", "交集", "集合", "venn"),
    ),
    "Kaplan-Meier": PlotMeta(
        name="Kaplan-Meier",
        category="基因组与生存",
        summary="生存曲线（阶梯线 + 删失标记 + 风险表），内置 log-rank 检验。",
        inputs="sample / time / status / group",
        sample_keys=("km_survival",),
        preview="km",
        engine="plotly",
        tags=("survival", "kaplan", "生存曲线", "生存分析", "km"),
    ),
    "Manhattan Plot": PlotMeta(
        name="Manhattan Plot",
        category="基因组与生存",
        summary="全基因组关联散点，按染色体分色并累积坐标，标注显著位点。",
        inputs="snp / chr / pos / pvalue（可选 gene）",
        sample_keys=("manhattan_gwas",),
        preview="manhattan",
        engine="plotly",
        tags=("gwas", "manhattan", "曼哈顿图", "全基因组", "关联"),
    ),
    "Paired Tree Comparison": PlotMeta(
        name="Paired Tree Comparison",
        category="基因组与生存",
        summary="两棵系统发育树镜像并排，按叶标签配对并以直线/曲线连接，支持分组着色与分支高亮。",
        inputs="Newick/Nexus 树 ×2 + 配对表 tree1_label / tree2_label + 可选分组表 label / group",
        sample_keys=("pt_tree1", "pt_tree2", "pt_pairing", "pt_groups"),
        preview="pairedtree",
        engine="plotly",
        tags=(
            "tree",
            "phylogeny",
            "tree-compare",
            "paired",
            "双树比较",
            "进化树",
            "系统发育",
            "newick",
        ),
    ),
}


@lru_cache(maxsize=None)
@lru_cache(maxsize=None)
def preview_svg(plot_name: str) -> str:
    """Return the inline SVG preview for a plot, cached per process."""
    meta = PLOTS[plot_name]
    path = PREVIEW_DIR / f"{meta.preview}.svg"
    return path.read_text(encoding="utf-8")


def figure_number(plot_name: str) -> int:
    """图版编号：按目录顺序从 1 开始，用于卡片与文档页的 Fig. 标注。"""
    try:
        return list(PLOTS).index(plot_name) + 1
    except ValueError:
        return 0


def meta_for(plot_name: str) -> PlotMeta:
    return PLOTS[plot_name]


def grouped_plots() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {category: [] for category in CATEGORY_ORDER}
    for name, meta in PLOTS.items():
        groups.setdefault(meta.category, []).append(name)
    return {category: names for category, names in groups.items() if names}


def search_plots(query: str, category: str = "全部", data_shape: str = "全部形状") -> list[str]:
    query = (query or "").strip().lower()
    names = list(PLOTS)
    if category and category != "全部":
        names = [n for n in names if PLOTS[n].category == category]
    if data_shape and data_shape != "全部形状":
        names = [n for n in names if data_shape_for(n) == data_shape]
    if not query:
        return names

    def matches(name: str) -> bool:
        meta = PLOTS[name]
        haystack = " ".join(
            [meta.name, meta.category, meta.summary, meta.inputs, *meta.tags]
        ).lower()
        return query in haystack

    return [n for n in names if matches(n)]
