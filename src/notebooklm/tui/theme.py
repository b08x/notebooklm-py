from rich.theme import Theme

# Dark warm palette from b08x.github.io dark mode
COLORS = {
    "background": "#211C17",
    "surface": "#2A241D",
    "foreground": "#ECE3D2",
    "accent": "#C97A5E",
    "secondary": "#84A4C0",
    "success": "#97AC78",
    "warning": "#DB8A5C",
    "danger": "#D2715F",
    "muted": "#968A78",
}

THEME = Theme(
    {
        # Base colors mapping
        "background": f"on {COLORS['background']}",
        "surface": f"on {COLORS['surface']}",
        "foreground": COLORS["foreground"],
        # Semantic roles
        "header": f"bold {COLORS['foreground']} on {COLORS['surface']}",
        "sidebar": f"{COLORS['foreground']} on {COLORS['background']}",
        "main": f"{COLORS['foreground']} on {COLORS['background']}",
        "footer": f"{COLORS['muted']} on {COLORS['surface']}",
        "border": COLORS["surface"],
        "prompt": f"bold {COLORS['accent']} on {COLORS['background']}",
        "error": f"bold {COLORS['danger']}",
        "success": f"bold {COLORS['success']}",
        "warning": f"bold {COLORS['warning']}",
        "info": f"{COLORS['secondary']}",
        "muted": f"{COLORS['muted']}",
        "selected": f"bold {COLORS['background']} on {COLORS['accent']}",
    }
)
