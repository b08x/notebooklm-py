from notebooklm.tui.layout import build_layout


def test_layout_structure():
    layout = build_layout()
    assert layout.name == "root"
    assert layout.get("header") is not None
    assert layout.get("body") is not None
    assert layout.get("footer") is not None

    body = layout.get("body")
    assert body.get("sidebar") is not None
    assert body.get("content") is not None
    content = body.get("content")
    assert content.get("results") is not None
    assert content.get("detail") is not None
