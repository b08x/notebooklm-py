from notebooklm.tui.theme import COLORS, THEME


def test_theme_keys():
    assert "background" in COLORS
    assert "accent" in COLORS

    styles = THEME.styles
    assert "header" in styles
    assert "sidebar" in styles
    assert "main" in styles
    assert "footer" in styles
    assert "prompt" in styles
    assert "error" in styles
    assert "success" in styles
    assert "warning" in styles
    assert "info" in styles
    assert "muted" in styles
    assert "border" in styles
    assert "foreground" in styles
