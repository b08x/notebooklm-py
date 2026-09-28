from rich.layout import Layout


def build_layout() -> Layout:
    layout = Layout(name="root")

    layout.split_column(
        Layout(name="header", size=3), Layout(name="body"), Layout(name="footer", size=3)
    )

    # The sidebar carries titles, badges and counts; at 1:3 it truncated nearly
    # every title, so it gets a wider share and a floor.
    layout["body"].split_row(
        Layout(name="sidebar", ratio=2, minimum_size=34), Layout(name="content", ratio=5)
    )

    layout["content"].split_column(Layout(name="results", ratio=1), Layout(name="detail", ratio=1))

    return layout
