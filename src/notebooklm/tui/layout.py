from rich.layout import Layout

from .state import Mode


def build_layout(mode: Mode = Mode.NOTEBOOKS) -> Layout:
    layout = Layout(name="root")

    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="modebar", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )

    if mode == Mode.JOBS:
        layout["body"].split_row(
            Layout(name="jobs_list", ratio=3), Layout(name="jobs_detail", ratio=4)
        )
        return layout

    # The sidebar carries titles, badges and counts; at 1:3 it truncated nearly
    # every title, so it gets a wider share and a floor.
    layout["body"].split_row(
        Layout(name="sidebar", ratio=2, minimum_size=34), Layout(name="content", ratio=5)
    )

    layout["content"].split_column(Layout(name="results", ratio=1), Layout(name="detail", ratio=1))

    return layout
