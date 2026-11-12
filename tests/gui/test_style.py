"""The palette and stylesheet (phase 5, step 6)."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from painter.gui.style import PAINTER, build_qss, contrast, load_fonts  # noqa: E402


def test_stylesheet_uses_the_five_base_colours():
    qss = build_qss()
    for c in ("#EFE7D5", "#252525", "#F4BE4F", "#8A9C72", "#B82D58"):
        assert c in qss


def test_text_pairs_pass_wcag_aa():
    p = PAINTER
    for fg, bg in [(p.on_primary, p.primary), (p.on_highlight, p.highlight),
                   (p.ink, p.background), (p.muted, p.background), (p.muted, p.surface),
                   (p.ink, p.secondary_tint), (p.ink, p.highlight_tint), (p.ink, p.primary_tint)]:
        assert contrast(fg, bg) >= 4.5, (fg, bg)


def test_bundled_fonts_load(painter_qapp):
    fams = load_fonts()
    assert "Work Sans" in fams and any("Bricolage" in f for f in fams)
