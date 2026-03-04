"""Estilos de UI para VIES VAT Validator

Centraliza todas las constantes visuales (colores, fuentes, tamaños, espaciado) para mejorar
mantenibilidad y consistencia en toda la aplicación.
"""


class UIStyles:
    """Contenedor para todas las constantes de estilo de UI."""

    # -------------------------
    # COLORS - Main Theme 
    # -------------------------
    
    # Background colors
    BG_MAIN = "#E8F0FE"  # soft blue background
    HEADER_BG = "#0b3a78"  # navy blue header
    CARD_BG = "#FFFFFF"  # white cards
    CARD_BORDER = "#E6E8EF"  # subtle border
    
    # Log styling
    LOG_BG = "#fafbfc"
    LOG_FG = "#1f2937"
    
    # Tree row colors (zebra striping)
    TREE_ROW_EVEN = "#fafbfc"
    TREE_ROW_ODD = "#ffffff"
    
    # Banner styling
    BANNER_BG = "#E6F6F8"  # light cyan background
    BANNER_BORDER = "#2FB5C4"  # cyan border
    BANNER_FG = "#0F3A6D"  # dark blue text
    BANNER_BTN_BG = "#2FB5C4"  # cyan button
    BANNER_BTN_FG = "white"
    BANNER_BTN_ACTIVE_BG = "#239EAC"  # darker cyan
    BANNER_BTN_ACTIVE_FG = "white"
    
    # Text colors
    TEXT_PRIMARY = "#1f2937"  # dark text
    TEXT_HEADER = "#ffffff"  # white (for dark backgrounds)
    TEXT_SUBTITLE = "#c7d2fe"  # light blue (for header)
    TOOLTIP_BG = "#fff9e6"  # light yellow
    TOOLTIP_FG = "#333"

    # Tree status colors
    STATUS_VALID = "#0f766e"  # teal
    STATUS_INVALID = "#b91c1c"  # dark red
    STATUS_PENDING = "#b45309"  # orange
    STATUS_THROTTLED = "#b45309"  # orange
    STATUS_TIMEOUT = "#b45309"  # orange
    STATUS_ERROR = "#b45309"  # orange
    STATUS_PENDING_MAX = "#64748b"  # slate
    STATUS_INVALID_FORMAT = "#64748b"  # slate
    
    # Log tag colors
    LOG_OK = "#10b981"  # green
    LOG_WARN = "#f59e0b"  # amber
    LOG_ERROR = "#ef4444"  # red
    LOG_INFO = "#1f2937"  # dark
    LOG_DEBUG = "#6b7280"  # gray

    # Treeview heading colors
    TREEVIEW_HEADING_BG = "#f0f2f5"
    TREEVIEW_HEADING_FG = "#1f2937"

    # -------------------------
    # FONTS
    # -------------------------
    
    FONT_MAIN = ("Segoe UI", 11)  # default font
    FONT_TITLE = ("Segoe UI", 22, "bold")  # page title
    FONT_SUBTITLE = ("Segoe UI", 10)  # subtitle
    FONT_LABEL = ("Segoe UI", 12, "bold")  # section labels
    FONT_HEADING = ("Segoe UI", 10, "bold")  # treeview headings
    FONT_SMALL = ("Segoe UI", 9)  # small text (buttons, status)
    FONT_XSMALL = ("Segoe UI", 8)  # extra small (tooltips)
    FONT_MONOSPACE = ("Consolas", 9)  # log text
    FONT_STATUS = ("Segoe UI", 9)  # status bar

    # -------------------------
    # SIZES & SPACING
    # -------------------------
    
    # Window geometry
    WINDOW_WIDTH = 1250
    WINDOW_HEIGHT = 760
    WINDOW_MIN_WIDTH = 1100
    WINDOW_MIN_HEIGHT = 650
    
    # Padding and margins
    MAIN_PADDING = 20  # main container padding
    CONTENT_PADDING_X = 16  # horizontal padding for sections
    CONTENT_PADDING_Y = 12  # vertical padding between sections
    BUTTON_PADX = 14  # horizontal button padding
    BUTTON_PADY = 8  # vertical button padding
    BUTTON_SMALL_PADX = 10  # small button padding
    BUTTON_SMALL_PADY = 4
    CARD_PADDING_X = 12  # card internal padding
    CARD_PADDING_Y = 8
    CARD_BORDERWIDTH = 1
    CARD_RELIEF = "flat"
    BUTTON_BORDERWIDTH = 1
    BANNER_BORDERWIDTH = 1
    BANNER_PADDING_X = 12
    BANNER_PADDING_Y = 8

    # Treeview and log settings
    TREEVIEW_HEIGHT = 25
    TREEVIEW_ROWHEIGHT = 24
    LOG_HEIGHT_LINES = 10
    NOTEBOOK_TAB_PADDING_X = 16
    NOTEBOOK_TAB_PADDING_Y = 8

    # Column widths
    COL_VAT = 140
    COL_COUNTRY = 80
    COL_NUMBER = 120
    COL_NAME = 160
    COL_STATUS = 130
    COL_ATTEMPTS = 80
    COL_LAST_CHECK = 130
    COL_NEXT_RETRY = 130
    COL_ERROR = 180
    COL_ACTION = 100

    # Tooltips
    TOOLTIP_DELAY_MS = 500
    TOOLTIP_PADX = 8
    TOOLTIP_PADY = 6
    TOOLTIP_WRAPLENGTH = 300
