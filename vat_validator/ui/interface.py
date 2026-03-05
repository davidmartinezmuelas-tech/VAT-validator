"""Interfaz gráfica de usuario para VIES VAT Validator.

Aplicación Tkinter para validación masiva de números VAT contra el servicio VIES.
Proporciona:
- Carga de archivos Excel con detección automática de columnas
- Validación concurrente con interfaz responsiva
- Exportación de resultados
- Reintentos manuales y automáticos
- Logs en tiempo real y visualización de resultados
"""

from __future__ import annotations

import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk

from vat_validator.models import (
    VatInfo,
    VatStatus,
    CountryNumber,
    PENDING_STATES,
    VALIDATED_STATES,
    parse_vat,
    get_vat_number_only,
    status_label,
    status_code,
)
from vat_validator.vies_client import ViesValidator
from vat_validator.retry_logic import RetryScheduler
from vat_validator.callbacks import ValidationCallbacks, BatchSummary
from vat_validator.excel_handler import load_excel, save_excel
from .styles import UIStyles


class Tooltip:
    """Helper simple de tooltips para widgets ttk."""
    def __init__(self, widget, text: str, delay_ms: int = UIStyles.TOOLTIP_DELAY_MS):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tipwindow = None
        self.id = None
        
        widget.bind("<Enter>", self.on_enter, add=True)
        widget.bind("<Leave>", self.on_leave, add=True)
    
    def on_enter(self, event):
        self.schedule()
    
    def on_leave(self, event):
        self.unschedule()
        self.hidetip()
    
    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(self.delay_ms, self.showtip)
    
    def unschedule(self):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
    
    def showtip(self):
        if self.tipwindow:
            return
        
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        
        label = tk.Label(tw, text=self.text, background=UIStyles.TOOLTIP_BG, foreground=UIStyles.TOOLTIP_FG,
                         relief=UIStyles.CARD_RELIEF, borderwidth=UIStyles.TOOLTIP_BORDERWIDTH, font=UIStyles.FONT_XSMALL,
                         padx=UIStyles.TOOLTIP_PADX, pady=UIStyles.TOOLTIP_PADY, wraplength=UIStyles.TOOLTIP_WRAPLENGTH)
        label.pack()
    
    def hidetip(self):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


class UIThreadCallbacks(ValidationCallbacks):
    """Marshalling de callbacks de workers del core al thread principal de Tkinter (thread-safe).
    
    Los workers (desde RetryScheduler) se ejecutan en threads separados y emiten callbacks.
    Todas las actualizaciones de UI deben ocurrir solo en el thread principal de Tkinter.
    Este adaptador usa root.after(0, callback) para programar actualizaciones.
    
    Garantiza que actualizaciones de tablas, logs, progreso y banners están sincronizadas
    con el event loop de Tkinter, previniendo race conditions y crashes.
    """

    def __init__(self, app: "VATValidatorApp"):
        self.app = app

    def on_vat_updated(self, key: CountryNumber, vat_info: VatInfo, result: dict) -> None:
        """Notifica a UI que un VAT ha sido procesado."""
        self.app.root.after(0, lambda: self.app._on_vat_updated_main_thread(key, vat_info, result))

    def on_progress(self, done: int, total: int) -> None:
        """Notifica a UI del progreso de validación."""
        self.app.root.after(0, lambda: self.app._on_progress_main_thread(done, total))

    def on_banner_update(self, text: str, next_retry_seconds: Optional[int] = None) -> None:
        """Actualiza banner con mensaje de estado y cuenta regresiva opcional."""
        self.app.root.after(0, lambda: self.app._on_banner_update_main_thread(text, next_retry_seconds))

    def on_batch_finished(self, summary: BatchSummary) -> None:
        """Notifica a UI que lote de validación completo ha terminado."""
        self.app.root.after(0, lambda: self.app._on_batch_finished_main_thread(summary))


class VATValidatorApp:
    """Aplicación principal de validación de VAT con interfaz Tkinter.
    
    Orquesta carga de Excel, validación concurrente, visualización de resultados
    y exportación. Mantiene estado de UI sincronizado con datos de validación.
    """
    
    # Estados from core
    PENDING_STATES = PENDING_STATES
    VALIDATED_STATES = VALIDATED_STATES
    
    # VIES web page
    VIES_WEB = ViesValidator.VIES_WEB

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("VIES VAT Validator")
        self.root.geometry(f"{UIStyles.WINDOW_WIDTH}x{UIStyles.WINDOW_HEIGHT}")
        self.root.minsize(UIStyles.WINDOW_MIN_WIDTH, UIStyles.WINDOW_MIN_HEIGHT)

        self.selected_file: Optional[Path] = None
        self.processing = False
        self._worker_threads: List[threading.Thread] = []
        self._stop_event = threading.Event()

        # Modelo
        self.vat_data: Dict[CountryNumber, VatInfo] = {}
        self._cache: Dict[CountryNumber, VatInfo] = {}  # cache en memoria por sesión (solo VALID/INVALID)

        # UI state
        self.status_var = tk.StringVar(value="Listo")
        self.log_autoscroll_var = tk.BooleanVar(value=True)

        # Search vars
        self.search_pending_var = tk.StringVar(value="")
        self.search_validated_var = tk.StringVar(value="")

        # Map iids per tree
        self.pending_tree_iids: Dict[CountryNumber, str] = {}
        self.validated_tree_iids: Dict[CountryNumber, str] = {}

        # Stack for undo last validated
        self.undo_stack: List[Tuple[CountryNumber, VatStatus]] = []

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.apply_theme()
        self.setup_ui()

        self.log_info("Aplicación iniciada. Carga un Excel para comenzar.")

    # -------------------------
    # THEME / UI
    # -------------------------

    def apply_theme(self) -> None:
        style = ttk.Style()
        
        self.root.configure(bg=UIStyles.BG_MAIN)
        
        style.configure("Treeview", rowheight=UIStyles.TREEVIEW_ROWHEIGHT, background=UIStyles.CARD_BG, fieldbackground=UIStyles.CARD_BG, foreground=UIStyles.TREEVIEW_HEADING_FG)
        style.configure("Treeview.Heading", font=UIStyles.FONT_HEADING, background=UIStyles.TREEVIEW_HEADING_BG, foreground=UIStyles.TREEVIEW_HEADING_FG)
        style.configure("TNotebook", background=UIStyles.CARD_BG)
        style.configure("TNotebook.Tab", padding=(UIStyles.NOTEBOOK_TAB_PADDING_X, UIStyles.NOTEBOOK_TAB_PADDING_Y))

    def setup_ui(self) -> None:
        """Construye la interfaz gráfica con layout grid de 5 filas.
        
        Estructura del root con grid:
        - Row 0: Header (no weight)
        - Row 1: Actions/Toolbar (no weight)
        - Row 2: Table/Notebook (weight 3) - crece más
        - Row 3: Log (weight 1) - crece menos
        - Row 4: Bottom bar fijo (no weight)
        """
        # ==== ROOT CONFIGURATION (GRID) ====
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)  # Header - fijo
        self.root.rowconfigure(1, weight=0)  # Actions - fijo
        self.root.rowconfigure(2, weight=3)  # Table - crece 3x
        self.root.rowconfigure(3, weight=1)  # Log - crece 1x
        self.root.rowconfigure(4, weight=0)  # Bottom - fijo

        # ==== ROW 0: HEADER ====
        frame_header = tk.Frame(self.root, bg=UIStyles.BG_MAIN)
        frame_header.grid(row=0, column=0, sticky="ew", padx=UIStyles.MAIN_PADDING, pady=UIStyles.MAIN_PADDING)
        frame_header.columnconfigure(0, weight=1)

        header = tk.Frame(frame_header, bg=UIStyles.HEADER_BG)
        header.pack(fill=tk.X, pady=(0, UIStyles.CONTENT_PADDING_Y))
        header.columnconfigure(0, weight=1)

        title = tk.Label(header, text="VIES VAT Validator", font=UIStyles.FONT_TITLE, bg=UIStyles.HEADER_BG, fg=UIStyles.TEXT_HEADER)
        title.pack(side=tk.TOP, fill=tk.X, padx=UIStyles.CONTENT_PADDING_X, pady=(UIStyles.BUTTON_PADY, 0), anchor="w")
        
        subtitle = tk.Label(header, text="Validación masiva de números VAT europeos", font=UIStyles.FONT_SUBTITLE, bg=UIStyles.HEADER_BG, fg=UIStyles.TEXT_SUBTITLE)
        subtitle.pack(side=tk.TOP, fill=tk.X, padx=UIStyles.CONTENT_PADDING_X, pady=(2, UIStyles.BUTTON_PADY), anchor="w")

        # ==== ROW 1: TOOLBAR/ACTIONS ====
        frame_actions = tk.Frame(self.root, bg=UIStyles.BG_MAIN)
        frame_actions.grid(row=1, column=0, sticky="ew", padx=UIStyles.MAIN_PADDING, pady=(0, UIStyles.CARD_PADDING_Y))
        frame_actions.columnconfigure(4, weight=1)

        self.load_btn = ttk.Button(frame_actions, text="Cargar Excel", bootstyle="primary", padding=(UIStyles.BUTTON_PADX, UIStyles.BUTTON_PADY), command=self.load_excel)
        self.load_btn.pack(side=tk.LEFT, padx=(0, UIStyles.CARD_PADDING_Y))

        self.validate_btn = ttk.Button(frame_actions, text="Validar", bootstyle="primary", padding=(UIStyles.BUTTON_PADX, UIStyles.BUTTON_PADY), command=self.start_validation)
        self.validate_btn.pack(side=tk.LEFT, padx=(0, UIStyles.CARD_PADDING_Y))
        self.validate_btn.state(["disabled"])

        self.retry_btn = ttk.Button(frame_actions, text="Reintentar", bootstyle="primary", padding=(UIStyles.BUTTON_PADX, UIStyles.BUTTON_PADY), command=self.retry_pending)
        self.retry_btn.pack(side=tk.LEFT, padx=(0, UIStyles.CARD_PADDING_Y))
        self.retry_btn.state(["disabled"])
        Tooltip(self.retry_btn, "Reintenta los pendientes que ya han cumplido el tiempo de espera.")

        self.validate_selected_btn = ttk.Button(frame_actions, text="Validar seleccionado", bootstyle="primary", padding=(14, 8), command=self.validate_selected)
        self.validate_selected_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.validate_selected_btn.state(["disabled"])
        Tooltip(self.validate_selected_btn, "Valida únicamente el VAT seleccionado.")

        self.undo_btn = ttk.Button(frame_actions, text="Deshacer último", bootstyle="secondary-outline", padding=(10, 6), command=self.undo_last_validated)
        self.undo_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.undo_btn.state(["disabled"])

        # Export menu button
        self.export_menu_btn = ttk.Menubutton(frame_actions, text="Exportar ▾", bootstyle="secondary-outline")
        self.export_menu_btn.pack(side=tk.RIGHT, padx=(0, 0))
        self.export_menu_btn.state(["disabled"])
        
        self.export_menu = tk.Menu(self.export_menu_btn, tearoff=0)
        self.export_menu.add_command(label="Exportar todo", command=lambda: self.export_to_excel(scope="all"))
        self.export_menu.add_command(label="Exportar validados", command=lambda: self.export_to_excel(scope="validated"))
        self.export_menu.add_command(label="Exportar pendientes", command=lambda: self.export_to_excel(scope="pending"))
        self.export_menu_btn["menu"] = self.export_menu

        # ==== ROW 2: TABLE CONTENT ====
        frame_table = tk.Frame(self.root, bg=UIStyles.BG_MAIN)
        frame_table.grid(row=2, column=0, sticky="nsew", padx=UIStyles.MAIN_PADDING, pady=(0, UIStyles.CARD_PADDING_Y))
        frame_table.columnconfigure(0, weight=1)
        frame_table.rowconfigure(0, weight=1)

        # Results card
        results_card = tk.Frame(frame_table, bg=UIStyles.CARD_BG, relief=UIStyles.CARD_RELIEF, borderwidth=UIStyles.CARD_BORDERWIDTH, highlightbackground=UIStyles.CARD_BORDER, highlightthickness=1)
        results_card.pack(fill=tk.BOTH, expand=True)
        results_card.columnconfigure(0, weight=1)
        results_card.rowconfigure(2, weight=1)
        
        tk.Label(results_card, text="Resultados", font=UIStyles.FONT_LABEL, bg=UIStyles.CARD_BG, fg=UIStyles.TEXT_PRIMARY, anchor="w", padx=UIStyles.CARD_PADDING_X, pady=UIStyles.CARD_PADDING_Y).grid(row=0, column=0, sticky="ew")

        # Banner frame
        self.banner_frame = tk.Frame(results_card, bg=UIStyles.BANNER_BG, relief=UIStyles.CARD_RELIEF, borderwidth=UIStyles.BANNER_BORDERWIDTH, highlightbackground=UIStyles.BANNER_BORDER, highlightthickness=1)
        self.banner_frame.grid(row=1, column=0, sticky="ew", padx=UIStyles.CARD_PADDING_Y, pady=UIStyles.CARD_PADDING_Y)
        self.banner_frame.columnconfigure(0, weight=1)
        self.banner_frame.grid_remove()
        
        banner_content = tk.Frame(self.banner_frame, bg=UIStyles.BANNER_BG)
        banner_content.grid(row=0, column=0, sticky="ew", padx=UIStyles.BANNER_PADDING_X, pady=UIStyles.BANNER_PADDING_Y)
        banner_content.columnconfigure(0, weight=1)
        
        self.banner_label = tk.Label(banner_content, text="", font=UIStyles.FONT_SMALL, bg=UIStyles.BANNER_BG, fg=UIStyles.BANNER_FG)
        self.banner_label.grid(row=0, column=0, sticky="w")
        
        banner_btn_frame = tk.Frame(banner_content, bg=UIStyles.BANNER_BG)
        banner_btn_frame.grid(row=0, column=1, sticky="e", padx=(UIStyles.BANNER_PADDING_X, 0))
        
        self.banner_go_pending_btn = tk.Button(banner_btn_frame, text="Ir a Pendientes", bg=UIStyles.BANNER_BTN_BG, fg=UIStyles.BANNER_BTN_FG, font=UIStyles.FONT_SMALL, relief=UIStyles.CARD_RELIEF, borderwidth=UIStyles.BUTTON_BORDERWIDTH, padx=UIStyles.BUTTON_SMALL_PADX, pady=UIStyles.BUTTON_SMALL_PADY, cursor="hand2", command=self._go_to_pending_tab, activebackground=UIStyles.BANNER_BTN_ACTIVE_BG, activeforeground=UIStyles.BANNER_BTN_ACTIVE_FG)
        self.banner_go_pending_btn.grid(row=0, column=0, padx=(0, UIStyles.BUTTON_SMALL_PADX))
        
        self.banner_retry_btn = tk.Button(banner_btn_frame, text="Reintentar ahora", bg=UIStyles.BANNER_BTN_BG, fg=UIStyles.BANNER_BTN_FG, font=UIStyles.FONT_SMALL, relief=UIStyles.CARD_RELIEF, borderwidth=UIStyles.BUTTON_BORDERWIDTH, padx=UIStyles.BUTTON_SMALL_PADX, pady=UIStyles.BUTTON_SMALL_PADY, cursor="hand2", command=self.retry_pending, activebackground=UIStyles.BANNER_BTN_ACTIVE_BG, activeforeground=UIStyles.BANNER_BTN_ACTIVE_FG)
        self.banner_retry_btn.grid(row=0, column=1)

        # Notebook (Pendientes / Validados)
        self.notebook = ttk.Notebook(results_card)
        self.notebook.grid(row=2, column=0, sticky="nsew", padx=UIStyles.CONTENT_PADDING_X, pady=UIStyles.CONTENT_PADDING_Y)

        # Pending tab
        pending_frame = ttk.Frame(self.notebook)
        self.notebook.add(pending_frame, text="Pendientes")
        self._build_tree_frame(pending_frame, kind="pending")

        # Validated tab
        validated_frame = ttk.Frame(self.notebook)
        self.notebook.add(validated_frame, text="Validados")
        self._build_tree_frame(validated_frame, kind="validated")

        # ==== ROW 3: LOG SECTION ====
        frame_log = tk.Frame(self.root, bg=UIStyles.BG_MAIN)
        frame_log.grid(row=3, column=0, sticky="nsew", padx=UIStyles.MAIN_PADDING, pady=(0, UIStyles.CARD_PADDING_Y))
        frame_log.columnconfigure(0, weight=1)
        frame_log.rowconfigure(1, weight=1)

        tk.Label(frame_log, text="Actividad", font=UIStyles.FONT_LABEL, bg=UIStyles.BG_MAIN, fg=UIStyles.TEXT_PRIMARY, anchor="w").grid(row=0, column=0, sticky="ew", padx=8, pady=(0, 4))

        log_text_frame = tk.Frame(frame_log, bg=UIStyles.CARD_BG, relief=UIStyles.CARD_RELIEF, borderwidth=UIStyles.CARD_BORDERWIDTH)
        log_text_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        log_text_frame.columnconfigure(0, weight=1)
        log_text_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_text_frame, height=UIStyles.LOG_HEIGHT_LINES, bg=UIStyles.LOG_BG, fg=UIStyles.LOG_FG, font=UIStyles.FONT_MONOSPACE, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_scrollbar = ttk.Scrollbar(log_text_frame, orient=tk.VERTICAL, command=self.log_text.yview, bootstyle="round")
        log_scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

        self._install_log_scroll_detection(log_scrollbar)

        # Log tags
        self.log_text.tag_config("OK", foreground=UIStyles.LOG_OK)
        self.log_text.tag_config("WARN", foreground=UIStyles.LOG_WARN)
        self.log_text.tag_config("ERROR", foreground=UIStyles.LOG_ERROR)
        self.log_text.tag_config("INFO", foreground=UIStyles.LOG_INFO)
        self.log_text.tag_config("DEBUG", foreground=UIStyles.LOG_DEBUG)

        # Log controls
        log_control_frame = tk.Frame(frame_log, bg=UIStyles.BG_MAIN)
        log_control_frame.grid(row=2, column=0, sticky="ew", padx=8)

        ttk.Button(log_control_frame, text="Limpiar registro", bootstyle="secondary-outline", padding=(8, 4), command=self.clear_log).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(log_control_frame, text="Copiar registro", bootstyle="secondary-outline", padding=(8, 4), command=self.copy_log).pack(side=tk.LEFT)

        # ==== ROW 4: FIXED BOTTOM BAR ====
        frame_bottom = ttk.Frame(self.root)
        frame_bottom.grid(row=4, column=0, sticky="ew", padx=UIStyles.MAIN_PADDING, pady=(UIStyles.CARD_PADDING_Y, UIStyles.MAIN_PADDING))
        frame_bottom.grid_columnconfigure(0, weight=1)
        frame_bottom.grid_columnconfigure(1, weight=0)
        frame_bottom.grid_columnconfigure(2, weight=0)

        # Progress bar (column 0, expandible)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(frame_bottom, variable=self.progress_var, mode="determinate", maximum=100, bootstyle="info")
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, UIStyles.CARD_PADDING_Y))

        # Status label (column 1, opcional)
        self.status_label = tk.Label(frame_bottom, textvariable=self.status_var, font=UIStyles.FONT_STATUS, fg=UIStyles.TEXT_PRIMARY, anchor="w")
        self.status_label.grid(row=0, column=1, sticky="ew", padx=(UIStyles.CARD_PADDING_Y, UIStyles.CARD_PADDING_Y))

        # Exit button (column 2, fijo a la derecha)
        self.exit_btn = ttk.Button(frame_bottom, text="Salir", bootstyle="danger-outline", padding=(UIStyles.BUTTON_PADX, UIStyles.BUTTON_PADY), command=self.exit_app)
        self.exit_btn.grid(row=0, column=2, sticky="e")

    def _build_tree_frame(self, parent: ttk.Frame, kind: str) -> None:
        """Construye un frame con búsqueda y tabla de VATs."""
        # Search frame
        search_frame = ttk.Frame(parent)
        search_frame.pack(fill=tk.X, pady=(0, 8))

        search_var = self.search_pending_var if kind == "pending" else self.search_validated_var
        ttk.Label(search_frame, text="Buscar:").pack(side=tk.LEFT, padx=(0, 8))
        entry = ttk.Entry(search_frame, textvariable=search_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        entry.bind("<KeyRelease>", lambda _e: self.refresh_trees())

        # Tree
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        if kind == "pending":
            cols = ("VAT", "País", "Número", "Nombre", "Estado", "Intentos", "Última verificación", "Siguiente intento", "Error", "Acción")
        else:
            cols = ("VAT", "País", "Número", "Nombre", "Estado", "Última verificación")

        tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=UIStyles.TREEVIEW_HEIGHT)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=120, anchor="w")

        tree.column("VAT", width=UIStyles.COL_VAT)
        tree.column("País", width=UIStyles.COL_COUNTRY, anchor="center")
        tree.column("Número", width=UIStyles.COL_NUMBER)
        tree.column("Nombre", width=UIStyles.COL_NAME)
        tree.column("Estado", width=UIStyles.COL_STATUS)
        
        if kind == "pending":
            tree.column("Intentos", width=UIStyles.COL_ATTEMPTS, anchor="center")
            tree.column("Última verificación", width=UIStyles.COL_LAST_CHECK)
            tree.column("Siguiente intento", width=UIStyles.COL_NEXT_RETRY)
            tree.column("Error", width=UIStyles.COL_ERROR)
            tree.column("Acción", width=UIStyles.COL_ACTION, anchor="center")
        else:
            tree.column("Última verificación", width=UIStyles.COL_LAST_CHECK)

        yscroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview, bootstyle="round")
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=yscroll.set)

        xscroll = ttk.Scrollbar(parent, orient=tk.HORIZONTAL, command=tree.xview, bootstyle="round")
        xscroll.pack(fill=tk.X)
        tree.configure(xscrollcommand=xscroll.set)

        # Zebra striping
        tree.tag_configure("row_even", background=UIStyles.TREE_ROW_EVEN)
        tree.tag_configure("row_odd", background=UIStyles.TREE_ROW_ODD)

        # Row tags (colors by status)
        tree.tag_configure("VALID", foreground=UIStyles.STATUS_VALID)
        tree.tag_configure("INVALID", foreground=UIStyles.STATUS_INVALID)
        tree.tag_configure("PENDING", foreground=UIStyles.STATUS_PENDING)
        tree.tag_configure("THROTTLED", foreground=UIStyles.STATUS_THROTTLED)
        tree.tag_configure("TIMEOUT", foreground=UIStyles.STATUS_TIMEOUT)
        tree.tag_configure("ERROR", foreground=UIStyles.STATUS_ERROR)
        tree.tag_configure("PENDING_MAX", foreground=UIStyles.STATUS_PENDING_MAX)
        tree.tag_configure("INVALID_FORMAT", foreground=UIStyles.STATUS_INVALID_FORMAT)

        tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        tree.bind("<Button-1>", self.on_tree_click)
        tree.bind("<Double-1>", self.on_tree_double_click)
        tree.bind("<Motion>", self.on_tree_motion)
        tree.bind("<Button-3>", self.show_context_menu)

        if kind == "pending":
            self.pending_tree = tree
        else:
            self.validated_tree = tree

        # Context menu
        self.tree_context_menu = tk.Menu(self.root, tearoff=0)
        self.tree_context_menu.add_command(label="Abrir en VIES (web)", command=self.open_vies_web)
        self.tree_context_menu.add_separator()
        self.tree_context_menu.add_command(label="Copiar número VAT", command=lambda: self.copy_vat(number_only=True))
        self.tree_context_menu.add_command(label="Copiar VAT completo", command=lambda: self.copy_vat(number_only=False))

    def _install_log_scroll_detection(self, scrollbar: ttk.Scrollbar) -> None:
        """Detecta cuando el usuario se separa del final del log."""
        def on_scroll(*args):
            self.log_text.yview(*args)
            self._check_log_autoscroll_state()

        scrollbar.configure(command=on_scroll)

        def on_mousewheel(event):
            try:
                self.log_text.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                return
            self._check_log_autoscroll_state()
            return "break"

        self.log_text.bind("<MouseWheel>", on_mousewheel)

    def _check_log_autoscroll_state(self) -> None:
        """Verifica si el usuario está al final del log."""
        _, last = self.log_text.yview()
        if last < 0.999:
            self.log_autoscroll_var.set(False)

    # -------------------------
    # STATUS / LOG
    # -------------------------

    def set_status(self, msg: str, timeout_ms: int = 4000) -> None:
        """Actualiza la barra de estado."""
        self.status_var.set(msg)
        self.status_label.update_idletasks()
        if timeout_ms > 0:
            self.root.after(timeout_ms, lambda: self.status_var.set("Listo"))

    def _log(self, level: str, message: str) -> None:
        """Escribe línea en el log con nivel."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}\n"
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line, level)
        if self.log_autoscroll_var.get():
            self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def log_ok(self, msg: str) -> None:
        self._log("OK", msg)

    def log_warn(self, msg: str) -> None:
        self._log("WARN", msg)

    def log_error(self, msg: str) -> None:
        self._log("ERROR", msg)

    def log_info(self, msg: str) -> None:
        self._log("INFO", msg)

    def log_debug(self, msg: str) -> None:
        self._log("DEBUG", msg)

    def clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.set_status("Registro limpiado", 2000)

    def copy_log(self) -> None:
        content = self.log_text.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.set_status("Registro copiado al portapapeles", 2500)

    # -------------------------
    # VAT helpers
    # -------------------------

    def accion_text(self, status: VatStatus) -> str:
        """Determina el texto del botón de acción para un estado."""
        if status in {VatStatus.THROTTLED, VatStatus.TIMEOUT, VatStatus.ERROR, VatStatus.PENDING_MAX}:
            return "[[ Abrir VIES ]]"
        return ""

    # -------------------------
    # UI interactions
    # -------------------------

    def _active_tree(self) -> ttk.Treeview:
        """Retorna el árbol visible (Pendientes o Validados)."""
        tab = self.notebook.index(self.notebook.select())
        return self.pending_tree if tab == 0 else self.validated_tree

    def on_tree_select(self, _event=None) -> None:
        tree = self._active_tree()
        sel = tree.selection()
        if sel and not self.processing:
            self.validate_selected_btn.state(["!disabled"])
        else:
            self.validate_selected_btn.state(["disabled"])

    def on_tree_motion(self, event) -> None:
        """Detecta si el cursor está sobre botón de acción."""
        tree = event.widget
        region = tree.identify_region(event.x, event.y)
        if region != "cell":
            tree.configure(cursor="")
            return
        col = tree.identify_column(event.x)
        row = tree.identify_row(event.y)
        if not row:
            tree.configure(cursor="")
            return
        # Last column is "Acción"
        if col == f"#{len(tree['columns'])}":
            vals = tree.item(row, "values")
            if vals and str(vals[-1]).strip():
                tree.configure(cursor="hand2")
                return
        tree.configure(cursor="")

    def on_tree_click(self, event) -> None:
        """Maneja clics en la tabla."""
        tree = event.widget
        region = tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = tree.identify_column(event.x)
        row = tree.identify_row(event.y)
        if not row or not col:
            return
        # Click on "Acción" column?
        if tree == self.pending_tree and col == f"#{len(self.pending_tree['columns'])}":
            vals = tree.item(row, "values")
            if vals and str(vals[-1]).strip():
                self.open_vies_web()

    def on_tree_double_click(self, event) -> None:
        """Maneja doble click: abre VIES."""
        tree = event.widget
        row = tree.identify_row(event.y)
        if row:
            self.open_vies_web()

    def show_context_menu(self, event) -> None:
        """Muestra menú contextual."""
        try:
            tree = event.widget
            item = tree.identify_row(event.y)
            if item:
                tree.selection_set(item)
                self.tree_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.tree_context_menu.grab_release()

    def open_vies_web(self) -> None:
        """Abre sitio web VIES y copia número VAT."""
        key = self._get_selected_key()
        if not key:
            messagebox.showinfo("Info", "Selecciona un VAT.")
            return
        info = self.vat_data.get(key)
        if info:
            num_only = get_vat_number_only(info.vat_clean)
            self.root.clipboard_clear()
            self.root.clipboard_append(num_only)
            webbrowser.open(self.VIES_WEB)
            self.set_status(f"Número {num_only} copiado al portapapeles, abriendo VIES...", 3000)

    def copy_vat(self, number_only: bool = False) -> None:
        """Copia número VAT al portapapeles."""
        key = self._get_selected_key()
        if not key:
            messagebox.showinfo("Info", "Selecciona un VAT.")
            return
        info = self.vat_data.get(key)
        if info:
            text = get_vat_number_only(info.vat_clean) if number_only else info.vat_clean
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.set_status(f"'{text}' copiado al portapapeles", 2000)

    # -------------------------
    # Refresh trees
    # -------------------------

    def refresh_trees(self) -> None:
        """Actualiza ambas tablas (Pendientes y Validados)."""
        self._render_pending_tree()
        self._render_validated_tree()

    def _render_pending_tree(self) -> None:
        """Renderiza tabla de VATs pendientes."""
        tree = self.pending_tree
        tree.delete(*tree.get_children())
        self.pending_tree_iids.clear()

        q = self.search_pending_var.get().strip().lower()

        for idx, (key, info) in enumerate(self.vat_data.items()):
            if info.status in self.VALIDATED_STATES:
                continue
            if q:
                hay = f"{info.vat_clean} {info.nombre_excel}".lower()
                if q not in hay:
                    continue

            attempts = info.attempts_hard + info.throttles
            last_checked = info.last_checked_at
            retry = ""
            if info.next_retry_at:
                retry = info.next_retry_at.strftime("%H:%M:%S")

            values = (
                info.vat_clean,
                info.country,
                info.number,
                info.nombre_excel,
                status_label(info.status),
                attempts,
                last_checked,
                retry,
                info.last_error,
                self.accion_text(info.status),
            )
            iid = str(key)
            row_tag = "row_even" if idx % 2 == 0 else "row_odd"
            tree.insert("", "end", iid=iid, values=values, tags=(row_tag, status_code(info.status)))
            self.pending_tree_iids[key] = iid

    def _render_validated_tree(self) -> None:
        """Renderiza tabla de VATs validados."""
        tree = self.validated_tree
        tree.delete(*tree.get_children())
        self.validated_tree_iids.clear()

        q = self.search_validated_var.get().strip().lower()

        for idx, (key, info) in enumerate(self.vat_data.items()):
            if info.status not in self.VALIDATED_STATES:
                continue
            if q:
                hay = f"{info.vat_clean} {info.nombre_excel} {info.vies_name}".lower()
                if q not in hay:
                    continue

            last_checked = info.last_checked_at
            values = (
                info.vat_clean,
                info.country,
                info.number,
                info.nombre_excel or info.vies_name,
                status_label(info.status),
                last_checked,
            )
            iid = str(key)
            row_tag = "row_even" if idx % 2 == 0 else "row_odd"
            tree.insert("", "end", iid=iid, values=values, tags=(row_tag, status_code(info.status)))
            self.validated_tree_iids[key] = iid

    def _get_selected_key(self) -> Optional[CountryNumber]:
        """Obtiene clave del VAT seleccionado en la tabla activa."""
        tree = self._active_tree()
        sel = tree.selection()
        if not sel:
            return None
        iid = sel[0]
        try:
            vals = tree.item(iid, "values")
            if not vals:
                return None
            country = vals[1]
            number = vals[2]
            return (country, number)
        except Exception:
            return None

    # -------------------------
    # Excel load / export
    # -------------------------

    def load_excel(self) -> None:
        """Carga archivo Excel con datos VAT."""
        if self.processing:
            messagebox.showinfo("Info", "Hay una validación en curso.")
            return

        file_path = filedialog.askopenfilename(
            title="Seleccionar archivo Excel",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")],
        )
        if not file_path:
            return

        self.selected_file = Path(file_path)
        self.vat_data.clear()

        self.retry_btn.state(["disabled"])
        self.export_menu_btn.state(["disabled"])
        self.validate_selected_btn.state(["disabled"])

        try:
            self.vat_data = load_excel(self.selected_file)
            self.refresh_trees()

            self.log_ok(f"Cargados {len(self.vat_data)} VATs únicos desde {self.selected_file.name}")
            self.set_status(f"Excel cargado: {len(self.vat_data)} VATs. Pulsa 'Validar' para comenzar.", 3500)

            self.validate_btn.state(["!disabled"])
            self.export_menu_btn.state(["!disabled"])

        except Exception as e:
            self.log_error(f"Error al cargar Excel: {e}")
            messagebox.showerror("Error", f"No se pudo cargar el archivo: {e}")

    def export_to_excel(self, scope: str = "all") -> None:
        """Exporta resultados a archivo Excel."""
        if not self.vat_data:
            messagebox.showinfo("Info", "No hay datos para exportar")
            return

        if scope not in {"all", "pending", "validated"}:
            scope = "all"

        initial_name = "vat_results.xlsx"
        if self.selected_file:
            suffix = {"all": "validated", "pending": "pending", "validated": "validated"}[scope]
            initial_name = f"{self.selected_file.stem}_{suffix}.xlsx"

        out = filedialog.asksaveasfilename(
            title="Guardar resultados",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("All", "*.*")],
            initialfile=initial_name,
        )
        if not out:
            return

        try:
            save_excel(Path(out), self.vat_data, scope=scope)
            self.log_ok(f"Exportado: {Path(out).name}")
            self.set_status(f"Exportado: {Path(out).name}", 3500)
            messagebox.showinfo("Éxito", f"Resultados exportados a:\n{out}")
        except Exception as e:
            self.log_error(f"Error al exportar: {e}")
            messagebox.showerror("Error", f"No se pudo exportar: {e}")

    # -------------------------
    # Validation flow
    # -------------------------

    def start_validation(self) -> None:
        """Inicia validación de todos los VATs nuevos."""
        if self.processing:
            return

        to_validate = [(k, v) for k, v in self.vat_data.items() if v.status == VatStatus.NEW and v.country and v.number]
        if not to_validate:
            return

        self.processing = True
        self._stop_event.clear()
        self.load_btn.state(["disabled"])
        self.validate_btn.state(["disabled"])
        self.retry_btn.state(["disabled"])
        self.validate_selected_btn.state(["disabled"])
        
        # Resetear barra de progreso
        self.progress_var.set(0)

        self.log_info("============================================================")
        self.log_info(f"Iniciando validación de {len(to_validate)} VATs...")

        t = threading.Thread(target=self._validate_batch_worker, args=(to_validate,), daemon=True)
        self._worker_threads = [t]
        t.start()

    def retry_pending(self) -> None:
        """Reintenta VATs pendientes listos para reintento."""
        if self.processing:
            return

        now = datetime.now()
        to_retry = []
        next_retry_time = None

        for k, v in self.vat_data.items():
            if v.is_retryable():
                if v.next_retry_at is None or v.next_retry_at <= now:
                    to_retry.append((k, v))
                elif next_retry_time is None or v.next_retry_at < next_retry_time:
                    next_retry_time = v.next_retry_at

        if not to_retry:
            if next_retry_time:
                wait_secs = int((next_retry_time - now).total_seconds())
                msg = f"Aún no se puede reintentar. Próximo reintento recomendado en {wait_secs}s."
                messagebox.showinfo("Reintentar", msg)
            else:
                messagebox.showinfo("Info", "No hay VATs pendientes listos para reintentar.")
            return

        self.processing = True
        self._stop_event.clear()
        self.load_btn.state(["disabled"])
        self.retry_btn.state(["disabled"])
        self.validate_selected_btn.state(["disabled"])

        self.log_info("============================================================")
        self.log_info(f"Reintentando {len(to_retry)} VATs pendientes...")
        self.progress_var.set(0)

        t = threading.Thread(target=self._validate_batch_worker, args=(to_retry,), daemon=True)
        self._worker_threads = [t]
        t.start()

    def validate_selected(self) -> None:
        """Valida un VAT seleccionado."""
        if self.processing:
            return
        key = self._get_selected_key()
        if not key:
            messagebox.showinfo("Info", "Selecciona un VAT.")
            return

        info = self.vat_data.get(key)
        if not info or not info.country or not info.number:
            return

        self.processing = True
        self._stop_event.clear()
        self.load_btn.state(["disabled"])
        self.validate_btn.state(["disabled"])
        self.retry_btn.state(["disabled"])
        self.validate_selected_btn.state(["disabled"])

        self.log_info(f"Validando seleccionado: {info.vat_clean}")
        self.progress_var.set(0)

        t = threading.Thread(target=self._validate_batch_worker, args=([(key, info)],), daemon=True)
        self._worker_threads = [t]
        t.start()

    def _validate_batch_worker(self, items: List[Tuple[CountryNumber, VatInfo]]) -> None:
        """Worker que valida un lote de VATs usando el planificador."""
        callbacks = UIThreadCallbacks(self)
        scheduler = RetryScheduler(self.vat_data, callbacks, self._stop_event)
        scheduler.validate_batch(items)

    def _on_vat_updated_main_thread(self, key: CountryNumber, info: VatInfo, result: dict) -> None:
        """Callback principal: VAT actualizado."""
        self._apply_result(info, result)
        if info.status in self.VALIDATED_STATES:
            self._cache[key] = info

    def _on_progress_main_thread(self, done: int, total: int) -> None:
        """Callback: Actualizar progreso."""
        self.set_status(f"Validando… {done}/{total}", 0)
        # Actualizar barra de progreso
        if total > 0:
            progress = (done / total) * 100
            self.progress_var.set(progress)

    def _on_banner_update_main_thread(self, text: str, next_retry_seconds: Optional[int] = None) -> None:
        """Callback: Actualizar banner."""
        if text:
            self.banner_label.config(text=text)
            self.banner_frame.grid()
        else:
            self._update_banner()

    def _on_batch_finished_main_thread(self, summary: BatchSummary) -> None:
        """Callback: Validación completada."""
        self._finish_validation(summary)

    def _apply_result(self, info: VatInfo, result: dict) -> None:
        """Aplica resultado de validación a VatInfo (solo campos presentacionales).
        
        RESPONSABILIDAD ÚNICA: Renderizar estado ya decidido por el core.
        
        La UI NO modifica:
        - info.status (ya actualizado por retry_logic.py)
        - info.throttles, info.attempts_hard (ya actualizado por retry_logic.py)
        - info.next_retry_at (ya calculado por RetryPolicy)
        - info.last_error (ya actualizado por retry_logic.py)
        
        La UI SÍ actualiza (solo campos presentacionales):
        - info.last_checked_at (timestamp de UI)
        - info.vies_name, info.vies_address (datos de respuesta VIES)
        
        Y realiza acciones de UI:
        - Escribir logs según info.status
        - Refrescar tablas
        - Habilitar/deshabilitar botones
        """
        # Campos presentacionales de UI (timestamp local)
        now = datetime.now()
        info.last_checked_at = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # Estado de negocio ya fue actualizado por core, solo lo leemos
        status = info.status
        prev_status_for_undo = result.get("_prev_status")  # Si core lo provee
        
        # Actualizar campos de respuesta VIES (solo para VALID)
        if status == VatStatus.VALID:
            info.vies_name = result.get("vies_name", "")
            info.vies_address = result.get("vies_address", "")
            self.log_ok(f"{info.vat_clean} → VALID")
            # Undo stack (solo si cambió a validado desde pendiente)
            if prev_status_for_undo and prev_status_for_undo not in self.VALIDATED_STATES:
                self.undo_stack.append(((info.country, info.number), prev_status_for_undo))
                self.root.after(0, lambda: self.undo_btn.state(["!disabled"]))

        elif status == VatStatus.INVALID:
            info.vies_name = ""
            info.vies_address = ""
            self.log_warn(f"{info.vat_clean} → INVALID")
            # Undo stack
            if prev_status_for_undo and prev_status_for_undo not in self.VALIDATED_STATES:
                self.undo_stack.append(((info.country, info.number), prev_status_for_undo))
                self.root.after(0, lambda: self.undo_btn.state(["!disabled"]))

        elif status == VatStatus.THROTTLED:
            # Solo logging (throttles ya fue incrementado por core)
            throttles = info.throttles
            if info.next_retry_at:
                retry_time = info.next_retry_at.strftime('%H:%M:%S')
                self.log_warn(f"{info.vat_clean} → THROTTLED ({throttles}) | retry {retry_time}")
            else:
                self.log_warn(f"{info.vat_clean} → THROTTLED ({throttles}) | no auto-retry")

        elif status == VatStatus.TIMEOUT or status == VatStatus.ERROR:
            # Solo logging (attempts_hard ya fue incrementado por core)
            attempts = info.attempts_hard
            retry_info = ""
            if info.next_retry_at:
                retry_info = f" | retry {info.next_retry_at.strftime('%H:%M:%S')}"
            self.log_warn(f"{info.vat_clean} → {status_code(status)} ({attempts} intentos){retry_info}")

        elif status == VatStatus.PENDING_MAX:
            # Estado terminal (ya asignado por RetryPolicy)
            self.log_error(f"{info.vat_clean} → NO VERIFICABLE (límite alcanzado)")

        elif status == VatStatus.INVALID_FORMAT:
            self.log_error(f"{info.vat_clean} → FORMATO INVÁLIDO")

        else:
            # Estado desconocido
            self.log_error(f"{info.vat_clean} → {status_code(status)}")

        # Refrescar UI (siempre)
        self.root.after(0, self.refresh_trees)

    def _finish_validation(self, summary: Optional[BatchSummary] = None) -> None:
        """Finaliza validación y actualiza UI."""
        self.processing = False
        self.load_btn.state(["!disabled"])
        self.validate_btn.state(["!disabled"])
        self.retry_btn.state(["!disabled"])

        self.refresh_trees()
        self._update_banner()

        if summary is not None:
            pending = summary.pending
            valid = summary.valid
            invalid = summary.invalid
        else:
            pending = sum(1 for v in self.vat_data.values() if v.status not in self.VALIDATED_STATES)
            valid = sum(1 for v in self.vat_data.values() if v.status == VatStatus.VALID)
            invalid = sum(1 for v in self.vat_data.values() if v.status == VatStatus.INVALID)
        
        self.log_info(f"✓ Validación completada: {valid} válidos, {invalid} inválidos, {pending} pendientes")
        
        if pending > 0:
            status_msg = (
                f"Validación completada: {valid} válidos, {invalid} inválidos, {pending} pendientes. "
                f"Puedes pulsar 'Reintentar' o 'Validar seleccionado'."
            )
            self.set_status(status_msg, 7000)
        else:
            status_msg = f"Validación completada: {valid} válidos, {invalid} inválidos"
            self.set_status(status_msg, 4500)

    def _update_banner(self) -> None:
        """Actualiza banner de VATs pendientes."""
        pending = sum(1 for v in self.vat_data.values() if v.status not in self.VALIDATED_STATES)
        valid = sum(1 for v in self.vat_data.values() if v.status == VatStatus.VALID)
        invalid = sum(1 for v in self.vat_data.values() if v.status == VatStatus.INVALID)
        
        if pending == 0 and (valid > 0 or invalid > 0):
            banner_text = f"✓ Validación terminada: {valid} válidos, {invalid} inválidos"
            self.banner_label.config(text=banner_text)
            self.banner_frame.grid()
            self.root.after(10000, lambda: self.banner_frame.grid_remove())
            return
        
        if pending == 0:
            self.banner_frame.grid_remove()
            return
        
        now = datetime.now()
        next_retry_time = None
        for v in self.vat_data.values():
            if v.status not in self.VALIDATED_STATES and v.next_retry_at:
                if next_retry_time is None or v.next_retry_at < next_retry_time:
                    next_retry_time = v.next_retry_at
        
        if next_retry_time and next_retry_time > now:
            wait_secs = int((next_retry_time - now).total_seconds())
            banner_text = f"{valid} válidos, {invalid} inválidos, {pending} pendientes (próximo reintento en {wait_secs}s)"
        else:
            banner_text = f"{valid} válidos, {invalid} inválidos, {pending} pendientes"
        
        self.banner_label.config(text=banner_text)
        self.banner_frame.grid()

    def _go_to_pending_tab(self) -> None:
        """Cambia a la pestaña Pendientes."""
        self.notebook.select(0)

    def undo_last_validated(self) -> None:
        """Deshace el último movimiento de Pendientes a Validados."""
        if not self.undo_stack:
            messagebox.showinfo("Info", "Nada que deshacer.")
            return
        
        if self.processing:
            messagebox.showinfo("Info", "No puedes deshacer mientras hay una validación en curso.")
            return
        
        key, prev_status = self.undo_stack.pop()
        info = self.vat_data.get(key)
        
        if not info:
            return
        
        info.status = VatStatus.NEW
        info.last_error = ""
        info.next_retry_at = None
        info.attempts_hard = 0
        info.throttles = 0
        info.last_checked_at = ""
        info.vies_name = ""
        info.vies_address = ""
        info.first_attempt_at = None
        info.auto_retry_count = 0
        
        self.refresh_trees()
        self._update_banner()
        
        if not self.undo_stack:
            self.undo_btn.state(["disabled"])
        
        self.set_status(f"Desecho: {info.vat_clean} (ahora pendiente para validar de nuevo)", 2500)
        self.log_info(f"Desecho: {info.vat_clean} → resetado a Pendiente para revalidar")

    # -------------------------
    # Exit
    # -------------------------

    def exit_app(self) -> None:
        self.on_closing()

    def on_closing(self) -> None:
        msg = "¿Seguro que quieres salir?"
        if self.processing:
            msg = "Hay una validación en curso. ¿Seguro que quieres salir?"
        if messagebox.askyesno("Salir", msg):
            self._stop_event.set()
            self.root.destroy()
