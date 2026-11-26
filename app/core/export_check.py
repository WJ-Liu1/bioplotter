from __future__ import annotations

import re
from dataclasses import dataclass

import plotly.graph_objects as go


MM_PER_INCH = 25.4
BASE_DPI = 96
MIN_FONT_PT = 6.0

JOURNAL_TEMPLATES: dict[str, float] = {
    "Nature 单栏 89mm": 89.0,
    "Nature 双栏 183mm": 183.0,
    "Cell 单栏 85mm": 85.0,
    "Cell 双栏 174mm": 174.0,
    "Science 单栏 55mm": 55.0,
    "Science 双栏 121mm": 121.0,
}

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_INFO = "info"


@dataclass(frozen=True)
class ExportCheckItem:
    label: str
    value: str
    status: str = STATUS_OK


@dataclass(frozen=True)
class ExportCheckResult:
    items: tuple[ExportCheckItem, ...]

    @property
    def warnings(self) -> int:
        return sum(1 for item in self.items if item.status == STATUS_WARN)

    @property
    def passed(self) -> int:
        return sum(1 for item in self.items if item.status == STATUS_OK)

    @property
    def summary(self) -> str:
        if self.warnings:
            return f"{self.passed} 项通过 · {self.warnings} 项需确认"
        return f"{self.passed} 项通过 · 可以导出"


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _axis_values(fig: go.Figure):
    for name in fig.layout:
        if name.startswith("xaxis") or name.startswith("yaxis"):
            axis = getattr(fig.layout, name, None)
            if axis is not None and axis.visible is not False:
                yield axis


def figure_font_info(fig: go.Figure) -> tuple[str, float | None]:
    """Return the effective font family and the smallest visible font size in px."""
    family = str(fig.layout.font.family or "").strip()
    global_size = _number(fig.layout.font.size) or 12.0
    sizes: list[float] = []

    title_text = str(getattr(fig.layout.title, "text", "") or "").strip()
    if title_text:
        sizes.append(_number(fig.layout.title.font.size) or global_size)

    if fig.layout.showlegend is not False:
        sizes.append(_number(fig.layout.legend.font.size) or global_size)

    for axis in _axis_values(fig):
        sizes.append(_number(axis.tickfont.size) or global_size)
        if str(axis.title.text or "").strip():
            sizes.append(_number(axis.title.font.size) or global_size)

    for annotation in fig.layout.annotations or ():
        if str(annotation.text or "").strip():
            sizes.append(_number(annotation.font.size) or global_size)

    visible = [size for size in sizes if size and size > 0]
    return family or "跟随模块", min(visible) if visible else None


def _canvas_item(
    fmt: str,
    width_mm: float | None,
    height_mm: float | None,
    dpi: int | None,
) -> ExportCheckItem:
    if width_mm is None or height_mm is None:
        return ExportCheckItem("画布", "未设置物理画布", STATUS_INFO)

    width_in = width_mm / MM_PER_INCH
    height_in = height_mm / MM_PER_INCH
    value = (
        f"{width_mm:.1f} × {height_mm:.1f} mm"
        f"（{width_in:.2f} × {height_in:.2f} in）"
    )
    if fmt == "PNG":
        effective_dpi = dpi or 300
        pixels_w = max(1, round(width_mm / MM_PER_INCH * effective_dpi))
        pixels_h = max(1, round(height_mm / MM_PER_INCH * effective_dpi))
        value += f" · {pixels_w} × {pixels_h} px"
    return ExportCheckItem("画布", value, STATUS_OK)


def _template_item(
    template_name: str,
    width_mm: float | None,
) -> ExportCheckItem:
    expected = JOURNAL_TEMPLATES.get(template_name)
    if expected is None:
        return ExportCheckItem("期刊模板", f"{template_name} · 无预设宽度限制", STATUS_INFO)
    if width_mm is None:
        return ExportCheckItem("期刊模板", f"{template_name} · 缺少画布宽度", STATUS_WARN)
    delta = abs(width_mm - expected)
    if delta <= 0.5:
        return ExportCheckItem(
            "期刊模板",
            f"{template_name} · 宽度匹配（{expected:.0f} mm）",
            STATUS_OK,
        )
    return ExportCheckItem(
        "期刊模板",
        f"{template_name} · 当前 {width_mm:.1f} mm，建议 {expected:.0f} mm",
        STATUS_WARN,
    )


def _font_item(
    font_family: str,
    min_font_pt: float | None,
) -> ExportCheckItem:
    family = font_family.strip() or "跟随模块"
    if min_font_pt is None:
        return ExportCheckItem("字体", f"{family} · 未检测到有效字号", STATUS_WARN)
    if min_font_pt + 1e-6 < MIN_FONT_PT:
        return ExportCheckItem(
            "字体",
            f"{family} · 最小 {min_font_pt:.1f} pt（建议 ≥{MIN_FONT_PT:.0f} pt）",
            STATUS_WARN,
        )
    return ExportCheckItem(
        "字体",
        f"{family} · 最小 {min_font_pt:.1f} pt",
        STATUS_OK,
    )


def _file_name_item(file_name: str, fmt: str) -> ExportCheckItem:
    value = file_name.strip()
    if not value:
        return ExportCheckItem("文件名", "文件名为空", STATUS_WARN)
    if len(value) > 80:
        return ExportCheckItem("文件名", f"{value[:77]}... · 超过 80 字符", STATUS_WARN)
    if re.search(r'[\\/:*?"<>|]', value):
        return ExportCheckItem("文件名", f"{value} · 含非法字符", STATUS_WARN)
    return ExportCheckItem("文件名", f"{value}.{fmt.lower()}", STATUS_OK)


def build_export_check(
    *,
    fmt: str,
    file_name: str,
    width_mm: float | None,
    height_mm: float | None,
    dpi: int | None = None,
    transparent: bool = False,
    template_name: str = "自定义",
    font_family: str = "",
    min_font_pt: float | None = None,
    static_ready: bool = True,
    html_offline: bool = False,
) -> ExportCheckResult:
    normalized = fmt.upper()
    raster = normalized == "PNG"
    vector = normalized in {"SVG", "PDF"}

    items = [
        _canvas_item(normalized, width_mm, height_mm, dpi),
        _template_item(template_name, width_mm),
    ]

    if raster:
        items.append(ExportCheckItem("分辨率", f"{dpi or 300} dpi · 位图", STATUS_OK))
        items.append(ExportCheckItem("类型", "PNG 位图", STATUS_OK))
        items.append(ExportCheckItem(
            "背景",
            "透明背景" if transparent else "不透明背景",
            STATUS_OK,
        ))
    elif vector:
        items.append(ExportCheckItem("分辨率", "矢量输出 · 可无损放大", STATUS_OK))
        items.append(ExportCheckItem("类型", f"{normalized} 矢量", STATUS_OK))
        items.append(ExportCheckItem("背景", "由图形背景与透明度决定", STATUS_INFO))
    else:
        items.append(ExportCheckItem("分辨率", "不适用", STATUS_INFO))
        items.append(ExportCheckItem("类型", normalized, STATUS_INFO))
        items.append(ExportCheckItem("背景", "由图形背景与透明度决定", STATUS_INFO))

    items.extend([
        ExportCheckItem("颜色", "RGB · CMYK 暂不支持", STATUS_INFO),
        _font_item(font_family, min_font_pt),
        _file_name_item(file_name, normalized),
    ])

    if normalized in {"PNG", "SVG", "PDF"}:
        items.append(ExportCheckItem(
            "静态引擎",
            "Kaleido + Chrome/Chromium 就绪" if static_ready else "Kaleido 或 Chrome/Chromium 未就绪",
            STATUS_OK if static_ready else STATUS_WARN,
        ))
    elif normalized == "HTML":
        items.append(ExportCheckItem(
            "HTML 资源",
            "完全离线 · Plotly JS 已内联" if html_offline else "CDN · 打开时需要联网",
            STATUS_OK if html_offline else STATUS_INFO,
        ))

    return ExportCheckResult(tuple(items))


def diagnose_static_export_error(exc: Exception, *, static_ready: bool = True) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    if not static_ready or "kaleido" in lowered:
        return (
            f"静态导出失败：{message}。请确认已安装 kaleido；仍失败时可先导出 SVG/PDF 或 HTML。"
        )
    if any(token in lowered for token in ("chrome", "chromium", "browser", "executable")):
        return (
            f"静态导出失败：{message}。Kaleido 已安装，但未找到可用的 Chrome/Chromium；"
            "请安装浏览器或改用 HTML/SVG 导出。"
        )
    if any(token in lowered for token in ("permission", "access denied")):
        return (
            f"静态导出失败：{message}。请检查临时目录写入权限，或改用 HTML/JSON 导出。"
        )
    return (
        f"静态导出失败：{message}。可先尝试 SVG/PDF，或改用 HTML/JSON 保留图形配置。"
    )
