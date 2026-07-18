"""
Console frame.
Panel derecho de la interfaz: un Textbox de solo lectura que muestra los
logs con colores según su nivel (DEBUG/INFO/WARNING/ERROR/CRITICAL).

Solo el hilo de la GUI escribe en este widget (ver App._poll_queue), por
lo que no hay problemas de concurrencia con Tkinter.
"""

import customtkinter as ctk

from core.gui_logging import LEVEL_STYLES


class ConsoleFrame(ctk.CTkFrame):
    """Consola de solo lectura para mostrar logs coloreados."""

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, corner_radius=12, **kwargs)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        title = ctk.CTkLabel(
            self, text="Consola de ejecución", font=ctk.CTkFont(size=16, weight="bold")
        )
        title.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        self.textbox = ctk.CTkTextbox(
            self, wrap="word", state="disabled", font=ctk.CTkFont(family="Consolas", size=12)
        )
        self.textbox.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))

        # Acceso al widget tkinter.Text interno para poder usar tags de color.
        self._raw_text = self.textbox._textbox
        for level_name, style in LEVEL_STYLES.items():
            font_weight = "bold" if style.bold else "normal"
            self._raw_text.tag_config(
                level_name,
                foreground=style.color,
            )

    def write_log(self, level_name: str, message: str) -> None:
        """Inserta una línea de log con el color correspondiente al nivel."""
        self.textbox.configure(state="normal")
        tag = level_name if level_name in LEVEL_STYLES else "INFO"
        self._raw_text.insert("end", message + "\n", tag)
        self.textbox.configure(state="disabled")
        self.textbox.see("end")

    def clear(self) -> None:
        self.textbox.configure(state="normal")
        self._raw_text.delete("1.0", "end")
        self.textbox.configure(state="disabled")
