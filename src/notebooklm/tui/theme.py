from rich.theme import Theme

# Low-chroma neutral base with a single violet accent reserved for focus and
# selection. Status hues (success/warning/danger) appear only on status text,
# never as decoration, so a colored glyph always carries meaning.
COLORS = {
    "background": "#18181B",
    "surface": "#232329",
    "selection": "#3B3363",
    "foreground": "#E4E4E7",
    "muted": "#8B8B94",
    "subtle": "#52525B",
    "border": "#3F3F46",
    "primary": "#A78BFA",
    "accent": "#A78BFA",
    "secondary": "#7DD3FC",
    "success": "#4ADE80",
    "warning": "#FBBF24",
    "danger": "#F87171",
    # Categorical hues for domain tags and entity spans: equal lightness,
    # reduced saturation, so no single category shouts over the others.
    "cat_blue": "#93C5FD",
    "cat_pink": "#F0ABFC",
    "cat_amber": "#FCD34D",
    "cat_green": "#86EFAC",
    "cat_teal": "#5EEAD4",
}

THEME = Theme(
    {
        # Base colors mapping
        "background": f"on {COLORS['background']}",
        "surface": f"on {COLORS['surface']}",
        "foreground": COLORS["foreground"],
        # Regions
        "header": f"{COLORS['foreground']} on {COLORS['surface']}",
        "sidebar": f"{COLORS['foreground']} on {COLORS['background']}",
        "main": f"{COLORS['foreground']} on {COLORS['background']}",
        "footer": f"{COLORS['muted']} on {COLORS['background']}",
        "border": COLORS["border"],
        "border.focus": COLORS["primary"],
        # Typography: one heading weight, one body, one secondary tier.
        "heading": f"bold {COLORS['foreground']}",
        "label": COLORS["muted"],
        "muted": COLORS["muted"],
        "subtle": COLORS["subtle"],
        "key": f"bold {COLORS['primary']}",
        "prompt": f"bold {COLORS['primary']}",
        # Status
        "error": COLORS["danger"],
        "success": COLORS["success"],
        "warning": COLORS["warning"],
        "info": COLORS["secondary"],
        # Kept for callers that still use the bold variants.
        "bold_primary": f"bold {COLORS['primary']}",
        "bold_info": f"bold {COLORS['secondary']}",
        "bold_accent": f"bold {COLORS['accent']}",
        "primary": COLORS["primary"],
        "accent": COLORS["accent"],
        # Selection: tinted bar plus bold, readable without a saturated fill.
        "selected": f"bold {COLORS['foreground']} on {COLORS['selection']}",
        "marker": f"bold {COLORS['primary']}",
        # Notebook domain tags
        "tag.gemini": COLORS["cat_blue"],
        "tag.claude": COLORS["cat_pink"],
        "tag.eng": COLORS["cat_amber"],
        "tag.dev": COLORS["cat_green"],
        "tag.other": COLORS["muted"],
        # Artifact badges
        "badge.audio": COLORS["cat_teal"],
        "badge.docs": COLORS["muted"],
        "badge.recent": COLORS["warning"],
        # Named-entity spans in assessment chunks
        "entity.person": COLORS["cat_blue"],
        "entity.org": COLORS["cat_green"],
        "entity.time": COLORS["cat_amber"],
        "entity.money": COLORS["cat_pink"],
        "entity.group": COLORS["cat_teal"],
        "entity.default": COLORS["foreground"],
    }
)
