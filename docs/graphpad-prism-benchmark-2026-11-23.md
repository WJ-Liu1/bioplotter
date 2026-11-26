# BioPlotter × GraphPad Prism 竞品对标与改进建议

> 对标日期：2026-11-23  
> 对标对象：GraphPad Prism（官网当前版本页与定价页） vs. `python_vis_app_styled/` 中的 BioPlotter  
> 调研方式：GraphPad 官网功能页/定价页 + BioPlotter 源码、README、既有站点评审、1440px 首页与绘图页截图  
> 结论一句话：**Prism 是“桌面端统计+绘图+发表”一体化工具，BioPlotter 是“浏览器端组学专用图形工作台”；两者不是替代关系，BioPlotter 应补齐“可信、可复现、可发表、可协作”四块短板，而不是复制 Prism 的全部统计功能。**

---

## 0. 结论先行

- **GraphPad Prism 的真正护城河**不是“能画图”，而是：结构化数据表 → 统计检验 → 假设检查 → 结果解释 → 出版级图 → 项目文件联动 → 协作分享，形成闭环。
- **BioPlotter 的真正优势**不是“免费”，而是：24 个组学专用图形、浏览器零安装、中文界面、按数据形状选图、示例数据开箱即用。这些是 Prism 官方功能页没有重点覆盖的领域。
- **最该优先补的三件事**：
  1. **项目包**：保存/恢复/分享“数据 + 参数 + 图 + 方法 + 版本”，解决刷新即丢失的问题。
  2. **统计与方法说明层**：每个图明确 n、检验方法、多重比较校正、效应量、置信区间、假设与引用，并能一键复制 Methods 句子。
  3. **导出前检查 + 期刊模板**：尺寸、分辨率、颜色空间、字体、透明背景、矢量/位图、离线 HTML，一次检查完再下载。
- **建议定位**：  
  **“浏览器里的组学图形工作台：从数据到可发表图，参数、统计与出处都可追溯。”**  
  不要写成“免费版 GraphPad”，否则用户会拿 Prism 的统计深度来要求你。

---

## 1. GraphPad Prism 是什么

### 1.1 产品定位

GraphPad 官方对 Prism 的定位是：**“The preferred analysis and graphing solution purpose-built for scientific research.”**  
它是一个 Windows / macOS 桌面软件，核心用户是湿实验科学家、临床研究者、药理学/生理学/神经科学等需要做统计并发表图的科研人员。Prism Cloud 负责项目共享、查看与讨论，但核心统计与作图仍在桌面端完成。

### 1.2 核心能力

| 能力块 | GraphPad Prism 的官方能力 |
| --- | --- |
| 数据组织 | 8 种数据表：XY、Column、Grouped、Contingency、Survival、Parts of whole、Multiple variables、Nested；支持表内公式、数据转换、子集筛选、宽表/长表重构 |
| 统计检验 | t 检验、Mann-Whitney、KS、Wilcoxon、one/two/three-way ANOVA、N-way ANOVA、重复测量/混合效应、非参数 ANOVA、卡方/Fisher、相对风险/OR、多重比较、效应量、置信区间 |
| 回归与建模 | 线性/非线性回归、105 个内置方程、自定义方程、全局拟合、稳健回归、异常值识别、AICc 模型比较、logistic 回归、GLM、Deming 回归 |
| 生存分析 | Kaplan-Meier、log-rank、趋势检验、Cox 比例风险回归、风险表 |
| 多变量分析 | PCA、K-means、层次聚类、树状图、置信椭圆/凸包、多变量图 |
| 统计辅助 | 样本量与检验效能、假设检查清单、效应量报告、统计指南与教程 |
| 图形 | 散点、柱状、分组图、生存曲线、气泡图、小提琴图、estimation plot、平滑样条、显著性星号、自动柱标、散点+均值/误差条组合 |
| 导出 | 文件类型、分辨率、透明度、尺寸、RGB/CMYK，面向期刊投稿的出版级导出 |
| 协作 | Prism Cloud 工作区、项目共享、评论/讨论、版本、角色权限（viewer 到 content manager） |
| 互操作 | CSV、PNG、JSON 等通用格式；与 OMIQ、FCS Express、LabArchives、Luma 等集成 |

### 1.3 商业模式与价格（官网 2026-11-23）

> 以下均为美元标价，具体以 GraphPad 官网和地区/机构协议为准。

| 方案 | 学术价 | 商业价 | 说明 |
| --- | ---: | ---: | --- |
| 个人订阅 Standard | $265/年 | $530/年 | 统计、绘图、可视化、Prism Cloud |
| 个人订阅 Pro | $360/年 | $720/年 | 增加 Multiple Variables、聚类、树状图、置信椭圆、多因子 ANOVA、表内公式 |
| 学生订阅 | $142/年 | $213/年 | Standard / Pro |
| 月度订阅 | $50/月 | $75/月 | 短期项目 |
| 永久许可 Prism 11 | $1,800/许可 | $4,200/许可 | 无后续升级、无未来支持、无协作/管理功能 |

Prism 提供 30 天免费试用，无需信用卡。

### 1.4 Prism 真正值得学习的地方

1. **统计不是“给一个 p 值”**：它把“选检验 → 检查假设 → 给出结果 → 报告效应量/置信区间 → 画到图上 → 生成方法文字”串成流程。
2. **项目文件是核心资产**：数据、分析、图、布局互相关联，改数据或改分析，结果和图自动更新。
3. **出版导出是产品能力**：不是“能下载 PNG”，而是尺寸、分辨率、透明、RGB/CMYK、默认模板一起解决。
4. **教育型产品**：Graph Portfolio、教程、示例数据、统计指南降低了用户的学习成本。
5. **协作围绕项目**：Prism Cloud 让“项目”成为共享单元，而不是共享一张图片。

---

## 2. BioPlotter 当前状态

### 2.1 已经做得好的部分

- **24 个原生图形模块 / 6 个分类 / 34 份示例数据**，全部是站内 Plotly 实现，不依赖 R、Node、iframe 或外部服务。
- **组学专用图形覆盖广**：Arc、HEB、Chord、Node-link、Sankey、Raincloud、Beeswarm、Split Violin、ScaBoxDen、Pirate、BubbleViz、Grouped Matrix、CircleViz、CircularBar、Mantel、GO、Volcano、PCA、Heatmap、UpSet、Genomic Variation、Kaplan-Meier、Manhattan、Paired Tree。
- **数据形状适配**：宽矩阵、长表、边表、生存表、集合表、树文件；CSV/TSV/TXT/XLSX；列名自动识别 + 手动映射；多文件模块支持示例数据打包下载。
- **浏览器零安装**：Streamlit 单进程，`streamlit run app.py` 即可；对用户没有安装 R/Python 包的门槛。
- **中文 UX 与响应式**：中文界面、10 套主题、1440/1024/768 三档布局、移动端侧栏修正。
- **交互与导出基础**：左侧参数、生成按钮、状态条、数据预览、使用说明三个 Tab；HTML/JSON/PNG/SVG/PDF；期刊尺寸预设 85/114/170mm、300/600 dpi、透明 PNG。
- **工程基础**：模块契约统一（`controls` + `build`）、示例路径稳健、预览 SVG 带无障碍标签、已有 AppTest/UI probe/截图回归脚本。

### 2.2 当前能力边界

| 维度 | 现状 | 影响 |
| --- | --- | --- |
| 统计 | 统计分散在各模块：Raincloud 有 t/Wilcoxon/ANOVA/Kruskal，KM 有 log-rank，Mantel 有置换 p，PCA 有方差解释与置信椭圆，Volcano 可读 padj 列 | 没有统一“统计层”；缺少假设检查、效应量、置信区间、多重比较校正、方法说明；用户容易把“画出来的 p 值”当成完整统计结论 |
| 项目保存 | 只有 `session_state`；刷新/关闭即丢失；导出 JSON 只是图配置，不能一键恢复完整工作 | 无法复现、无法交接、无法版本管理；这是与 Prism 差距最大的地方之一 |
| 协作 | 无账户、无项目、无分享链接、无评论、无版本 | 目前是单机工具定位；团队使用需要靠截图/文件传来传去 |
| 导出 | Plotly 静态导出依赖 `kaleido` + 本机 Chrome；无 CMYK；HTML 使用 CDN；字体/文字可编辑性未做检查 | 投稿场景可能失败或不符合期刊要求；离线分享可能缺 Plotly JS |
| 数据互操作 | 主要是表格 + Newick/Nexus；缺少 h5ad、GCT、VCF、BED、mtx、AnnData/Seurat 等组学原生格式 | 对生信用户来说，仍要多一步“先导成 CSV” |
| 扩展方式 | 新增模块要改 6 处注册点；没有 Python API/CLI/插件机制 | 站点内部扩展方便，但外部开发者/团队复用成本高 |
| 信任与验证 | 有示例、有测试脚本，但没有“统计结果对照 R/Prism 的验证页”，没有方法/引用/版本说明 | 审稿人或统计审阅者会追问“这个 p 值怎么算的” |

### 2.3 已知工程问题（来自现有评审）

- Sankey 节点标签仍可能压在节点块上（Plotly Sankey 标签定位限制）。
- 24 张首页预览缩略图的视觉风格尚未完全统一。
- 个别模块仍残留中英文混排（如 Sankey 的状态/控件）。
- `CircularBarPlot` 的 trace 数与测试预算有偏差（R 对齐新增分隔线/刻度圆导致）。
- 依赖未锁版本、测试入口仍是脚本、无 CI/Dockerfile（长期维护风险）。

这些不是产品定位问题，但会影响“专业感”和“可维护性”，建议在 P0/P1 中一并处理。

---

## 3. 对比矩阵

> 评分是产品视角的“相对强弱”，不是功能数量比赛。

| 维度 | GraphPad Prism | BioPlotter | 判断 |
| --- | --- | --- | --- |
| 产品形态 | Windows/macOS 桌面软件 + Prism Cloud | 浏览器端 Streamlit 应用 | 不同赛道；BioPlotter 零安装，Prism 离线/本地数据更稳 |
| 目标用户 | 湿实验、临床、药理等需要统计的科研人员 | 生信/组学/多组学可视化用户 | BioPlotter 应服务“组学图形”，不要泛化成通用统计软件 |
| 数据输入 | 8 种结构化数据表，表内公式、重构、2048 列 | CSV/TSV/TXT/XLSX，自动/手动列映射，多文件模块 | Prism 强在数据模型；BioPlotter 强在文件灵活性和组学形状 |
| 图形广度 | 经典科研图 + 气泡/小提琴/estimation/平滑样条 | 24 个组学专用图，含 UpSet、Manhattan、Sankey、Chord、Arc、HEB、环形网络、配对树 | **BioPlotter 明显更强**；这是核心差异化 |
| 图形深度/编辑 | 实时属性编辑、直接操作、格式刷、模板 | 左侧参数 + 主题/配色 + 部分模块高级选项 | Prism 更强；BioPlotter 参数多但层级和实时反馈还不够 |
| 统计分析 | 非常深，覆盖假设、效应量、校正、建模 | 轻量、分散、以可视化为目的 | Prism 压倒性领先；BioPlotter 不应硬拼全量统计 |
| 统计可信度/解释 | 假设检查、方法说明、教程、指南 | 有计算但缺方法说明、校正、验证页 | 这是 BioPlotter 最大的“信任缺口” |
| 项目保存/复现 | 项目文件，数据/分析/图联动，Cloud 版本 | session_state；刷新丢失；JSON 仅图配置 | Prism 强；BioPlotter 必须补“项目包” |
| 出版导出 | RGB/CMYK、尺寸、分辨率、透明、默认模板 | 85/114/170mm、300/600dpi、透明 PNG、SVG/PDF（kaleido+Chrome） | Prism 更强；BioPlotter 可做到“够用且可检查” |
| 协作/分享 | Prism Cloud、角色、评论、版本 | 无 | Prism 强；BioPlotter 可先做“只读快照 + 项目包”，再做账户 |
| 学习/上手 | 教程、Graph Portfolio、示例、统计指南 | 3 步引导、按数据形状筛选、难度标签、示例数据 | Prism 内容更体系化；BioPlotter 中文和组学场景更贴近 |
| 性能/大数据 | 桌面端优化，适合较大数据表 | Plotly/浏览器渲染，200×20 热图没问题，更大数据需优化 | Prism 更稳；BioPlotter 需要缓存、降采样、WebGL、进度提示 |
| 移动/跨平台 | 桌面为主，Cloud 可查看 | 浏览器 + 响应式，手机可看 | BioPlotter 更强；但手机端更适合“查看/分享”，不适合精调 |
| 中文/本地化 | 以英文为主 | 原生中文 | BioPlotter 明显更强 |
| 成本 | 订阅/永久许可，学术价仍不低 | 自托管/开源（需明确 License） | BioPlotter 有明显获客优势 |
| 扩展/集成 | 封闭但成熟的生态与集成 | 模块化好，但缺 API/CLI/插件 | 两者各有短板；BioPlotter 可用 API/CLI 建立平台优势 |
| 生态/信任 | 论文中广泛使用，品牌强 | 新项目，缺引用/验证/社区 | Prism 强；BioPlotter 需要“可验证”来换信任 |

---

## 4. 关键差异解读

### 4.1 Prism 强在“闭环”，不是单点功能

Prism 的用户路径是：

```text
数据表 → 选择分析 → 检查假设 → 结果/效应量/CI → 图 → 方法文字 → 项目文件 → 分享/投稿
```

BioPlotter 目前的路径是：

```text
上传表格 → 映射列 → 调参数 → 生成图 → 导出图片/HTML
```

差别不在“图好不好看”，而在**用户能不能放心地把图放进论文，并且三个月后还能复现**。这就是为什么“项目包 + 方法说明 + 统计校正”比“再加 5 种图”更重要。

### 4.2 BioPlotter 强在“组学图形的广度”

Prism 官方功能页重点讲的是经典统计图、气泡图、小提琴图、estimation plot、平滑样条等；UpSet、Manhattan、Sankey、Chord、Arc、HEB、环形网络、配对树对比并不是它的核心叙事。  
BioPlotter 的 24 个模块里，很多是生信用户“找不到现成工具、只能写 R/Python”的图。这是非常清晰的差异化。

建议在首页把这句话讲透：

> “不用写 R/Python，也能做出 UpSet、Manhattan、Sankey、Chord、环形网络、配对树对比等组学专用图。”

### 4.3 不要照搬 Prism

- **不要做完整统计套件**：t 检验/ANOVA/回归/生存/混合模型全做一遍，投入大、验证难、容易出错。
- **不要做桌面电子表格**：Streamlit 不适合复刻 Prism 的数据表编辑体验。
- **不要做通用绘图**：通用散点/柱状/折线已经是红海，Prism/Origin/ggplot2/Excel 都很强。
- **不要把 AI 当统计权威**：AI 可以帮写方法文字、解释参数，但统计结果必须由可验证的计算库产生。

### 4.4 最大风险

1. 用户把“图上的 p 值/星号”当成完整统计结论，但站点没有说明检验方法、样本量、校正方式。
2. 用户刷新页面后参数丢失，无法复现，最后放弃。
3. 导出 PNG/SVG/PDF 在投稿时失败，或不符合期刊尺寸/颜色要求。
4. 用户把你的图和 Prism 的图放在一起比较，发现“统计解释”不足，失去信任。

---

## 5. 改进建议（按优先级）

### P0：1–2 周，低成本、高回报

#### P0-1 项目包：保存 / 恢复 / 分享

这是最值得先做的事，直接对标 Prism 的“项目文件”优势。

**建议格式**：`.bioplot.zip`

```text
project.bioplot.zip
├── manifest.json        # app 版本、模块、参数、主题、配色、创建时间、数据哈希
├── data/                # 原始数据 + 清洗后数据（可选）
├── figure.json          # Plotly figure 配置
├── preview.png          # 当前预览
├── methods.md           # 方法/统计说明（可复制）
└── README.txt           # 如何打开、版本要求、引用
```

**交互要求**：

- 顶部工具栏增加“保存项目”“打开项目”“另存为”。
- 打开项目时校验 `app_version` 和模块名；版本不兼容给出明确提示。
- 保存时记录数据文件名、列映射、参数、主题、配色、生成时间。
- 分享时可选“只读快照”（HTML + PNG + methods）或“完整项目包”。

**验收标准**：

- 刷新页面后能恢复上次项目。
- 同一项目包在另一台机器打开，图与参数一致。
- `methods.md` 中的 n、检验、校正、版本、时间可追溯。

#### P0-2 每个图的“方法与统计”面板

在每个绘图页增加第四个 Tab 或右侧抽屉：**方法与统计**。

建议字段：

| 字段 | 示例 |
| --- | --- |
| 数据规模 | n = 3,000 genes；上调 1,203 / 下调 942 / 不显著 855 |
| 检验方法 | Welch t-test / Mann-Whitney / log-rank / permutation test |
| 多重比较 | Benjamini-Hochberg FDR；显著性阈值 q < 0.05 |
| 效应量 | Cohen's d / HR / R² / log2FC |
| 置信区间 | 95% CI |
| 假设/限制 | 独立性、正态性、方差齐性、比例风险假设等 |
| 软件/版本 | BioPlotter vX.Y；SciPy x.y；Plotly x.y |
| 引用 | 方法引用 + 软件引用 |
| 一键复制 | “Copy methods sentence” |

**关键原则**：没有做的统计，不要写成“已做”。用“未计算/需上游提供”明确标注。

**验收标准**：

- 每个模块至少给出“当前图做了什么/没做什么”。
- 用户能复制一段可直接放进论文 Methods 的中英文句子。
- 统计结果有对应的测试或引用依据。

#### P0-3 导出前检查 + 期刊模板

在“导出结果”里增加一个 **Export Check** 区块：

- 画布尺寸（mm / inch）
- 输出分辨率（300/600 dpi）
- 颜色空间（RGB；CMYK 标注“暂不支持”）
- 字体与最小字号
- 透明背景
- 矢量/位图
- 离线 HTML（内联 Plotly JS，不依赖 CDN）
- 文件名规范

**建议模板**：

- 单栏 85mm、1.5 栏 114mm、双栏 170mm（已有）
- 增加 Nature/Cell/Science 等常见模板（具体尺寸以期刊指南为准）
- 增加“自定义宽高 + 锁定纵横比”

**验收标准**：

- 导出前能看到“预计像素尺寸”和“是否符合当前模板”。
- 静态导出失败时，明确告诉用户是 `kaleido` 还是 Chrome 的问题，并给出替代方案。
- HTML 可选择“依赖 CDN”或“完全离线”。

#### P0-4 修复已知问题与一致性

- Sankey 节点标签：节点 id 与显示 label 分离；节点多时增加左右 margin；hover 显示完整信息；必要时提供“标签避让/隐藏”开关。
- 24 张首页预览统一构图规则：固定 viewBox、统一线宽、主色 + 辅助色、主体占画布 70–80%。
- 统一中英文术语：模块 = 图形，对象 = 图表，动作 = 生成图形；TRUE/FALSE 改 toggle。
- `CircularBarPlot` trace 预算与测试对齐。
- 锁定 `requirements` 版本，补 `pytest` 入口和 CI。

#### P0-5 一键复现示例

每个模块提供“示例数据 + 推荐参数 + 预期截图 + 方法说明”的复现包。  
示例数据使用固定随机种子；截图回归与示例参数绑定，避免“示例看起来很好，换成自己的数据就崩”。

---

### P1：1–3 个月，形成差异化

#### P1-1 统一统计层

不要在每个模块各写一套统计。建议建立 `app/core/stats.py`：

- 统一封装 `scipy.stats`、`statsmodels`、`lifelines`（生存分析）。
- 统一多重比较校正：BH/FDR、Bonferroni、Holm。
- 统一效应量：Cohen's d、Hedges' g、HR、R²、Cramér's V 等。
- 统一置信区间与 bootstrap。
- 统一假设检查：正态性、方差齐性、比例风险。
- 统一输出结构：`StatResult(method, statistic, p, ci, effect_size, n, warnings, citation)`。

**验证方式**：

- 用 R/Prism 对同一份示例数据跑一遍，结果写入 `tests/reference/`。
- 每个统计函数有容差断言（p 值、CI、效应量）。
- 站点增加“验证与版本”页面，公开方法、公式、引用、测试结果。

#### P1-2 模块级增强

| 模块 | 建议增加 | 价值 |
| --- | --- | --- |
| Volcano | padj/FDR 阈值、q 值 vs p 值切换、Top-N 策略、阈值预设、显著基因表下载、Methods 句子 | 让“火山图”从展示图变成可解释的差异分析结果 |
| Kaplan-Meier | HR、中位生存期、风险表、删失说明、log-rank 细节、Cox 单变量/多变量（可选） | 直接对标 Prism 的生存分析叙事 |
| PCA | Scree plot、loadings、biplot、置信椭圆方法说明、异常样本标记 | 让 PCA 不只是散点图 |
| Heatmap | 行/列注释条、聚类距离/方法、Z-score 说明、缺失值策略、导出尺寸 | 提升组学热图的可解释性 |
| UpSet | 集合排序、交集过滤、百分比、颜色映射、交集表下载 | 让 UpSet 更适合论文 |
| Manhattan | QQ plot、genomic inflation factor λ、lead SNP 表、基因组版本、阈值说明 | 让 GWAS 图更专业 |
| GO Enrichment | 支持 clusterProfiler/Enrichr 输出、Top-N、分面、点大小图例、校正后 p 值说明 | 贴近真实富集分析流程 |
| Sankey | 标签避让、节点分组、数值格式、颜色语义、导出尺寸 | 修复当前最明显的视觉问题 |
| Paired Tree | 支持 bootstrap/支持度、分支长度、叶对齐、颜色图例 | 提升系统发育图专业性 |
| Raincloud | 多重比较校正、效应量、样本量标注、配对/非配对说明 | 让分布比较图有统计支撑 |
| Mantel | 偏 Mantel、距离方法、置换次数、FDR | 让检验结果更完整 |
| Circular/Chord/Arc/HEB | 统一布局预设、标签避让、导出尺寸、颜色盲友好 | 提升组学网络图的稳定性 |
| Genomic Variation | GFF3/BED 导入、转录本异构体、区域缩放、SNP 密度 | 从“示意图”升级为“基因组浏览器轻量版” |

#### P1-3 “数据形状/实验类型 → 推荐图”向导

首页在现有“按数据形状筛选”的基础上，增加 **实验类型入口**：

- 差异表达（RNA-seq/DESeq2/edgeR）→ Volcano、Heatmap、PCA、GO
- 生存/临床 → Kaplan-Meier、Cox、森林图（未来）
- GWAS → Manhattan、QQ、区域图
- 微生物组/物种组成 → Stacked bar、Heatmap、PCA/PCoA、Mantel
- 网络/通路 → Chord、Sankey、Arc、HEB、Node-link
- 集合/重叠 → UpSet
- 系统发育 → Paired Tree

每一步给出“需要什么列、输出什么图、常见坑”，并链接到示例数据。

#### P1-4 导入/互操作

优先支持生信用户真实拿到的格式：

- `h5ad`（AnnData/Scanpy）
- GCT / CLS（GSEA）
- VCF / BED（基因组）
- mtx（10x）
- Newick/Nexus（已有）
- DESeq2/edgeR 结果表
- clusterProfiler/Enrichr 富集表

同时提供“导出为 GraphPad/Excel 友好 CSV”，让用户可以在 BioPlotter 探索、在 Prism 做统计，形成互补而不是对抗。

#### P1-5 Python API + CLI 批量模式

把站点能力产品化：

```python
import bioplotter

fig = bioplotter.render(
    module="volcano",
    data="deg.csv",
    params={"log2fc": 1.0, "p": 0.05, "label_top": 10},
    theme="Light",
)
fig.write_image("volcano.pdf")
```

```bash
bioplotter batch config.yaml --out results/
```

用途：批量出图、CI 回归、团队模板、Jupyter 集成、自动化报告。

#### P1-6 性能与大数据

- 对 `build()` 纯计算做缓存（module + sorted params + data hash）。
- 大散点使用 WebGL（`Scattergl`）。
- 热图/Manhattan 做服务端降采样或分块渲染。
- 超过阈值时给出“样本/行数/列数”提示，而不是卡死。
- 重计算放到后台任务，前端显示进度。

---

### P2：3–6 个月，平台化

#### P2-1 协作与账户

分两步：

1. **先做无账户分享**：只读快照链接（HTML + PNG + methods），可设过期时间/密码。
2. **再做账户与项目**：项目列表、版本、评论、团队模板、权限。

如果不想自建后端，可以先接对象存储 + 签名 URL；或者提供“导出项目包，放到机构网盘”的方案。

#### P2-2 团队模板与期刊样式库

- 团队统一的配色、字体、字号、线宽、图注风格。
- 期刊模板库：单栏/双栏、最小字号、颜色空间、文件格式。
- “一键应用到所有图”。

#### P2-3 插件 SDK / 社区画廊

- 模块注册接口：`register_module(name, controls, build, preview)`。
- 第三方可以贡献新图，不必改 `app.py`。
- 社区画廊展示示例数据、参数、预期截图、引用。

#### P2-4 可选 AI 助手（有边界）

适合做：

- 根据数据列推荐图形和参数。
- 生成 Methods 草稿、图注草稿。
- 解释“这个 p 值/HR/CI 是什么意思”。

不适合做：

- 替代统计计算。
- 在没有假设检查的情况下给“显著性结论”。
- 自动编造引用。

---

## 6. 首页与文案建议

### 6.1 Hero

现在：

> 把组学数据，变成可读、可发表的图

建议增加“差异化 + 信任”信息：

> **把组学数据，变成可读、可发表、可复现的图**  
> 24 个组学专用图形 · 浏览器零安装 · 参数/统计/出处可追溯

### 6.2 增加“适合 / 不适合”说明

这不会削弱产品，反而会建立信任：

- **适合**：组学探索性可视化、论文主图/附图、教学演示、批量出图、跨团队分享。
- **不适合**：复杂实验设计的主统计分析、需要完整假设检查/混合模型/多重比较的临床统计。  
  这类需求建议用 Prism/R/SPSS，或把 BioPlotter 作为“可视化前端”。

### 6.3 增加“可信”标签

在导出面板/图注附近显示：

- 方法：Welch t-test
- 校正：BH FDR
- n：3 vs 3
- 版本：BioPlotter vX.Y
- 引用：可复制

这比再加 10 个主题更能提升专业感。

---

## 7. 建议的衡量指标

| 目标 | 指标 |
| --- | --- |
| 激活 | 首次访问到生成第一张图 < 3 分钟；示例数据→上传自己数据的转化率 |
| 留存 | 7 日/30 日回访；每人保存项目数；每人导出次数 |
| 发表 | SVG/PDF 导出占比；Methods 复制率；期刊模板使用率 |
| 信任 | 统计验证测试通过率；用户统计问题数量；引用/方法说明查看率 |
| 性能 | 生成图 p95 时间；导出成功率；大文件失败率 |
| 协作 | 分享链接打开率；评论数；团队项目数（P2） |

---

## 8. 优先级总表

| 优先级 | 事项 | 影响 | 成本 | 建议 |
| --- | --- | --- | --- | --- |
| P0 | 项目包保存/恢复/分享 | 极高 | 低-中 | 立刻做 |
| P0 | 方法与统计面板 | 极高 | 低 | 立刻做 |
| P0 | 导出前检查 + 期刊模板 | 高 | 低-中 | 立刻做 |
| P0 | 修复 Sankey/预览/术语/依赖 | 中-高 | 低 | 立刻做 |
| P1 | 统一统计层 + R/Prism 对照验证 | 极高 | 中-高 | 3 个月内 |
| P1 | 数据形状/实验类型向导 | 高 | 中 | 3 个月内 |
| P1 | h5ad/GCT/VCF/BED 等导入 | 高 | 中 | 3 个月内 |
| P1 | Python API/CLI 批量 | 高 | 中 | 3 个月内 |
| P1 | 性能优化（缓存/WebGL/降采样） | 中-高 | 中 | 持续 |
| P2 | 账户/协作/版本 | 高 | 高 | 6 个月内评估 |
| P2 | 团队模板/期刊样式库 | 高 | 中 | 6 个月内 |
| P2 | 插件 SDK/社区画廊 | 中 | 中-高 | 6 个月内 |
| P2 | AI 助手（有边界） | 中 | 中 | 最后做 |

---

## 9. 一句话战略

**不要做“免费的 GraphPad Prism”。**  
做 **“组学专用、浏览器端、可复现、可发表的图形工作台”**：  
用 Prism 的“严谨与闭环”补自己的短板，用自己的“组学图形广度 + 零安装 + 中文”打 Prism 覆盖不到的场景。

---

## 10. 资料来源

- GraphPad Prism 功能页：https://www.graphpad.com/features
- GraphPad Prism 定价页：https://www.graphpad.com/how-to-buy/
- GraphPad 官网首页：https://www.graphpad.com/
- BioPlotter 源码与文档：`python_vis_app_styled/README.md`、`docs/site-review-2026-11-21.md`、`docs/prd-native-fusion.md`
- BioPlotter 截图：`scripts/_p0_shots/1440-light-home.png`、`scripts/_p0_shots/1440-light-plot.png`、`scripts/_ui_shots/export_panel.png`

> 价格、版本与功能以 GraphPad 官网为准；本文价格为 2026-11-23 访问官网时的美元标价，地区/机构协议可能不同。
