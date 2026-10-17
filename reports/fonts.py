"""
reports/fonts.py
跨平台中文字体解析 — 供 Matplotlib 图表与 CSS 字体栈共用。

Linux 云环境通常没有 Songti SC / Hiragino；本机有文泉驿 / Droid Sans Fallback。
优先选用已安装且含 CJK 字形的字体，避免图表「□□□」乱码。
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

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
