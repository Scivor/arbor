"""
tests/test_fonts.py
中文字体解析 — 保证 Matplotlib 不会回退到无 CJK 字形的 DejaVu。
"""

import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reports.fonts import (
    apply_matplotlib_cjk_font,
    available_cjk_sans,
    css_sans_stack,
    resolve_plot_font_family,
)


def test_resolve_prefers_installed_cjk():
    family = resolve_plot_font_family()
    assert family
    assert family[-1] in ("DejaVu Sans", "sans-serif") or "DejaVu Sans" in family
    # 本机通常有文泉驿或 Droid；若都没有至少列表非空
    installed = available_cjk_sans()
    if installed:
        assert family[0] in installed
        assert family[0] != "DejaVu Sans"


def test_matplotlib_renders_cjk_without_glyph_warning(tmp_path):
    apply_matplotlib_cjk_font()
    fig, ax = plt.subplots(figsize=(3, 1.5))
    ax.set_title("近日报价走势")
    ax.set_ylabel("美分/磅")
    ax.plot([1, 2, 3], [1, 2, 1])
    out = tmp_path / "cjk.png"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fig.savefig(out, dpi=100)
        plt.close(fig)
    glyph_warnings = [
        w for w in caught
        if "Glyph" in str(w.message) and "missing" in str(w.message)
    ]
    # 有 CJK 字体时应无缺字形警告
    if available_cjk_sans():
        assert not glyph_warnings, glyph_warnings
    assert out.stat().st_size > 500


def test_css_stack_includes_linux_fallbacks():
    from reports.fonts import css_display_stack, css_serif_stack

    stack = css_sans_stack()
    assert "WenQuanYi Micro Hei" in stack
    assert "Droid Sans Fallback" in stack
    serif = css_serif_stack()
    assert "WenQuanYi Micro Hei" in serif
    assert "Droid Sans Fallback" in serif
    display = css_display_stack()
    assert "Comfortaa" in display


def test_brand_assets_and_comfortaa_faces():
    from reports.fonts import (
        arbor_wordmark_data_uri,
        comfortaa_font_face_css,
        embedded_comfortaa_font_face_css,
    )

    uri = arbor_wordmark_data_uri("brand")
    assert uri.startswith("data:image/png;base64,")
    assert len(uri) > 200
    assert "Comfortaa" in comfortaa_font_face_css()
    assert "comfortaa-latin-400.woff2" in comfortaa_font_face_css()
    embedded = embedded_comfortaa_font_face_css()
    assert "Comfortaa" in embedded
    assert "data:font/woff2;base64," in embedded


def test_web_pages_use_shared_cjk_stacks():
    from web.chat import build_chat_page
    from web.track_record import build_track_record_html

    chat = build_chat_page(briefing="测试简报")
    assert "WenQuanYi Micro Hei" in chat
    assert "Droid Sans Fallback" in chat
    tr = build_track_record_html({"total": 0, "weeks": []})
    assert "WenQuanYi Micro Hei" in tr
    assert "Droid Sans Fallback" in tr
