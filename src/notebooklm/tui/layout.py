from rich.layout import Layout


def build_layout() -> Layout:
    layout = Layout(name="root")

    layout.split_column(
        Layout(name="header", size=3), Layout(name="body"), Layout(name="footer", size=3)
    )

    layout["body"].split_row(Layout(name="sidebar", ratio=2), Layout(name="main", ratio=3))

    layout["sidebar"].split_column(
        Layout(name="notebooks", ratio=3), Layout(name="commands", ratio=1)
    )

    return layout
