# BioPlotter 生物数据可视化工作台

基于 Streamlit + Plotly 的**单进程**在线作图平台，面向生物信息与组学数据。内置 **24 个图形模块 / 6 个分类 / 35 份示例数据**，全部为站内原生 Plotly 实现——不依赖任何外部服务或前端框架。

## 功能一览

- **24 个原生图形模块**，分 6 类：网络关系 4 · 分布比较 6 · 矩阵与热图 3 · 环形与极坐标 2 · 统计与富集 4 · 基因组与生存 4
- 每个模块内置示例数据，载入即出图；参数在左侧实时调整
- 支持 CSV / TSV / TXT / XLSX 上传，列名自动识别 + 手动映射
- 默认 **Paper · 纸白** 主题（冷纸白 + 墨绿单强调色）；界面上另提供 Slate / Warm / Midnight，其余旧主题保留键值以兼容历史项目包
- 绘图页分「图形 / 数据预览 / 使用说明」三个 Tab
- **图形文档（首页内嵌）**：点击首页任意卡片，左侧卡片列收窄、右侧展开「说明 / 数据 / Python 代码 / 环境」；示例数据可预览下载（整图 ZIP / 全部 ZIP），Python 示例与完整模块源码支持一键 Copy
- 绘图页工具栏收敛为四个主操作：**生成 / 设置与导出 / 数据 / 帮助**；下方用一行紧凑标签显示「状态、样式来源、数据规模、更新时间、外观未应用」
- **设置与导出**：统一字体、字号、标题、图例、网格线、期刊画布、DPI、透明背景与文件名；支持 HTML / JSON / PNG / SVG / PDF，静态导出需可选依赖 kaleido
- **项目包**：保存 / 恢复 `.bioplot.zip`（原始数据、示例快照、参数、主题与图形配置）
- **可复现随机种子**：Pirate、Raincloud、Beeswarm、ScaBoxDen、Mantel、Genomic Variation 的随机布局可固定并随项目包保存
- 顶栏吸顶导航 + 6 类侧栏目录树；1440 / 1024 / 768 三档响应式，无横向滚动

## 快速开始

```bash
python -m venv .venv

# Windows
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py

# macOS / Linux
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Windows 也可以双击 `start_app.bat`，macOS / Linux 用 `./start_app.sh`（会自动创建 `.venv` 并安装依赖）。

启动后访问 `http://localhost:8501`。

## 项目结构

```text
python_vis_app_styled/
├── app.py                      # 顶栏 / 首页画廊 / 绘图页 / 导出
├── requirements.txt
├── start_app.sh / start_app.bat
├── .streamlit/config.toml
├── app/
│   ├── assets/
│   │   ├── styles.css           # 全站样式（含 $placeholder 主题变量）
│   │   └── previews/            # 24 张首页 SVG 预览
│   ├── docs_hub.py              # 首页内嵌文档（卡片列 / 右侧详情）
│   ├── core/
│   │   ├── catalog.py          # 模块分类、简介、输入格式、示例数据映射
│   │   ├── docs_content.py     # 每个图形的说明要点（解读 / 要点 / 参数建议）
│   │   ├── theme.py            # 10 套主题色板（含侧栏专用色）
│   │   ├── sample_utils.py     # 示例数据路径、载入控件、zip 打包
│   │   ├── io_utils.py         # 表格读取（按 mtime 缓存）、边表/矩阵转换
│   │   ├── plot_utils.py       # 图形字节导出（Matplotlib 兜底）
│   │   └── examples.py         # 内存示例数据
│   └── modules/                # 24 个绘图模块，统一 controls/build/render
├── sample_data/                # 35 份示例数据（CSV / TXT / NWK）
├── scripts/                    # 开发脚本（示例数据生成、测试、UI 探针）
├── docs/                       # 需求与架构设计文档
└── env/                        # 依赖环境：requirements-lock.txt / README.md
```

## 图形模块

### 网络关系（5）

| 模块 | 主要输入 |
| --- | --- |
| Arc Diagram | `from` / `to` / `value`、邻接矩阵，或 `.gml`；可选节点属性表 `name` / `group` / `fill` / `border` |
| Hierarchical Edge Bundling | `from` / `to` / `value`，`from` 支持层级路径 |
| Chord Diagram | `from` / `to` / `value` / `color` |
| Node-link Diagram | `from` / `to` / `value` / `color` |
| Sankey | `links(source/target/value/colorlink)` + `nodes(nodes/colornode)` |

### 分布比较（6）

| 模块 | 主要输入 |
| --- | --- |
| Raincloud Plot | 宽表（每列一组）或长表 `Group` / `Value` |
| Beeswarm | `Groups` / `Value` / `Group2` |
| Split Violin | `value` / `Group` / `Attribute` |
| ScaBoxDen | `x` / `y` / `group` |
| Pirate Plot | 连续值列 + 分类列 |
| BubbleViz | `x`（数值）/ `y`（数值）/ `size`（数值 > 0）/ `hue`（分类）/ `frame`（可选，驱动动画） |

### 矩阵与热图（3）

| 模块 | 主要输入 |
| --- | --- |
| Grouped Matrix Plotting | 长表 `row` / `group` / `column` / `category`（也支持宽表） |
| Heatmap | 宽表：第 1 列行名 + 数值列（可选行分组列） |
| UpSet Plot | 长表 `set` / `element`，或 0-1 宽表 |

### 环形与极坐标（2）

| 模块 | 主要输入 |
| --- | --- |
| CircleViz | 固定 6 列：`id` / `name` / `data1` / `data2` / `data3` / `data4`（列名不参与解析） |
| CircularBarPlot | `Name` / `type` / `data`（可正可负）/ `p_value` 或 `num_stars`（可选） |

### 统计与富集（4）

| 模块 | 主要输入 |
| --- | --- |
| Mantel Test | 物种 / 特征矩阵 + 环境矩阵 |
| GO Enrichment | `GO_Class` / `GO_Term` / `number_of_out`，或 `Richfactor` / `GO_desc` / `Corrected_P` / `Expressed_GO` |
| Volcano Plot | `gene` / `log2FC` / `pvalue`（可选 `padj`、`group`） |
| PCA | 宽表：第 1 列样本名 + 数值特征列（可选 `group`） |

### 基因组与生存（4）

| 模块 | 主要输入 |
| --- | --- |
| Genomic Variation Viewer | 基因结构 `name` / `start` / `end` + SNP `name` / `position` / `score`（上轨与下轨） |
| Kaplan-Meier | `sample` / `time` / `status` / `group` |
| Manhattan Plot | `snp` / `chr` / `pos` / `pvalue`（可选 `gene`） |
| Paired Tree Comparison | 两棵 Newick / Nexus 树 + 配对表 `tree1_label` / `tree2_label`（可选分组表 `label` / `group`） |

## 数据格式

- 表格文件支持 `.csv`、`.tsv`、`.txt`、`.xlsx`，默认按 UTF-8 读取；Arc Diagram 另支持 `.gml`
- 边表至少包含 `from`、`to`、`value` 三列，空值与非数值行会被过滤
- 矩阵第一列作为行名，其余列作为数值列；非数值自动转 0
- Arc Diagram 的 `.gml` 会读取节点 `label` / `group` / `fill` / `border` 与边 `value`；CSV 示例可搭配 `sample_data/arc_nodes.csv` 还原同一套节点属性
- Sankey 需要节点表与连边表两份文件；Mantel 需要特征矩阵与环境矩阵两份文件；Genomic Variation Viewer 需要基因结构 + 上/下轨 SNP 共三份文件
- 每个模块左侧都提供示例数据下载按钮，可先下载模板再替换内容
- 宽表数值列默认按「列」解释为特征：PCA / Heatmap 的第 1 列是样本名或行名，不会被当作数值

## 导出说明

绘图页工具栏的「设置与导出」按需渲染导出选项，可选格式取决于后端与已安装的依赖：

- **HTML**：完整独立页面，可选 CDN 或完全离线（内联 Plotly JS），适合分享与嵌入
- **JSON**：保留完整图形配置，便于二次开发
- **PNG**：位图，按物理尺寸 + dpi 渲染，可选透明背景
- **SVG / PDF**：矢量输出，按物理尺寸定画布，可无损放大

### 物理尺寸（mm）

静态导出不按像素定尺寸，而是按**期刊画布宽度**换算，PNG 与 SVG/PDF 共用同一套模型：

| 预设 | 宽度 | 适用场景 |
| --- | --- | --- |
| 单栏 85mm | 85 mm | 单栏插图（多数期刊要求 84–90 mm） |
| 1.5 栏 114mm | 114 mm | 1.5 栏版式 |
| 双栏 170mm | 170 mm | 通栏插图（170–180 mm） |
| Nature 单栏 / 双栏 | 89 / 183 mm | Nature 系列常用宽度，投稿前请复核最新指南 |
| Cell 单栏 / 双栏 | 85 / 174 mm | Cell 系列常用宽度，投稿前请复核最新指南 |
| Science 单栏 / 双栏 | 55 / 121 mm | Science 系列常用宽度，投稿前请复核最新指南 |
| 当前画布 | 画布像素 ÷ 96 dpi | 与屏幕上看到的构图完全一致 |
| 自定义 | 40–400 mm | 手动填写宽高，可锁定纵横比 |

高度默认按图形原始宽高比自动推算，只有「当前画布」与「自定义」会单独给出高度。少量以 Matplotlib 绘制的模块同样按 mm 定画布，矢量格式不提供 dpi 选项（尺寸由画布英寸数决定）。

### 导出前检查

静态格式下载前会显示 **Export Check**：物理画布、预计像素尺寸、模板宽度匹配、300/600 dpi、PNG 位图或 SVG/PDF 矢量、透明背景、RGB（CMYK 暂不支持）、字体族与最小字号、文件名规范、Kaleido/Chrome 状态。字号低于 6 pt、模板宽度不符或文件名过长时会显示提醒。

HTML 支持「CDN（文件较小）」与「完全离线（内联 Plotly JS）」两种模式；离线文件约 4–5 MB，但不需要联网即可打开。静态导出失败时，会区分 Kaleido 缺失、Chrome/Chromium 缺失和临时目录权限问题，并提示可改用 SVG/PDF 或 HTML。

### 尺寸与 dpi 的换算

换算基准是 `96 dpi`，即浏览器 CSS 像素：`px = mm ÷ 25.4 × 96`。画布先按 96 dpi 定尺寸，PNG 再靠 `scale = dpi ÷ 96` 放大像素——**物理尺寸不变，只是像素变多**：

| 请求 | 实际输出 |
| --- | --- |
| 85 mm @ 300 dpi | 1003 × 584 px ≈ 84.9 × 49.4 mm |
| 170 mm @ 600 dpi | 4019 × 2344 px ≈ 170 × 99 mm |

若把 dpi 直接当作画布像素基准，PDF/SVG 的 MediaBox 会偏大 `1 / 0.75` 倍（85 mm 变成 265 mm），这是初版实现踩过的坑，改法见 `EXPORT_BASE_DPI`。

### 依赖

PNG / SVG / PDF 需要可选依赖 `kaleido`；Kaleido 1.x 不再内置浏览器，由本机 Chrome / Chromium 渲染：

```bash
pip install kaleido
```

未安装时导出项只显示 HTML / JSON，界面会给出提示，不影响其他功能。首次静态渲染要拉起无头浏览器（数秒），结果按图形 JSON 缓存（`render_static_image`，最多 24 份），同一图形重复导出不再重跑。PNG 由 Pillow 写入真实的 300/600 dpi 元数据，确保像素尺寸、物理尺寸和投稿要求一致。示例数据可在「导出结果」中打包为 zip 下载。

`env/requirements-lock.txt` 记录了验证过的精确 Python 版本；`env/README.md` 提供从零搭建环境的完整命令。

## 图形文档（首页内嵌）

不再有独立的文档页。首页点击任意卡片即进入 `?page=home&doc=<图形名>` 的展开态：

- **左侧卡片列**：原 4 列图库收窄为 2 列，当前卡片高亮；搜索框与分类/数据形状筛选沿用首页顶部控件
- **右侧文档**：`说明 / 数据 / Python 代码 / 环境` 四个页签，顶部提供「← 收起文档」返回完整图库

「数据」页签会预览并列出该图形的全部示例文件（可直接下载，也可整图打包 ZIP），卡片区底部还能一次下载全部 35 份数据；「Python 代码」页签显示**可运行的 Python 示例代码块**（读取同名示例文件，右上角一键 Copy，可下载 `.py`），并默认展开该图形在本站的**完整模块源码代码块**（`app/modules/*.py`，可查看、复制、下载）。「环境」页签展示当前 Python 版本与依赖安装状态，并提供完整依赖文件和可复制的 Python 安装命令。

## 项目包（保存 / 恢复）

绘图页左侧「项目包」可把当前模块保存为 `.bioplot.zip`，用于刷新恢复、换机器继续、交接或投稿留档。

项目包内容：

- `manifest.json`：格式版本、模块、参数、主题、配色、统一外观与数据哈希
- `data/`：用户上传的原始文件
- `samples/`：内置示例数据快照，避免示例数据升级后旧项目无法复现
- `figure.json`：Plotly 图形配置
- `help.md` / `README.txt`：使用说明与恢复提示

恢复流程：在任意页面左侧「项目包」上传 zip → 点击「载入项目」。系统会自动进入对应绘图页，恢复参数/主题/配色、统一外观与随机种子，并把包内数据重新喂给原模块；上传控件仍可继续替换为新文件。旧项目包缺少外观字段时使用站点默认值。

限制：单个项目包压缩前/解压后均不超过 200 MB；项目仅保存当前模块，不包含其他模块的临时状态。

## 可复现与标签防裁剪

所有图形在统一出图出口执行标签防裁剪：根据长刻度、旋转标签、注释和图例估算边距，只扩大不缩小模块原有边距。相同数据、参数和随机种子会生成相同布局；随机种子是普通参数，因此项目包保存/恢复不依赖浏览器会话。

## 设置与导出

绘图页工具栏的「设置与导出」集中管理所有模块共用的外观、输出和参数重置，不再需要逐模块寻找同类选项。

- 字体：跟随模块、Arial、Helvetica、Times New Roman、微软雅黑；默认跟随模块，避免破坏已有模块样式。
- 字号：全局比例按模块原层级等比缩放；标题、轴标题、刻度、图例可分别输入固定字号，`0` 表示跟随模块。
- 标题与布局：可将统一标题覆盖到当前图形；图例支持右侧、顶部、底部或隐藏；网格线支持显示或隐藏。
- 恢复：可清除通用覆盖或恢复网站默认。恢复后会显示成功提示并自动重新生成。
- 画布与文件：支持单栏 85 mm、1.5 栏 114 mm、双栏 170 mm、当前画布和自定义尺寸；PNG 可选 300/600 dpi 与透明背景。
- 文件名：导出文件名与图形标题解耦，可单独设置；系统会自动清理非法字符并避免重复扩展名。
- 一致性：修改外观后点击「应用外观并重新生成」；未应用时工具栏状态标签与导出区都会提示当前预览仍使用上一次结果。
- 导出反馈：点击任意下载按钮后，工具栏会显示「导出完成 + 文件名/格式」的成功提示。

统一外观保存在项目包的 `manifest.json → figure_style` 中，包括字体、字号、标题覆盖、图例、网格和导出文件名。顶部/底部图例也会进入标签防裁剪计算。

左侧参数区按模块复杂度分区：Heatmap、Volcano Plot、PCA、Kaplan-Meier、Node-link Diagram、Sankey 的常用参数默认展开，聚类、标注、统计细节、层级与节点布局等高级参数收进「高级参数」折叠区；其他模块继续使用原有的「参数设置」或模块内折叠分组。

## 新增一个图形模块

1. 在 `app/modules/` 新建模块，提供 `controls(shared)` 与 `build(shared)`，`build` 返回 `(figure, data, status, help_text)`，失败路径返回 `(None, None, 中文提示, HELP_TEXT)`；可选提供 `advanced_controls(shared)` 把进阶参数放入折叠区
2. 在 `app.py` 的 `MODULES` 与 `app/modules/__init__.py` 中登记模块对象
3. 在 `app/core/catalog.py` 的 `PLOTS` 中补充分类、简介、输入格式与示例数据键
4. 在 `app/assets/previews/` 添加同名 SVG 预览（`viewBox="0 0 400 240"`）
5. 在 `app/core/sample_utils.py` 的 `SAMPLE_PATHS` 中登记示例数据
6. 若模块有颜色选择器，把 `st.color_picker` 的 key 统一为 `<前缀>_<语义>_color`，并把前缀加进 `app.py` 的 `reset_module_colors()`
7. 在 `app/core/py_recipes.py` 补 Python 示例并登记模块文件名（`MODULE_SOURCES`），在 `app/core/docs_content.py` 补说明要点

## 开发脚本

`scripts/` 下均为开发期工具，不参与站点运行：

| 脚本 | 用途 |
| --- | --- |
| `generate_sample_data.py` | 用固定种子重新生成 14 份示例数据（可复现） |
| `apptest_native_modules.py` | 5 个迁移模块的 AppTest 契约与变体测试 |
| `verify_t3.py` | 6 个新增模块的 build 契约 + 算法断言 |
| `apptest_ui.py` | 首页 / 路由 / 绘图页 Tab / 导出路径的 AppTest |
| `apptest_project.py` | 项目包保存、恢复、上传数据、DataFrame 参数与安全校验 |
| `apptest_reproducibility.py` | 严格模式、随机种子、标签防裁剪与项目恢复的可复现性 |
| `apptest_figure_settings.py` | 统一外观、导出文件名、脏状态提示、24 模块外观与项目恢复 |
| `apptest_toolbar_refactor.py` | 工具栏四入口、合并状态条、恢复/重置反馈、导出提示与 6 模块参数分区 |
| `apptest_docs_hub.py` | 首页内嵌文档：展开/收起、卡片/详情、筛选、数据下载、Python 代码与环境文件 |
| `check_py_recipes.py` | 用内置示例数据逐个执行 24 段 Python 代码，并校验模块源码映射 |
| `apptest_export_products.py` | 普通图/热图/网络图的真实 PNG、SVG、PDF 成品验收 |
| `apptest_export_check.py` | 导出前检查、期刊模板、锁定纵横比与离线 HTML |
| `apptest_option_sweep.py` | 全模块参数组合遍历 |
| `audit_keys.py` | session_state key 命名静态审计（前缀 + 禁用子词 + 颜色规则） |
| `render_check*.py` | 用 headless Chrome 把图形渲染成 PNG 做视觉核验 |
| `ui_probe.py` | 浏览器级 UI 验收（顶栏吸顶、卡片列数、无横向滚动、侧栏折叠） |

## 常见问题

- **提示缺少 streamlit / pandas**：先激活 `.venv`，再执行 `pip install -r requirements.txt`
- **Louvain 社区检测不可用**：确认已安装 `python-louvain`（import 名为 `community`）
- **静态导出失败**：检查 `kaleido` 与本机 Chrome/Chromium（Kaleido 1.x 由它渲染）；报错信息会显示在导出面板下方
- **导出很慢或卡住**：首次渲染需要拉起无头浏览器，约数秒；同一图形参数第二次导出走缓存
- **中文乱码**：将输入文件另存为 UTF-8 编码
- **端口被占用**：`streamlit run app.py --server.port 8502`
- **切换主题后颜色没变**：确认该模块的颜色 key 含 `color` 子串，且前缀已登记进 `reset_module_colors()`

## 说明

24 个模块全部输出 Plotly 交互图，单进程运行，无需任何外部服务。投稿级出图建议安装 Kaleido，用「单栏 85mm / 双栏 170mm + 300 或 600 dpi」导出 SVG/PDF——矢量格式在 Word / LaTeX 里可无损缩放，且物理尺寸与期刊要求直接对齐。

## 许可证

本项目以 [MIT License](LICENSE) 发布。
