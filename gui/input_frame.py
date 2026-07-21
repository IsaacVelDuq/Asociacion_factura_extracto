"""
Input frame.
Panel izquierdo de la interfaz: todos los campos que el usuario debe
diligenciar antes de iniciar el proceso, más los botones "Iniciar" y
"Proceder".
"""

from tkinter import filedialog
from typing import Callable

import customtkinter as ctk


class InputFrame(ctk.CTkFrame):
    """Formulario de parámetros de entrada + controles de ejecución."""

    def __init__(
        self,
        master,
        on_start: Callable[[], None],
        on_proceed: Callable[[], None],
        on_stop: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, corner_radius=12, **kwargs)

        self._on_start = on_start
        self._on_proceed = on_proceed
        self._on_stop = on_stop

        self.grid_columnconfigure(0, weight=1)

        row = 0

        title = ctk.CTkLabel(
            self,
            text="GCO · Tesorería",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        title.grid(row=row, column=0, sticky="w", padx=16, pady=(16, 0))
        row += 1

        subtitle = ctk.CTkLabel(
            self,
            text="Conciliación de extracto vs. facturas Cronos",
            font=ctk.CTkFont(size=12),
            text_color="#9aa0ac",
        )
        subtitle.grid(row=row, column=0, sticky="w", padx=16, pady=(0, 16))
        row += 1

        row = self._add_file_field(
            row,
            label="Extracto bancario (PDF)",
            var_name="bank_statement_path",
            browse_command=self._browse_pdf,
        )
        row = self._add_dir_field(
            row,
            label="Carpeta de salida",
            var_name="output_dir",
            browse_command=self._browse_output_dir,
        )
        row = self._add_text_field(row, "Últimos 4 dígitos tarjeta", "card_last_digits")

        note = ctk.CTkLabel(
            self,
            text=(
                "Se buscarán los casos que tengan como proceedor (Éxito/Aviatur) "
                "y que coincidan con los últimos 4 dígitos de la tarjeta."
            ),
            font=ctk.CTkFont(size=11),
            text_color="#7f849c",
            wraplength=280,
            justify="left",
        )
        note.grid(row=row, column=0, sticky="w", padx=16, pady=(4, 8))
        row += 1

        self.start_button = ctk.CTkButton(
            self, text="Iniciar proceso", command=self._handle_start
        )
        self.start_button.grid(row=row, column=0, sticky="ew", padx=16, pady=(8, 4))
        row += 1

        self.proceed_button = ctk.CTkButton(
            self,
            text="Proceder (ya inicié sesión)",
            command=self._handle_proceed,
            fg_color="#f9c74f",
            hover_color="#e0ac2b",
            text_color="#1e1e1e",
            state="disabled",
        )
        self.proceed_button.grid(row=row, column=0, sticky="ew", padx=16, pady=4)
        row += 1

        self.stop_button = ctk.CTkButton(
            self,
            text="Detener proceso",
            command=self._handle_stop,
            fg_color="#ef4444",
            hover_color="#dc2626",
            state="disabled",
        )
        self.stop_button.grid(row=row, column=0, sticky="ew", padx=16, pady=4)
        row += 1

        self.status_label = ctk.CTkLabel(
            self, text="Listo para iniciar.", text_color="#9aa0ac", wraplength=280
        )
        self.status_label.grid(row=row, column=0, sticky="w", padx=16, pady=(12, 16))
        row += 1

        self.grid_rowconfigure(row, weight=1)

    # ------------------------------------------------------------------
    # Construcción de campos
    # ------------------------------------------------------------------
    def _add_text_field(self, row: int, label: str, var_name: str) -> int:
        ctk.CTkLabel(self, text=label, anchor="w").grid(
            row=row, column=0, sticky="w", padx=16, pady=(6, 0)
        )
        row += 1
        entry = ctk.CTkEntry(self)
        entry.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 4))
        setattr(self, f"{var_name}_entry", entry)
        return row + 1

    def _add_file_field(self, row: int, label: str, var_name: str, browse_command) -> int:
        ctk.CTkLabel(self, text=label, anchor="w").grid(
            row=row, column=0, sticky="w", padx=16, pady=(6, 0)
        )
        row += 1
        wrapper = ctk.CTkFrame(self, fg_color="transparent")
        wrapper.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 4))
        wrapper.grid_columnconfigure(0, weight=1)

        entry = ctk.CTkEntry(wrapper)
        entry.grid(row=0, column=0, sticky="ew")
        setattr(self, f"{var_name}_entry", entry)

        browse_btn = ctk.CTkButton(wrapper, text="...", width=32, command=browse_command)
        browse_btn.grid(row=0, column=1, padx=(6, 0))
        return row + 1

    def _add_dir_field(self, row: int, label: str, var_name: str, browse_command) -> int:
        return self._add_file_field(row, label, var_name, browse_command)

    # ------------------------------------------------------------------
    # Callbacks de selección de archivos
    # ------------------------------------------------------------------
    def _browse_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecciona el extracto bancario (PDF)",
            filetypes=[("Archivos PDF", "*.pdf")],
        )
        if path:
            self.bank_statement_path_entry.delete(0, "end")
            self.bank_statement_path_entry.insert(0, path)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Selecciona la carpeta de salida")
        if path:
            self.output_dir_entry.delete(0, "end")
            self.output_dir_entry.insert(0, path)

    # ------------------------------------------------------------------
    # Handlers de botones
    # ------------------------------------------------------------------
    def _handle_start(self) -> None:
        self._on_start()

    def _handle_proceed(self) -> None:
        self._on_proceed()

    def _handle_stop(self) -> None:
        self._on_stop()

    # ------------------------------------------------------------------
    # API pública usada por App
    # ------------------------------------------------------------------
    def get_values(self) -> dict:
        return {
            "bank_statement_path": self.bank_statement_path_entry.get().strip(),
            "output_dir": self.output_dir_entry.get().strip(),
            "card_last_digits": self.card_last_digits_entry.get().strip(),
        }

    def set_running_state(self) -> None:
        self.start_button.configure(state="disabled", text="Ejecutando...")
        self.proceed_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_label.configure(text="Proceso en ejecución...")

    def set_waiting_for_login_state(self) -> None:
        self.proceed_button.configure(state="normal")
        self.stop_button.configure(state="normal")
        self.status_label.configure(
            text="Inicia sesión manualmente en el navegador (captcha) "
            "y luego haz clic en 'Proceder'."
        )

    def set_resumed_state(self) -> None:
        self.proceed_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_label.configure(text="Reanudado. Procesando...")

    def set_idle_state(self, message: str = "Listo para iniciar.") -> None:
        self.start_button.configure(state="normal", text="Iniciar proceso")
        self.proceed_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.status_label.configure(text=message)
