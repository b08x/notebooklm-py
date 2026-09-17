from rich.layout import Layout


def build_layout() -> Layout:
    layout = Layout(name="root")

    layout.split_column(
        Layout(name="header", size=3), Layout(name="body"), Layout(name="footer", size=3)
    )

    layout["body"].split_row(Layout(name="sidebar", ratio=1), Layout(name="content", ratio=3))

    layout["content"].split_column(Layout(name="results", ratio=1), Layout(name="detail", ratio=1))

    return layout
