# 依赖环境

网站是纯 Python / Plotly 实现，只需要 Python 环境。
「图形文档 → 代码」里展示的也是 Python 示例与本站完整模块源码。

## 1. 运行网站（Python）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r env\requirements-lock.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

也可以直接双击项目根目录的 `start_app.bat`。

`requirements-lock.txt` 为验证过的精确版本；`requirements.txt` 保留较宽松的版本范围，
便于在新机器上安装。

## 2. 数据

全部示例数据位于 `sample_data/`，并在「图形文档」页内按图形分组提供预览与下载，
也支持一键打包 ZIP，无需手动翻目录。
