# BioPlotter 网站完善建议

> 核查对象：`python_vis_app_styled/`（Streamlit + Plotly 单进程应用）
> 核查方式：本地启动实例，用 headless Chrome 在 1440 / 390 两种视口抓取首页、Volcano / Heatmap / Sankey / Paired Tree 绘图页，并做 DOM 与源码交叉核对
> 核查日期：2026-11-21　版本：v3.0（24 模块 / 6 分类 / 34 示例 / 10 主题）

---

## 〇、已落地的修改（2026-11-23）

下文 P0 / P1 / 工程项已按优先级改完一批，逐条对应：

| 编号 | 改动 | 落点 |
| --- | --- | --- |
| P0-1 | 侧栏初始 `expanded` → `auto`；≤768px 侧栏宽度限 86vw；≤640px 卡片强制单列 | `app.py` `set_page_config`、`styles.css` 末尾媒体查询 |
| P0-2 | 删除右下 `position: fixed` 悬浮条，把「重置参数」并入顶部工具栏（5 列）；工具栏成为唯一操作入口 | `app.py` `_toolbar_row`、`styles.css` |
| P0-3 | 侧栏模块名允许换行（不再被侧栏边界硬切），目录间距由 1rem 收到 0.1rem | `styles.css` `[class*="st-key-nav_"]` |
| P0-4 | 热图按行列数量自动抽稀刻度（`dtick` = ⌈n/30⌉），标签默认字号 8 → 10 | `app/modules/heatmap.py` `_tick_step()` |
| P1-5 | 删除 24 张卡片上的 `PLOTLY` 标签及其 CSS | `gallery_card_html()` |
| P1-7 | Sankey 全部控件与帮助文案中文化（含 `Sinks Right` → `末级节点靠右 / 是·否`、状态行） | `app/modules/sankey_d3.py` |
| P1-8 | Sankey 画布高度 560、右侧留白 140 给末级标签 | 同上 `update_layout` |
| P1-11 | 筛选生效时在计数右侧出现「清除」按钮 | `render_gallery_controls()` |
| P2 | 卡片正文 0.72rem/`--muted` → 0.78rem/`--text`@0.78；`gallery-meta` 同步提亮 | `styles.css` |
| 工程-12 | 1409 行内联 CSS 抽到 `app/assets/styles.css`，`inject_css` 只做 `Template(...).substitute()`；app.py 2654 → 1245 行 | 新增 `app/assets/styles.css` |
| 工程-13 | 32 处 `use_container_width` → `width="stretch"/"content"`，启动日志不再刷废弃警告 | 全项目 |
| 工程-14 | `read_table()` 走 `@st.cache_data`（按 path + mtime 失效）；去掉生成后多余的一次 `st.rerun()` | `app/core/io_utils.py`、`show_plot()` |
| 工程-15 | `preview_svg()` 补上 `@lru_cache`（docstring 与实现终于一致） | `app/core/catalog.py` |

同时修正了顶栏 `.topbar` 自带的 `border-bottom`（在绘图页只画到导航末尾，像一条断掉的线），改由外层 `.st-key-topbar` 统一画。

**回归结果**：`apptest_p0` 33/33、`apptest_ui` 24/24、`verify_t3` 0 failure、`audit_keys` 0 problem、浏览器级 `ui_probe_p0` 23/23（1440/1024/768 三档布局 + 亮/暗对比度 + 无横向滚动）。

**仍有已知问题**：`apptest_native_modules` 有 2 条 CircularBarPlot 的 `trace count 19 > budget 16`（R 对齐那批新增的分隔线/刻度圆导致，与本次改动无关）；Sankey 节点标签仍压在节点块上（Plotly Sankey 不支持标签定位）；24 张预览缩略图风格仍未统一。

---

## 〇之二、导出链路改造：物理尺寸导出（2026-11-23）

与 GraphPad Prism 对照后列出的第一优先项——**期刊投稿要的是 mm + dpi，不是像素**。原实现只有「1x / 2x / 3x」像素倍率，SVG/PDF 还明确写着「不提供分辨率选项」，等于把定尺寸的活丢给用户在 Word 里手拉。

改造要点：

| 项 | 改前 | 改后 |
| --- | --- | --- |
| 尺寸模型 | 像素倍率 1x/2x/3x | 期刊画布 5 档：单栏 85mm / 1.5 栏 114mm / 双栏 170mm / 当前画布 / 自定义 40–400mm |
| 精度 | 无（固定像素） | PNG 可选 300 / 600 dpi；矢量格式按 mm 定画布，无 dpi 概念 |
| SVG / PDF | 不控尺寸 | 与 PNG 共用同一 mm 模型，MediaBox 与请求一致 |
| 透明背景 | 无 | PNG 可勾选 |
| 渲染缓存 | 无 | `render_static_image` 按图形 JSON + 尺寸 + dpi 缓存 24 份 |

**关键换算**：画布统一按 `EXPORT_BASE_DPI = 96`（浏览器 CSS 像素基准）定尺寸，`px = mm ÷ 25.4 × 96`；PNG 再用 `scale = dpi ÷ 96` 放大像素。这样物理尺寸、PDF/SVG 的 MediaBox、字号比例三者才对齐。

初版把 dpi 直接当画布像素基准，结果请求 85mm 的 PDF 量出 265.7mm（偏大 `1 / 0.75` 倍），定位后改为上述 96dpi 模型。

**端到端验证**（真实下载落盘后读尺寸，非源码断言）：

| 请求 | 输出像素 | 实际物理尺寸 |
| --- | --- | --- |
| PNG 85mm @ 300dpi | 1003 × 584 | 84.9 × 49.4 mm |
| PNG 170mm @ 600dpi | 4019 × 2344 | — |
| SVG 85mm | `width="85mm"` | 84.9 mm |
| PDF 85mm | MediaBox 一致 | 84.9 mm |

验收方式：AppTest 不暴露 `download_button` 的二进制，改用 CDP（`Browser.setDownloadBehavior`）真实下载落盘再读像素。`README.md` 的「导出说明」已同步这套模型、预设表与依赖说明。

---

## 一、先说做对的部分

这些是该保留的资产，不建议在重构中丢掉：

- **模块契约统一**：24 个模块都是 `controls(shared)` + `build(shared) -> (fig, data, status, help_text)`，新增模块只需登记 6 处，扩展成本很低。
- **零外部依赖**：全部 Plotly 原生实现，不依赖 R/Node/iframe，`sample_data/` 自带 34 份示例，克隆即可跑。
- **路径健壮**：`sample_utils.PROJECT_ROOT = Path(__file__).parents[2]`，工作目录无关，这点比多数同类项目做得好。
- **预览图可访问**：24 张 SVG 带 `role="img"` + `aria-label`，不是裸 `<div>`。
- **开发工具链齐全**：`audit_keys.py` 静态审计 session_state、`ui_probe.py` 用 CDP 做浏览器级验收，思路专业。

---

## 二、P0：影响可用性，建议先修

### 1. 移动端侧栏默认展开，遮住 70% 内容

`st.set_page_config(initial_sidebar_state="expanded")` 在 390px 视口下把整个侧栏铺开，主区只剩一条缝，绘图页的图完全看不到（已截图确认）。

**改法**：`initial_sidebar_state="auto"`，并在 `inject_css` 里加窄屏断点，让侧栏 `position: static` 或默认收起；绘图页的"参数设置"在 <768px 时改为底部抽屉/折叠面板。

### 2. 生成/导出入口重复，且悬浮条遮图

绘图页同时存在两套动作：

- 顶部工具栏（`_toolbar_row`）：生成图形 / 使用说明 / 数据预览 / 导出结果
- 右下悬浮条（`render_sticky_actions`）：生成图形 / 重置参数 / 导出

`.st-key-plot-actions` 是 `position: fixed`，在 Volcano 页实测压在散点图上、并盖住页脚。

**改法**：只留顶部工具栏；悬浮条改为"参数已修改"时的轻量提示条（仅当 dirty 时出现，且 `bottom: 1.2rem` 时给主区加 `padding-bottom`），或干脆去掉。同时"数据预览/使用说明"在工具栏 popover 与下方 Tab 里各有一份，建议二选一（Tab 更适合大内容）。

### 3. 侧栏长模块名被裁切

`Hierarchical Edge Bundling` 在 218px 宽的按钮里溢出，被侧栏边界硬切，没有省略号，看不出是哪个模块。

**改法**：按钮/链接加 `text-overflow: ellipsis; white-space: nowrap; overflow: hidden;` + `title` 属性；或侧栏允许换行（`white-space: normal; line-height: 1.25`）。

### 4. 热图行名刻度不可读

Heatmap 示例是 200 行 × 20 列（200 个基因 × 20 个样本），Plotly 把 200 个行名整条铺在 y 轴上，实际是一排糊在一起的小字（x 轴 20 个样本名尚可读）。

**改法**：按数量自动抽稀（`dtick`，每 ⌈n/30⌉ 个显示一个），行数 > 50 时同样处理 x 轴。

---

## 三、P1：体验与一致性

### 5. 每张卡片都挂 "PLOTLY" 标签，是纯噪声

24 张卡片右上角都一样。技术栈不是用户决策依据，占的却是卡片最贵的位置。

**改法**：删掉，改在页脚/关于页写一句"全部图形由 Plotly 原生渲染"。

### 6. 预览缩略图风格不统一、对比度偏低

- Arc / HEB / Chord / Node-link 用低饱和 pastel，缩到 130px 高后几乎"消失"；Sankey / Genomic Variation / Heatmap 又很密很重。
- 同一行里有的图形占满画布，有的缩在中间（Beeswarm、Split Violin 大片留白）。

**改法**：统一 24 张 SVG 的构图规则——固定 400×240 viewBox、线宽 ≥ 2、主色统一取主题主色 + 1 个辅助色、主体占画布 70%~80%；用 `scripts/preview_shots.py` 批量重出一次。

### 7. 中英文混排

- Sankey 状态："Sankey diagram generated: 18 nodes, 26 links."，其余全中文。
- Sankey 侧栏 "Font Family: serif"、"TRUE/FALSE"，与其他模块的中文一致风格不符。
- 术语在"图形 / 图表 / 图 / Plot"之间来回切换（"图形标题""添加图表标题""生成图形"）。

**改法**：统一中文文案 + 固定一套术语表（建议：模块 = 图形，对象 = 图表，动作 = 生成图形）；TRUE/FALSE 用 `st.toggle`。

### 8. Sankey 画布比例失衡

图形被拉成很扁的一条，挤在画布中间，节点标签 `group_1` 多处重复叠字，纵向留白超过 60%。

**改法**：给 800×420 的固定 aspect ratio；标签去重（node id 与 label 分开）；节点数 > 15 时自动加 left/right margin 并允许 `hovertext`。

### 9. 侧栏参数区密度过高

- 4 个大色块（色板）纵向吃掉约 200px。
- 分组标题 `### 数据 / 阈值 / 外观` 与控件之间层级弱。
- 参数多时侧栏要滚很久，且滚动后看不到"生成图形"。

**改法**：色板改成一行 4 个 28×28 小方块 + 取色器；参数按 `数据 / 外观 / 导出` 分 3 个 Tab；把"生成图形"固定在侧栏底部。

### 10. 状态条信息权重偏大

`状态 / 数据 / 引擎 / 更新 / 主题` 五个 chip 常驻，其中"引擎 Plotly"对 24 个模块是同一值（同第 5 条）。

**改法**：降级为一行 `st.caption`，只留"数据规模 + 生成时间"；错误态才升格为醒目提示。

### 11. 首页缺少"下一步"引导

现在只有搜索 + 分类 pill；筛选为空时有"清除筛选"，非空时反而没有；没有"最近使用"、没有 `Cmd/Ctrl+K`。

**改法**：筛选行右侧加"清除"；空态加"按数据形状找图"入口；搜索框支持 `/` 聚焦；localStorage 记录最近 3 个模块。

---

## 四、P2：视觉细节

- **正文对比度**：卡片描述 12–13px 浅灰（约 `#64748b`），小字号下接近 WCAG AA 临界，实测放大后偏淡。提到 `#475569` + 13.5px。
- **卡片纵向浪费**：卡片高约 330px，预览只占 130px，正文 3 行 + CTA 挤在下面。可把预览提到 170px、正文压到 2 行（`-webkit-line-clamp`），一屏能多露半行卡片。
- **首页 hero 与筛选行间距**偏大（约 40px 空白），首屏信息被推低。
- **卡片 CTA**"打开绘图 →"是纯文字链接位，没有 hover 反馈；建议整卡 hover 抬升 + 边框主色，CTA 变实心小按钮。

---

## 五、工程与可维护性（技术债最重的地方）

### 12. `app.py` 2654 行，其中约 1465 行是内联 CSS

`inject_css()` 从第 225 行到第 1690 行，一整段 f-string `<style>`，并且存在**同一选择器定义 3 次**的情况：

| 选择器 | 位置 | 写法 |
| --- | --- | --- |
| `[data-testid="stSidebar"] .stMarkdown h1~h4` | 471 / 1474 / 1615 | 三次，前两次硬编码色值 |
| `... [data-testid="stExpanderDetails"] h3` | 714 / 1513 / 1654 | 三次，714 用 `#cfd8e3 !important` |

真正生效靠"后面的 `!important` 覆盖前面的 `!important`"，改一行颜色要往上翻 900 行确认没被覆盖。

**改法**：
1. CSS 抽到 `app/assets/styles.css`，用 `st.markdown(Path(...).read_text(), unsafe_allow_html=True)` 注入；
2. 主题变量走 `:root { --bg: ...; }`，Python 只输出一行 `:root{...}`，不再整段拼模板；
3. 删掉 1460–1516 这类被 var() 版本取代的硬编码遗留块（当前是死代码）。

### 13. 34 处 `use_container_width` 已废弃

启动日志刷屏：

```
Please replace `use_container_width` with `width`. `use_container_width` will be removed after 2025-12-31.
```

当前 Streamlit 1.55 仍兼容，但按官方时间表已经过期。

**改法**：全局替换 `use_container_width=True → width="stretch"`，`False → width="content"`（34 处，可用一条 sed + 回归截图验证）。

### 14. 完全没有缓存

全项目 0 处 `st.cache_data` / `st.cache_resource`。每次 rerun 都要：重读 CSV → 重新解析 → 重新跑模块 `controls()`。叠加 `run_module_generation()` 后紧跟 `st.rerun()`（2631–2634 行），一次"生成图形"点击实际跑两遍脚本。

**改法**：
- `@st.cache_data` 包住 `pd.read_csv`（key 用 `path + mtime`）；
- `@st.cache_data` 包住 `build` 的纯计算部分（key 用 `module + sorted(params)`）；
- 去掉多余的 `st.rerun()`，生成后直接渲染即可。

### 15. `preview_svg()` 的 docstring 与实际不符

注释写 "cached per process"，实现是每次 `path.read_text()`。首页一次渲染要读 24 个文件。

**改法**：`@lru_cache(maxsize=None)`。

### 16. 依赖不锁、无测试入口、无部署产物

- `requirements.txt` 10 项全是 `>=`，没有上限也没有 lock 文件；`plotly`/`kaleido` 大版本漂移会直接打死导出功能。
- 测试是 `scripts/` 下 17 个一次性脚本，没有 `pytest` 入口、没有 CI，`pytest` 关键字全项目 0 命中。
- 没有 `LICENSE`、没有 `Dockerfile`，README 只讲本地 `streamlit run`。

**改法**：加 `pyproject.toml`（依赖 + `[tool.pytest]`）、`uv.lock` 或 `requirements.lock`；把 `apptest_*.py` / `verify_t3.py` 改造成 `tests/test_*.py`；补 `Dockerfile` + `HEALTHCHECK`；明确 LICENSE。

---

## 六、建议的实施顺序

| 阶段 | 内容 | 交付物 |
| --- | --- | --- |
| 第 1 步（0.5 天） | P0 四条：移动端侧栏、悬浮条去重、长名省略、热图刻度 | 截图对比 |
| 第 2 步（1 天） | 拆 `styles.css` + 主题变量化 + 删死代码 | app.py 降到 ~1200 行 |
| 第 3 步（0.5 天） | `use_container_width` 全量迁移 + 加缓存 | 启动日志无警告、rerun 明显变快 |
| 第 4 步（1–2 天） | 首页视觉：删 PLOTLY 标签、重出 24 张预览、卡片密度 | 新首页截图 |
| 第 5 步（1 天） | 文案统一（中英混排 / 术语表）+ Sankey/Heatmap 可读性 | 文案对照表 |
| 第 6 步（1 天） | pytest + CI + lock + Dockerfile | 绿灯 CI |

---

## 附：本次核查的原始证据

截图保存在工作区根目录 `_shots/`（可随时删除）：`h_full.png`（首页整页）、`crop_row1.png` / `crop_sidebar_full.png`（卡片与侧栏高清）、`h_heatmap.png` / `h_sankey.png` / `h_pairedtree.png` / `plot_volcano.png`（绘图页）、`m_home.png` / `m_volcano.png`（390px 移动端）。
