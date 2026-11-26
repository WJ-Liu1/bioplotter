"""图形文档要点：每个图形的解读、要点、参数建议与注意事项。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    """单个图形的文档要点。"""

    notes: str = ""
    highlights: tuple[str, ...] = ()
    params: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()


RECIPES: dict[str, Recipe] = {
    'Arc Diagram': Recipe(
        notes='把节点排在一条基线上，用弧线高度表达连接关系。适合展示模块内部的连边结构、基因共表达或蛋白互作网络。',
        highlights=(
            '节点顺序决定图形可读性，可按度数、分组或首字母重排。',
            '弧高与连边权重联动，权重越大弧越高。',
            '节点标签在密集区域会自动避让，避免遮挡。',
        ),
        params=(
            '`value`：连边权重，控制弧线与线宽。',
            '节点分组：决定节点颜色与基线排列顺序。',
        ),
        caveats=(
            '边表默认按无向图处理；需要方向时启用有向模式并加箭头。',
        ),
    ),
    'Hierarchical Edge Bundling': Recipe(
        notes='沿层次骨架捆绑定边，兼顾层级结构与跨分支关系。当边表的 `from` / `to` 是 `a.b.c` 形式的路径时，先展开成树，再绘制捆绑边。',
        highlights=(
            '层次前缀相同的连边会被捆成一束，适合展示 Flare 这类分类数据。',
            '环形布局配合对角线边，能显著降低大量连边的视觉噪声。',
            '节点大小可用于编码实体的重要性（如节点度数）。',
        ),
        params=(
            '`value`：连边权重，控制捆束的线宽。',
            '`circular`：环形或树形布局，环形更适合展示整体结构。',
        ),
        caveats=(
            '路径字段需要先拆成节点层级；网站内部已自动展开，Python 里可用 `str.split()` 补上。',
        ),
    ),
    'Pirate Plot': Recipe(
        notes='海盗图 = 散点 + 箱线 + 密度，用一张图同时呈现原始观测与分布形态。适合小样本、多组比较，比纯箱线图更能暴露离群值与双峰。',
        highlights=(
            '每个点的位置会轻微抖动，避免重叠遮盖。',
            '中位线与置信区间叠在密度曲线上，兼顾稳健统计。',
            '组内样本量较小时，比柱状误差线更诚实。',
        ),
        params=(
            '连续值列：决定纵轴。',
            '分类列：决定横轴分组与颜色。',
        ),
        caveats=(
            '组数超过 8 个时建议改为分面，否则横轴会过于拥挤。',
        ),
    ),
    'Chord Diagram': Recipe(
        notes='圆周弦图把实体排在圆周上，用飘带表达流量或关联。适合邻接矩阵、有向流量、共现关系等「谁和谁有多少」的问题。',
        highlights=(
            '每段圆弧的弧长与该实体的总量成正比。',
            '飘带从源扇区中点连接到目标扇区中点，默认单向箭头。',
            '`directional = 1` 时箭头只画在目标端，不会出现双向三角。',
        ),
        params=(
            '`transparency`：飘带透明度，0.2–0.35 之间最清晰。',
            '方向：开启单向箭头；反向时把方向参数设为 -1。',
        ),
        caveats=(
            '实体超过 20 个时标签会拥挤，建议先合并低频类别。',
        ),
    ),
    'Node-link Diagram': Recipe(
        notes='经典节点—连边图，用位置和连线表达网络拓扑。适合观察中心节点、社区结构与连通性。',
        highlights=(
            '力导向布局会把连接紧密的节点聚在一起。',
            '节点大小可映射度数，边宽映射权重。',
            '根节点布局适合展示以某个实体为中心的网络。',
        ),
        params=(
            '`value`：连边权重，控制线宽。',
            '`color`：连边颜色列，可直接沿用数据中的颜色。',
        ),
        caveats=(
            '示例文件无表头，读取时需要 `header=None` 并按四列命名。',
        ),
    ),
    'Raincloud Plot': Recipe(
        notes='半小提琴 + 箱线 + 散点三合一，是分布比较里信息密度最高的一种。适合组间比较、前后对照与离群值排查。',
        highlights=(
            '半小提琴展示密度，箱线给出中位数与四分位，散点保留原始观测。',
            '密度曲线不会掩盖样本量，小样本一眼可见。',
            '组数较多时可横向排列，避免重叠。',
        ),
        params=(
            '宽表：每列一组；长表：`Group` / `Value`。',
            '`adjust`：密度平滑程度，越小越贴近原始数据。',
        ),
        caveats=(
            '示例文件是制表符分隔且小数点为逗号，读取时用 `decimal=","`。',
        ),
    ),
    'Mantel Test': Recipe(
        notes='检验两个距离矩阵（如物种群落与环境因子）是否显著相关。输出相关系数与置换检验 p 值，并可用散点 + 拟合线展示趋势。',
        highlights=(
            '先分别计算两个矩阵的距离，再做 Mantel 置换检验。',
            '999 次置换足以稳定估计 p 值。',
            '环境变量量纲不同时先做 z-score 标准化。',
        ),
        params=(
            '物种矩阵：建议用 Bray-Curtis 距离。',
            '环境矩阵：标准化后用欧氏距离。',
        ),
        caveats=(
            '示例物种表为分组表头，Python 中需先按样本聚合为矩阵再计算距离。',
        ),
    ),
    'Beeswarm': Recipe(
        notes='蜂群图把同组散点沿垂直方向错开，既不重叠也不改变数值位置。适合展示每组几十个观测的分布与离群值。',
        highlights=(
            '每个点的 y 值保持真实，x 方向只做避让。',
            '颜色可再编码第二分组（Group2）。',
            '样本量越大蜂群越宽，需要相应加大画布。',
        ),
        params=(
            '点大小：控制散点直径与避让间距。',
            '排布方式：整齐避让或准随机，后者更适合大样本。',
        ),
        caveats=(
            '分组超过 10 个时建议横向滚动或分面，否则点会挤在一起。',
        ),
    ),
    'GO Enrichment': Recipe(
        notes='GO 富集结果常用条形图或气泡图呈现：条形看条目数量，气泡看 richness 与显著性。适合功能注释、通路富集与多组比较。',
        highlights=(
            '条目按数量或 Rich factor 排序后更易读。',
            '颜色可编码 GO 大类（BP / MF / CC）。',
            '气泡大小常映射基因数，颜色映射校正 p 值。',
        ),
        params=(
            '条形图：`GO_Term` + `number_of_out`。',
            '气泡图：`Richfactor` + `Corrected_P` + `Expressed_GO`。',
        ),
        caveats=(
            '`Corrected_P` 跨越多个数量级，气泡图建议用 `-np.log10()` 上色。',
        ),
    ),
    'Sankey': Recipe(
        notes='桑基图用流带宽度表达数量在多层级之间的流转。适合基因 → 功能 → 通路这类多阶段归属关系。',
        highlights=(
            '节点按层级自动分列，流带宽度与 value 成正比。',
            '颜色可分别指定节点色与流带色。',
            '悬停可查看具体流向与数值。',
        ),
        params=(
            '`links`：source / target / value / colorlink。',
            '`nodes`：节点名与节点颜色。',
        ),
        caveats=(
            '`source` / `target` 必须是节点表中的名字，索引从 0 开始。',
        ),
    ),
    'ScaBoxDen': Recipe(
        notes='散点 + 边缘箱线/密度，同时看双变量关系与各自的边际分布。适合相关分析、回归前的数据检查。',
        highlights=(
            '主图展示 x–y 关系，边缘图补充单变量分布。',
            '分组颜色会同步到边缘箱线。',
            '可叠加线性拟合线判断趋势。',
        ),
        params=(
            '`x` / `y`：两个连续变量。',
            '`group`：分组颜色，可选。',
        ),
        caveats=(
            '边际图类型可选 box / density / histogram，点太多时 density 更快。',
        ),
    ),
    'Split Violin': Recipe(
        notes='左右半小提琴把两组分布放在同一位置对比，适合配对设计或病例对照。比并排小提琴更省空间，也更容易比较峰值位置。',
        highlights=(
            '两侧各自保留真实密度轮廓。',
            '中间可叠加箱线或分位点。',
            '分组颜色语义清晰：一侧一个颜色。',
        ),
        params=(
            '`Value`：数值列。',
            '`Group`（横轴）与 `Attribute`（左右侧）。',
        ),
        caveats=(
            '两组样本量差异过大时密度宽度不可直接比较，建议同时标注 n。',
        ),
    ),
    'BubbleViz': Recipe(
        notes='四维气泡图：x、y、气泡大小、颜色，再叠加一维做逐帧动画。适合展示多年份、多国家的社会经济或组学指标。',
        highlights=(
            '`sizes` 控制气泡直径范围，避免极端值压扁其他点。',
            '`frame` 生成播放按钮与时间轴。',
            '对数坐标适合跨越多个数量级的指标。',
        ),
        params=(
            '`x` / `y` / `size`：三个数值列。',
            '`color`：分类列；`animation`：可选时间列。',
        ),
        caveats=(
            '气泡面积感知弱于长度，比较数值时优先看 tooltip 与排序。',
        ),
    ),
    'Grouped Matrix Plotting': Recipe(
        notes='分组矩阵点阵图：Y 轴实体按组排列，单元格用形状 + 颜色表达类别。适合展示基因家族、病毒片段或样本的多维分类状态。',
        highlights=(
            '同一行属于同一分组，组间留白便于扫读。',
            '形状与颜色双重编码，黑白打印也能区分。',
            '缺失类别显示为空白，不会误判为某一类。',
        ),
        params=(
            '`row` / `group`：实体与分组。',
            '`column` / `category`：列与单元格类别。',
        ),
        caveats=(
            '类别超过 6 种时建议改用颜色梯度或分面，避免形状难以分辨。',
        ),
    ),
    'CircleViz': Recipe(
        notes='多层同心环叠加环形网络：内环编码分类，外环编码数值，最外层可加径向柱。适合在一个圆内同时呈现样本分组、数值与互作关系。',
        highlights=(
            '每一环的轨道高度与间距可独立设置。',
            '环间连线能直接表达跨组关系。',
            '外圈标签沿切线旋转，长标签也不会重叠。',
        ),
        params=(
            '固定 6 列：id / name / data1–data4。',
            '`track.height`：环带高度；`start.degree`：起始角度。',
        ),
        caveats=(
            '环数过多会压缩中心区域，建议不超过 4 层。',
        ),
    ),
    'CircularBarPlot': Recipe(
        notes='环形柱（玫瑰图）把分面条形卷成圆环，中心留白放分组标签。适合基因/通路这类类别多、需要紧凑排版的场景。',
        highlights=(
            '正值与负值用双色区分，零点清晰可见。',
            '显著性星号跟随柱顶，不额外占横向空间。',
            '可切换分面条形视图，便于逐个比较绝对值。',
        ),
        params=(
            '`data`：数值列，可正可负。',
            '`type`：分组列，决定扇区划分；`num_stars` / `p_value` 控制星号。',
        ),
        caveats=(
            '环形柱的长度感知弱于直角柱，跨组比较建议同时提供分面视图。',
        ),
    ),
    'Genomic Variation Viewer': Recipe(
        notes='在基因组坐标轴上画基因结构块与 SNP 棒棒糖轨道。支持 lollipop 与 dandelion 两种模式，适合变异位点注释图。',
        highlights=(
            '基因结构块按 start–end 绘制，外显子可再细分。',
            '上、下轨可分别展示不同样本或不同方向的突变。',
            '棒棒糖高度映射 score，颜色可映射突变类型。',
        ),
        params=(
            'feature：`name` / `start` / `end`。',
            'SNP：`name` / `position` / `score`。',
        ),
        caveats=(
            '真实项目常配合专门的基因组可视化工具；下方等价的最小实现仅依赖 Plotly。',
        ),
    ),
    'Volcano Plot': Recipe(
        notes='火山图把差异倍数与显著性放在同一平面：横轴 log2FC，纵轴 -log10(p)。是差异表达分析的标准展示方式。',
        highlights=(
            '阈值线把基因分为上调、下调与不显著三类。',
            'Top-N 基因自动标注，避免标签重叠。',
            '点大小与透明度可编码表达量或可靠性。',
        ),
        params=(
            '`log2FC`：差异倍数；`pvalue` / `padj`：显著性。',
            '`FC 阈值` 与 `p 阈值`：两条阈值线。',
        ),
        caveats=(
            'p 值为 0 时 -log10 会变成无穷大，作图前建议截断到最小非零值。',
        ),
    ),
    'PCA': Recipe(
        notes='主成分分析把高维样本投影到前两个主成分，用散点观察分组与离群样本。轴标题会带解释方差比例。',
        highlights=(
            '样本在 PC1 / PC2 上的距离近似其整体表达差异。',
            '置信椭圆帮助判断分组是否可分。',
            '解释方差过低时说明前两维代表性不足。',
        ),
        params=(
            '第 1 列样本名，第 2 列可选分组，其余为数值特征。',
            '先做 z-score 标准化以消除量纲影响。',
        ),
        caveats=(
            'PCA 对离群样本敏感，建议先做标准化并检查极端值。',
        ),
    ),
    'Heatmap': Recipe(
        notes='表达矩阵热图：行是基因、列是样本，颜色编码表达量。支持行 z-score、层次聚类重排与分组注释条。',
        highlights=(
            '按行 z-score 后不同基因的幅度可比较。',
            '行/列聚类会把相似模式排在一起。',
            '分组注释条直接标出样本所属处理。',
        ),
        params=(
            '宽表：第 1 列行名，其余数值列。',
            '按行做 z-score 标准化；`row_cluster/col_cluster` 控制聚类。',
        ),
        caveats=(
            '列数超过 100 时标签会重叠，建议关闭列名或加大画布。',
        ),
    ),
    'UpSet Plot': Recipe(
        notes='UpSet 用交集柱 + 集合总量 + 成员点阵替代韦恩图，能处理 5 个以上集合。适合基因集、通路成员的重叠分析。',
        highlights=(
            '每个柱子是一个具体交集，点阵标出参与集合。',
            '左侧条形是各集合的总量。',
            '可按频率或度数排序，突出主要交集。',
        ),
        params=(
            '长表：`set` / `element`。',
            '展示规模：控制集合数量与交集数量。',
        ),
        caveats=(
            '集合数量超过 12 个时点阵会很高，建议先合并低频集合。',
        ),
    ),
    'Kaplan-Meier': Recipe(
        notes='生存曲线用阶梯线展示随时间变化的生存概率，并附风险表。适合临床试验、随访数据的组间比较。',
        highlights=(
            '删失点用竖线标记，不丢弃样本。',
            'log-rank 检验给出组间差异的 p 值。',
            '风险表显示各时间点的在访人数。',
        ),
        params=(
            '`time`：随访时间；`status`：1 = 事件，0 = 删失。',
            '`group`：分组变量。',
        ),
        caveats=(
            '分组样本量过小时置信带会很宽，解释需谨慎。',
        ),
    ),
    'Manhattan Plot': Recipe(
        notes='曼哈顿图按染色体分色并累积坐标，展示全基因组关联位点。显著位点越高越值得关注。',
        highlights=(
            '同一条染色体使用同一种颜色，便于定位。',
            '显著性阈值线帮助快速筛选。',
            '可标注 Top 位点对应的基因。',
        ),
        params=(
            '`chr` / `pos` / `pvalue` / `snp`。',
            '全基因组显著阈值线。',
        ),
        caveats=(
            '染色体需为 1–22 或 X/Y 等标准命名，混合 `chr1` 与 `1` 会导致排序错乱。',
        ),
    ),
    'Paired Tree Comparison': Recipe(
        notes='两棵系统发育树镜像并排，按叶标签配对连线，用于比较不同建树方法或不同基因的拓扑差异。支持分组着色与分支高亮。',
        highlights=(
            '叶标签对齐后，配对关系一目了然。',
            '两树可独立着色，也可按同一分组着色。',
            '分支长度可隐藏，只比较拓扑结构。',
        ),
        params=(
            '两棵 Newick / Nexus 树文件。',
            '配对表：`tree1_label` / `tree2_label`；可选分组表。',
        ),
        caveats=(
            '配对标签必须在两棵树中都存在，缺失会导致连线错位。',
        ),
    ),
}


def recipe_for(name: str) -> Recipe | None:
    return RECIPES.get(name)


PYTHON_PACKAGES: tuple[str, ...] = (
    'streamlit',
    'pandas',
    'numpy',
    'matplotlib',
    'seaborn',
    'plotly',
    'kaleido',
    'Pillow',
    'networkx',
    'scipy',
    'openpyxl',
    'python-louvain',
)


def install_python_snippet() -> str:
    return (
        "# 项目根目录执行（Windows）\n"
        "python -m venv .venv\n"
        r".\.venv\Scripts\python.exe -m pip install -r env\requirements-lock.txt" "\n"
        r".\.venv\Scripts\python.exe -m streamlit run app.py" "\n"
    )
