"""Punto de entrada principal para VIES VAT Validator.

Ejecuta la aplicación de escritorio con interfaz Tkinter.
"""

import tkinter as tk
import ttkbootstrap as ttk
from vat_validator.ui.interface import VATValidatorApp


def main() -> None:
    """Inicia la aplicación principal."""
    root = ttk.Window(themename="flatly")
    app = VATValidatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
