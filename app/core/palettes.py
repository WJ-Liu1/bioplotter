"""SCI 期刊配色板与「图 → 色板」映射（纯数据，无依赖）。

两套东西：
* ``SCI_PALETTES`` —— 10 组期刊风格配色（每组 4–5 色，已按和谐度排好序）
* ``SCI_SEMANTIC`` —— 模块语义色（volcano_up / pca_group1 / cbar_pos …）
  ``theme.py`` 会把这些键写进 10 套主题，因此模块代码只需要
  ``st.session_state.get("<key>_color", theme["<key>"])`` 就能拿到 SCI 配色。

注意：这里只放颜色常量，不 import streamlit / plotly，避免循环依赖。
"""

from __future__ import annotations

# 10 组 SCI 风格配色：No.001–No.021（编号沿用原色板目录，跳号是正常的）
SCI_PALETTES: dict[str, tuple[str, ...]] = {
    # 黑 + 藏青 + 金 + 浅灰：高对比，适合散点/火山图
    "No.001": ("#0B0B0B", "#1B2A41", "#F2A900", "#E6E6E6"),
    # 米白 + 砖红 + 深蓝灰 + 灰绿 + 麦黄：柔和百搭，适合分布类
    "No.002": ("#F1EFE6", "#D96C4F", "#2E3A4A", "#84B19C", "#E3C27A"),
    # 墨绿 + 青 + 沙黄 + 橙 + 珊瑚：分区明确，适合基因组轨道
    "No.003": ("#1F3A3D", "#2A9D8F", "#E9C46A", "#F4A261", "#E76F51"),
    # 湖蓝 + 浅蓝 + 橄榄 + 芥黄 + 灰白：适合网络类
    "No.005": ("#3AA2B6", "#8FC4D4", "#4A5D54", "#E4BA56", "#E3E9E2"),
    # 苔绿 + 棕 + 象牙 + 浅金 + 灰绿：适合矩阵/富集
    "No.009": ("#5BA790", "#866251", "#F0EAE1", "#EBCB97", "#C0CEC0"),
    # 灰绿 + 玫瑰棕 + 近白 + 中性灰 + 灰青：低饱和，适合大面积区块
    "No.012": ("#8ABBA6", "#955866", "#F3FBF8", "#DFDEDB", "#99ABA1"),
    # 青蓝 + 沙金 + 深棕 + 亮青 + 冰白：适合极坐标/曼哈顿
    "No.013": ("#279FB9", "#DABD6B", "#62573B", "#77BDCE", "#E9FCFC"),
    # 雾蓝 + 酒红 + 米色 + 冷灰 + 石板蓝：热图发散色友好
    "No.015": ("#669DBC", "#571925", "#F9EEE4", "#D0DBE0", "#708C9F"),
    # 深紫 + 陶红 + 沙 + 墨紫 + 灰粉：降维/聚类分组
    "No.018": ("#3B0B62", "#995358", "#B28F87", "#260A41", "#E2BB7E"),
    # 靛蓝 + 灰绿 + 灰米 + 紫罗兰 + 灰玫瑰：同心环
    "No.021": ("#4B66AA", "#8CB2A9", "#CABCB8", "#684277", "#93707B"),
}

# 模块语义色：主题键名与之一致（模块里的 *_color 只是 session 覆盖）
SCI_SEMANTIC: dict[str, str] = {
    # 火山图：上调 / 下调 / 不显著 / 阈值线
    "volcano_up": "#D96C4F",
    "volcano_down": "#3AA2B6",
    "volcano_ns": "#A8B0B8",
    "volcano_thr": "#7A8794",
    # PCA：分组 + 椭圆描边
    "pca_group1": "#D96C4F",
    "pca_group2": "#2E3A4A",
    "pca_group3": "#84B19C",
    "pca_group4": "#E3C27A",
    "pca_ellipse": "#7A8794",
    # 热图：低 / 中 / 高
    "heatmap_low": "#669DBC",
    "heatmap_mid": "#F9EEE4",
    "heatmap_high": "#571925",
    # UpSet：交集柱 / 集合总量 / 活跃点 / 非活跃点
    "upset_bar": "#2E3A4A",
    "upset_setbar": "#84B19C",
    "upset_active": "#D96C4F",
    "upset_inactive": "#C8CDD4",
    # Kaplan-Meier：4 组 + 删失
    "km_g1": "#D96C4F",
    "km_g2": "#3AA2B6",
    "km_g3": "#5BA790",
    "km_g4": "#E3C27A",
    "km_censor": "#2E3A4A",
    # Manhattan：奇 / 偶染色体 + 显著点
    "manhattan_odd": "#2E3A4A",
    "manhattan_even": "#8FC4D4",
    "manhattan_sig": "#E76F51",
    # BubbleViz：单色 / 低 / 高
    "bubble_point": "#3AA2B6",
    "bubble_low": "#8FC4D4",
    "bubble_high": "#2E3A4A",
    # 分组矩阵：3 类别 + 空值 + 边框
    "gmp_cat1": "#5BA790",
    "gmp_cat2": "#EBCB97",
    "gmp_cat3": "#D96C4F",
    "gmp_empty": "#F0EAE1",
    "gmp_border": "#8A8F98",
    # CircleViz：内环 5 类 + 中/外环渐变 + 连线 + 中心
    "circle_cat1": "#4B66AA",
    "circle_cat2": "#8CB2A9",
    "circle_cat3": "#CABCB8",
    "circle_cat4": "#684277",
    "circle_cat5": "#93707B",
    "circle_mid_low": "#E3E9E2",
    "circle_mid_mid": "#8FC4D4",
    "circle_mid_high": "#3AA2B6",
    "circle_out_low": "#F9EEE4",
    "circle_out_mid": "#E3C27A",
    "circle_out_high": "#D96C4F",
    "circle_link": "#8A8F98",
    "circle_center": "#2E3A4A",
    "circle_bar": "#4B66AA",
    # 环形柱：正 / 负 / NA / 星号
    "cbar_pos": "#FB9A99",
    "cbar_neg": "#74A9CF",
    "cbar_na": "#7F7F7F",
    "cbar_star": "#FF0000",
    # 基因轨道：结构块 / SNP / 上轨 / 下轨
    "genvar_feature": "#1F3A3D",
    "genvar_snp": "#2A9D8F",
    "genvar_upper": "#2A9D8F",
    "genvar_lower": "#E76F51",
    "genvar_label": "#F9EEE4",
}

# 每个模块主打色板（用于首页卡片、预览图与后续「按色板切换」功能）
PLOT_PALETTE: dict[str, str] = {
    "Volcano Plot": "No.001",
    "PCA": "No.018",
    "Heatmap": "No.015",
    "UpSet Plot": "No.009",
    "Kaplan-Meier": "No.015",
    "Manhattan Plot": "No.013",
    "BubbleViz": "No.002",
    "Grouped Matrix Plotting": "No.009",
    "CircleViz": "No.021",
    "CircularBarPlot": "No.013",
    "Genomic Variation Viewer": "No.003",
    "Arc Diagram": "No.005",
    "Hierarchical Edge Bundling": "No.005",
    "Chord Diagram": "No.005",
    "Node-link Diagram": "No.005",
    "Sankey": "No.005",
    "Raincloud Plot": "No.002",
    "Beeswarm": "No.002",
    "Split Violin": "No.002",
    "ScaBoxDen": "No.002",
    "Pirate Plot": "No.002",
    "Mantel Test": "No.001",
    "GO Enrichment": "No.009",
}

# 12 个旧模块（非 P0 的 11 个）的 SCI 语义色
SCI_LEGACY: dict[str, str] = {
    # 网络类
    "sci_network_primary": "#3AA2B6",
    "sci_network_light": "#8FC4D4",
    "sci_network_dark": "#4A5D54",
    "sci_network_accent": "#E4BA56",
    "sci_network_pale": "#E3E9E2",
    # 分布类
    "sci_dist_1": "#D96C4F",
    "sci_dist_2": "#2E3A4A",
    "sci_dist_3": "#84B19C",
    "sci_dist_4": "#E3C27A",
    "sci_dist_5": "#8FC4D4",
    "sci_dist_6": "#C98A5E",
    # Mantel
    "sci_mantel_low": "#669DBC",
    "sci_mantel_mid": "#F9EEE4",
    "sci_mantel_high": "#D96C4F",
    # GO 富集
    "sci_go_1": "#5BA790",
    "sci_go_2": "#EBCB97",
    "sci_go_3": "#D96C4F",
    "sci_go_low": "#669DBC",
    "sci_go_mid": "#F9EEE4",
    "sci_go_high": "#D96C4F",
}

# 分类色序列：分布类 / 网络类（模块内直接按序取色）
SCI_DIST_COLORS: tuple[str, ...] = ("#D96C4F", "#2E3A4A", "#84B19C", "#B28F87", "#8FC4D4", "#C98A5E")
SCI_NETWORK_COLORS: tuple[str, ...] = ("#3AA2B6", "#8FC4D4", "#4A5D54", "#E4BA56", "#B28F87", "#93707B")


# GMP 分组色块专用：取自 No.009 / No.002 / No.015 / No.012 的低饱和组合
GMP_GROUP_COLORS: tuple[str, ...] = (
    "#5BA790",  # 苔绿
    "#EBCB97",  # 浅金
    "#8ABBA6",  # 灰绿
    "#D96C4F",  # 砖红
    "#669DBC",  # 雾蓝
    "#B28F87",  # 灰玫瑰
)

DEFAULT_PALETTE = "No.002"


def palette_for(name: str) -> tuple[str, ...]:
    """返回模块主打色板的颜色元组；未登记时回落到 No.002。"""
    return SCI_PALETTES.get(PLOT_PALETTE.get(name, DEFAULT_PALETTE), SCI_PALETTES[DEFAULT_PALETTE])


def palette_by_id(palette_id: str) -> tuple[str, ...]:
    """按色板编号取色（供后续「切换色板」功能复用）。"""
    return SCI_PALETTES.get(palette_id, SCI_PALETTES[DEFAULT_PALETTE])
