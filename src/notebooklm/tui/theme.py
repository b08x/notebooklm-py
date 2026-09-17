from rich.theme import Theme

# Omega-13 Logo Variants-selection palette
COLORS = {
    "background": "#1F1F24",
    "surface": "#4C1D95",
    "foreground": "#FFFFFF",
    "primary": "#7C3AED",
    "accent": "#F0913F",
    "secondary": "#A855F7",
    "success": "#33E666",
    "warning": "#F0913F",
    "danger": "#B7410E",
    "muted": "#A855F7",
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
        "footer": f"{COLORS['muted']} on {COLORS['background']}",
        "border": COLORS["primary"],
        "prompt": f"bold {COLORS['accent']} on {COLORS['background']}",
        "error": f"bold {COLORS['danger']}",
        "success": f"bold {COLORS['success']}",
        "warning": f"bold {COLORS['warning']}",
        "info": f"{COLORS['secondary']}",
        "muted": f"{COLORS['muted']}",
        # Selection highlight (very visible)
        "selected": f"bold {COLORS['background']} on {COLORS['accent']}",
    }
)
