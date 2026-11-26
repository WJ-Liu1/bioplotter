# 工具栏、统一设置与导出面板

绘图页工具栏收敛为四个主操作：**生成 / 设置与导出 / 数据 / 帮助**。通用外观、导出、参数重置集中在「设置与导出」，数据预览与模块说明分别进入「数据」「帮助」弹层。

工具栏下方用一行紧凑状态标签合并原 `meta-strip`：

- `状态`：就绪 / 已生成 / 待处理 / 生成失败。
- `样式来源`：网站默认、自定义通用外观、R 严格模式或组合状态。
- `R 模式`：站点外观 / R 严格模式。
- `数据`：本次图形使用的数据规模。
- `更新`：最近一次生成时间。
- `外观尚未应用`：仅在修改外观但尚未重新生成时出现；重新生成后自动消失。

引擎与主题不再重复占用状态条：主题已在顶栏可见，引擎对当前模块是固定信息。

## 参数分区

复杂模块把常用参数与高级参数拆开，避免常用项被长列表淹没：

- Heatmap：聚类方法、距离度量与行列聚类进入「高级参数」。
- Volcano Plot：Top-N 标注与标注字号进入「高级参数」。
- PCA：标准化、置信椭圆与分组配色进入「高级参数」。
- Kaplan-Meier：置信带、风险表、p 值与配色尺寸进入「高级参数」。
- Node-link Diagram：外/内层标签、节点形状与数值显示进入「高级参数」。
- Sankey：末级节点靠右、节点宽度/间距与标签字号进入「高级参数」。

其他模块保留原有「参数设置」或模块内折叠分组；新增模块可提供可选的 `advanced_controls(shared)` 接入同一套分区。

## 面板结构

### 外观设置

- 图形标题与「覆盖模块标题」开关。
- 字体族：跟随模块、Arial、Helvetica、Times New Roman、微软雅黑。
- 全局字号比例：`0.6–1.6`，对模块已有字号层级等比缩放。
- 标题、轴标题、刻度、图例固定字号：`0` 表示跟随模块。
- 图例位置：跟随模块、右侧、顶部、底部、隐藏。
- 网格线：跟随模块、显示、隐藏。
- 当前样式来源：网站默认、自定义通用外观、R 严格模式或二者组合。
- 恢复操作：清除通用覆盖、恢复网站默认、恢复 R 默认外观。
- 恢复反馈：恢复成功后显示明确成功提示，并自动重新生成预览。

### 导出与文件

- 独立导出文件名，不与图形标题绑定。
- PDF/SVG/PNG 期刊物理尺寸和 300/600 dpi。
- PNG 透明背景。
- 期刊模板：单栏、1.5 栏、双栏，以及 Nature / Cell / Science 常用宽度；尺寸用于预检，投稿前需复核目标期刊最新指南。
- 自定义宽高可锁定当前图形纵横比。
- HTML 可选 CDN 或完全离线（内联 Plotly JS）。
- JSON 配置导出。
- 配套示例数据下载。
- 外观未应用时在工具栏显示紧凑状态条，导出区同时显示明确警告，避免误导出旧图。
- 点击下载后显示「导出完成 + 文件名/格式」反馈。

### 导出前检查

下载前显示一条紧凑检查卡，覆盖：

- 物理画布（mm / inch）与 PNG 预计像素尺寸。
- 当前模板宽度是否匹配。
- 300/600 dpi、PNG 位图或 SVG/PDF 矢量。
- 透明背景状态。
- RGB 输出；CMYK 明确标注“暂不支持”。
- 字体族与最小可见字号；低于 6 pt 时提醒。
- 文件名长度与非法字符。
- Kaleido / Chrome/Chromium 是否就绪。
- HTML 使用 CDN 还是完全离线。

静态导出失败时使用分类诊断：区分 Kaleido 缺失、Chrome/Chromium 缺失、临时目录权限问题，并给出 SVG/PDF、HTML 或 JSON 替代方案。

## 实现边界

- `app/core/figure_style.py` 统一保存样式状态、序列化、字号缩放、字体和图例/网格应用。
- `app/core/export_static.py` 负责 Plotly 静态渲染；PNG 导出后由 Pillow 重写 DPI 元数据，同时保留透明通道。
- `app/core/export_check.py` 负责模板、像素尺寸、字体、RGB/CMYK、文件规范与错误诊断，不修改图形数据。
- 样式只在统一 Plotly 出图出口执行，不修改 DataFrame、统计结果、trace 数据或项目参数。
- `prevent_label_clipping()` 在样式应用之后运行，右侧、顶部和底部图例都会预留边距；分类刻度会从 trace 数据推断长标签，并为左右边缘和旋转标签预留空间。
- R 严格模式仍在其后处理模块专属背景、Pirate 网格和 HEB 连线透明度。
- 通用外观字段使用 `fs_` 前缀，不进入模块参数和 R 对齐断言。

## 项目包

`manifest.json` 新增 `figure_style`：

```json
{
  "font_family": "Arial",
  "font_scale": 1.1,
  "title_size": 18,
  "axis_title_size": 12,
  "tick_size": 10,
  "legend_size": 10,
  "legend_position": "顶部",
  "grid_mode": "隐藏",
  "title_override": true,
  "export_name": "Figure 1"
}
```

旧项目包没有该字段时恢复为站点默认值。恢复后会按新样式自动重新生成，而不是直接复用包内旧 `figure.json`。

## 静态导出成品验收

回归脚本不读取浏览器下载按钮的二进制，而是直接走同一个 `app/core/export_static.py` 核心，并用 AppTest 生成的真实普通图、热图和网络图作为输入：

- PNG：校验像素尺寸、300/600 dpi 元数据、85 mm 物理宽度、透明背景四角 alpha 与内容 alpha。
- SVG：解析根节点 `width`、`height`、`viewBox`，检查中文标题与 `Microsoft YaHei` 字体。
- PDF：解析 `/MediaBox`，换算为毫米后校验宽高误差小于 0.5 mm。
- 布局：检查顶部水平图例、隐藏网格、长分类标签左右/底部边距，以及导出图四边无内容裁切。
- 一致性：将 1x 静态渲染作为预览基准，与 300 dpi 导出缩放到同尺寸后比较宽高比和平均像素差。
- 导出检查：验证 Nature/Cell/Science 模板、预计像素、大小字号提醒、锁定纵横比、离线 HTML 与错误诊断。

## 验证

```bash
.venv/Scripts/python.exe -X utf8 scripts/apptest_export_products.py
.venv/Scripts/python.exe -X utf8 scripts/apptest_export_check.py
.venv/Scripts/python.exe -X utf8 scripts/apptest_figure_settings.py
.venv/Scripts/python.exe -X utf8 scripts/apptest_toolbar_refactor.py
.venv/Scripts/python.exe -X utf8 scripts/apptest_p0.py
.venv/Scripts/python.exe -X utf8 scripts/apptest_project.py
.venv/Scripts/python.exe -X utf8 scripts/apptest_ui.py
```

覆盖字体继承、字号缩放、标题覆盖、图例位置、网格开关、顶部/长标签边距、文件名清理、项目包保存恢复、工具栏四入口、合并状态条、恢复/重置反馈、导出完成提示、参数分区、真实 PNG/SVG/PDF 成品、导出前检查、期刊模板、离线 HTML，以及 24 个模块应用非默认外观后的出图稳定性。
