"""
App.
Clase principal de la interfaz. Se encarga de:
  - Construir la ventana (InputFrame a la izquierda, ConsoleFrame a la
    derecha). Corre en el proceso principal, en su hilo principal — el
    lugar más confiable para Tkinter.
  - Lanzar un `multiprocessing.Process` con el flujo de scraping al hacer
    clic en "Iniciar". Al ser un PROCESO (no un hilo), tiene su propio
    GIL: por más pesado que sea Playwright/pandas, nunca compite por CPU
    con el hilo de la GUI, así que la ventana jamás se congela.
  - Vaciar `message_queue` periódicamente (`after`) para pintar logs y
    actualizar estados — el único punto donde se tocan widgets.

Comunicación con el proceso hijo:
  - `message_queue` (multiprocessing.Queue): hijo -> GUI (logs, pausa, fin)
  - `resume_event` (multiprocessing.Event): GUI -> hijo (botón "Proceder")
"""

import multiprocessing
import tkinter.messagebox as messagebox

import customtkinter as ctk

from core.gui_logging import MSG_FINISHED, MSG_LOG, MSG_PAUSED
from core.worker import ScraperParams
from core.worker_process import run_worker_process
from gui.console_frame import ConsoleFrame
from gui.input_frame import InputFrame

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

POLL_INTERVAL_MS = 100


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("GCO - Tesorería · Conciliación de tarjeta")
        self.geometry("1180x680")
        self.minsize(980, 600)

        self.grid_columnconfigure(0, weight=0, minsize=340)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Comunicación con el proceso hijo ---
        self._message_queue: "multiprocessing.Queue" = multiprocessing.Queue()
        self._resume_event = multiprocessing.Event()
        self._worker_process: "multiprocessing.Process | None" = None

        # --- Paneles ---
        self.input_frame = InputFrame(
            self,
            on_start=self._handle_start_clicked,
            on_proceed=self._handle_proceed_clicked,
        )
        self.input_frame.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)

        self.console_frame = ConsoleFrame(self)
        self.console_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)

        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self.after(POLL_INTERVAL_MS, self._poll_queue)

    # ------------------------------------------------------------------
    # Callbacks de botones
    # ------------------------------------------------------------------
    def _handle_start_clicked(self) -> None:
        if self._worker_process is not None and self._worker_process.is_alive():
            messagebox.showinfo("Proceso en curso", "Ya hay un proceso en ejecución.")
            return

        values = self.input_frame.get_values()

        missing = [
            k
            for k in ("bank_statement_path", "output_dir", "card_last_digits")
            if not values[k]
        ]
        if missing:
            messagebox.showwarning(
                "Faltan datos", f"Completa los siguientes campos: {', '.join(missing)}"
            )
            return

        params = ScraperParams(
            bank_statement_path=values["bank_statement_path"],
            output_dir=values["output_dir"],
            card_last_digits=values["card_last_digits"],
        )

        self._resume_event.clear()
        self.console_frame.clear()
        self.input_frame.set_running_state()

        # Se ejecuta en un PROCESO aparte (no un hilo): así el trabajo de
        # Playwright/pandas nunca compite por el GIL con la GUI.
        self._worker_process = multiprocessing.Process(
            target=run_worker_process,
            args=(params, self._message_queue, self._resume_event),
            daemon=True,
            name="ScraperWorkerProcess",
        )
        self._worker_process.start()

    def _handle_proceed_clicked(self) -> None:
        self.input_frame.set_resumed_state()
        self._resume_event.set()

    def _handle_close(self) -> None:
        if self._worker_process is not None and self._worker_process.is_alive():
            # Al ser un proceso real (no un hilo), sí se puede terminar de
            # forma forzosa sin dejar nada colgado.
            self._worker_process.terminate()
        self.destroy()

    # ------------------------------------------------------------------
    # Único punto que toca widgets: se ejecuta en el hilo de la GUI.
    # ------------------------------------------------------------------
    def _poll_queue(self) -> None:
        try:
            while True:
                item = self._message_queue.get_nowait()
                kind = item[0]

                if kind == MSG_LOG:
                    _, level_name, message = item
                    self.console_frame.write_log(level_name, message)

                elif kind == MSG_PAUSED:
                    self.input_frame.set_waiting_for_login_state()

                elif kind == MSG_FINISHED:
                    _, success, message = item
                    self.input_frame.set_idle_state(
                        "Proceso finalizado." if success else "Proceso con errores."
                    )
                    if success:
                        messagebox.showinfo("Proceso finalizado", message)
                    else:
                        messagebox.showerror("Error en el proceso", message)

        except Exception:
            # multiprocessing.Queue.get_nowait() lanza queue.Empty (que
            # hereda de Exception) cuando no hay mensajes pendientes.
            pass
        finally:
            self.after(POLL_INTERVAL_MS, self._poll_queue)
