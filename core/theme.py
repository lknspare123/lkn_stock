"""
core/theme.py — All colors, fonts, and style constants in one place.
"""

# ── Color Palette ────────────────────────────────────────────────────────────
COLORS = {
    # Backgrounds
    "bg_dark":      "#0F1117",
    "bg_sidebar":   "#161B22",
    "bg_card":      "#1C2128",
    "bg_surface":   "#21262D",
    "bg_input":     "#161B22",
    "bg_hover":     "#2D333B",

    # Accent
    "accent":       "#58A6FF",
    "accent_hover": "#79B8FF",
    "accent_dim":   "#1F3A5F",

    # Status
    "success":      "#3FB950",
    "warning":      "#D29922",
    "danger":       "#F85149",
    "info":         "#58A6FF",

    # Text
    "text_primary":   "#E6EDF3",
    "text_secondary": "#8B949E",
    "text_muted":     "#484F58",
    "text_on_accent": "#FFFFFF",

    # Borders
    "border":       "#30363D",
    "border_focus": "#58A6FF",

    # Table
    "table_header": "#161B22",
    "table_row":    "#1C2128",
    "table_alt":    "#21262D",
    "table_select": "#1F3A5F",
}

# ── Font Families ────────────────────────────────────────────────────────────
FONTS = {
    "body":    ("Khmer OS Siemreap", 10),
    "body_sm": ("Khmer OS Siemreap", 9),
    "heading": ("Khmer OS Siemreap", 14, "bold"),
    "title":   ("Khmer OS Siemreap", 18, "bold"),
    "code":    ("Consolas", 10),  # Retained monospace for code components
    "khmer":   ("Khmer OS Siemreap", 11),
    "num":     ("Khmer OS Siemreap", 10),
    "num_lg":  ("Khmer OS Siemreap", 16, "bold"),
}

# ── Sizing ───────────────────────────────────────────────────────────────────
SIZES = {
    "sidebar_w":  220,
    "toolbar_h":  52,
    "row_h":      30,
    "padding":    16,
    "radius":     6,
    "btn_h":      32,
}

NAV_ITEMS = [
    ("Dashboard",      "⬛",  "dashboard"),
    ("Items",          "📦",  "items"),
    ("Main Stock",     "🗄",   "main_stock"),
    ("Stock Receive",  "📥",  "receive"),
    ("Print Labels",   "🏷",  "print_labels"),
    ("Sales",          "💰",  "sales"),
    ("Branch Transfer","🚚",  "branch_transfer"),  # Added for your new transfer page
    ("Reports",        "📊",  "reports"),
    ("Settings",       "⚙",   "settings"),
]