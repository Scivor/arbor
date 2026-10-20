"""
reports/fonts.py
跨平台中文字体解析 — 供 Matplotlib 图表与 CSS 字体栈共用。

Linux 云环境通常没有 Songti SC / Hiragino；本机有文泉驿 / Droid Sans Fallback。
优先选用已安装且含 CJK 字形的字体，避免图表「□□□」乱码。

品牌展示字体：Comfortaa（与 Arbor 字标同系的圆润几何无衬线）。
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import List

_STATIC_ROOT = Path(__file__).resolve().parent.parent / "web" / "static"

# 按优先级：开源 CJK → 系统常见中文 → 西文兜底
_CJK_SANS_CANDIDATES = (
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
    "Droid Sans Fallback",
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "Source Han Sans SC",
    "PingFang SC",
    "Hiragino Sans GB",
    "Microsoft YaHei",
    "SimHei",
    "Arial Unicode MS",
)

_CJK_SERIF_CANDIDATES = (
    "Noto Serif CJK SC",
    "Source Han Serif SC",
    "Songti SC",
    "STSong",
    "SimSun",
)


@lru_cache(maxsize=1)
def _installed_font_names() -> frozenset[str]:
    try:
        from matplotlib.font_manager import fontManager
        return frozenset(f.name for f in fontManager.ttflist)
    except Exception:
        return frozenset()


def available_cjk_sans() -> List[str]:
    """已安装的无衬线 CJK 字体名（按优先级）。"""
    installed = _installed_font_names()
    return [n for n in _CJK_SANS_CANDIDATES if n in installed]


def available_cjk_serif() -> List[str]:
    installed = _installed_font_names()
    return [n for n in _CJK_SERIF_CANDIDATES if n in installed]


def resolve_plot_font_family() -> List[str]:
    """
    Matplotlib font.sans-serif 列表：优先 CJK，末尾 DejaVu 兜底。
    """
    fonts = available_cjk_sans()
    # 有些环境只有 serif CJK
    if not fonts:
        fonts = available_cjk_serif()
    fonts = list(fonts)
    for fallback in ("DejaVu Sans", "sans-serif"):
        if fallback not in fonts:
            fonts.append(fallback)
    return fonts


def apply_matplotlib_cjk_font() -> List[str]:
    """
    配置全局 Matplotlib rcParams 以正确渲染中文。
    Returns: 实际写入的 font.sans-serif 列表。
    """
    import matplotlib.pyplot as plt

    family = resolve_plot_font_family()
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = family
    plt.rcParams["axes.unicode_minus"] = False
    return family


def css_sans_stack() -> str:
    """
    网页 CSS sans-serif 栈：保留 macOS/Windows 优先字体，
    并插入 Linux 常见 CJK（WenQuanYi / Droid）避免无字形。
    """
    return (
        'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, '
        '"SF Pro Text", "PingFang SC", "Hiragino Sans GB", '
        '"WenQuanYi Micro Hei", "Droid Sans Fallback", '
        '"Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", '
        '"Helvetica Neue", Arial, sans-serif'
    )


def css_serif_stack() -> str:
    return (
        'Charter, Georgia, "TsangerJinKai02", '
        '"Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", '
        '"WenQuanYi Micro Hei", "Droid Sans Fallback", '
        'Palatino, serif'
    )


def css_display_stack() -> str:
    """
    标题 / 品牌展示栈：Comfortaa 对齐字标圆润几何气质；
    CJK 回退到无衬线中文（Comfortaa 无汉字字形）。
    """
    return (
        '"Comfortaa", "Nunito", "Varela Round", '
        '"PingFang SC", "Hiragino Sans GB", '
        '"WenQuanYi Micro Hei", "Droid Sans Fallback", '
        '"Noto Sans CJK SC", "Microsoft YaHei", sans-serif'
    )


def comfortaa_font_face_css(*, url_prefix: str = "/static/fonts/") -> str:
    """Web 用 @font-face（相对站点 /static）。"""
    prefix = url_prefix if url_prefix.endswith("/") else url_prefix + "/"
    faces = []
    for weight, name in ((400, "comfortaa-latin-400.woff2"),
                         (600, "comfortaa-latin-600.woff2"),
                         (700, "comfortaa-latin-700.woff2")):
        faces.append(
            f"""@font-face {{
  font-family: "Comfortaa";
  font-style: normal;
  font-weight: {weight};
  font-display: swap;
  src: url("{prefix}{name}") format("woff2");
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6,
    U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122,
    U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
}}"""
        )
    return "\n".join(faces)


@lru_cache(maxsize=1)
def embedded_comfortaa_font_face_css() -> str:
    """周报 HTML/PDF 内嵌 Comfortaa（data URI），不依赖外网。"""
    faces = []
    for weight, name in ((400, "comfortaa-latin-400.woff2"),
                         (600, "comfortaa-latin-600.woff2"),
                         (700, "comfortaa-latin-700.woff2")):
        path = _STATIC_ROOT / "fonts" / name
        if not path.exists():
            continue
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        faces.append(
            f"""@font-face {{
  font-family: "Comfortaa";
  font-style: normal;
  font-weight: {weight};
  font-display: swap;
  src: url(data:font/woff2;base64,{b64}) format("woff2");
}}"""
        )
    return "\n".join(faces)


@lru_cache(maxsize=4)
def arbor_wordmark_data_uri(variant: str = "brand") -> str:
    """
    Arbor 字标 PNG data URI。
    variant: brand | dark | light | nav
    """
    names = {
        "brand": "arbor-wordmark.png",
        "dark": "arbor-wordmark-dark.png",
        "light": "arbor-wordmark-light.png",
        "nav": "arbor-wordmark-nav.png",
    }
    path = _STATIC_ROOT / "img" / names.get(variant, names["brand"])
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"
