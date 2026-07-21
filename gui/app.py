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
import queue
import tkinter.messagebox as messagebox

import customtkinter as ctk

from core.gui_logging import MSG_FINISHED, MSG_LOG, MSG_PAUSED
from core.params import ScraperParams
from core.process_lifecycle import shutdown_worker_process
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
        self.geometry("900x500")
        self.minsize(900, 500)

        self.grid_columnconfigure(0, weight=0, minsize=340)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Comunicación con el proceso hijo ---
        self._message_queue: "multiprocessing.Queue" = multiprocessing.Queue()
        self._resume_event = multiprocessing.Event()
        self._worker_process: "multiprocessing.Process | None" = None
        self._awaiting_result = False  # True mientras hay un proceso corriendo
        # y todavía no hemos recibido su mensaje MSG_FINISHED.

        # --- Paneles ---
        self.input_frame = InputFrame(
            self,
            on_start=self._handle_start_clicked,
            on_proceed=self._handle_proceed_clicked,
            on_stop=self._handle_stop_clicked,
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
        labels = {
            "bank_statement_path": "Extracto bancario",
            "output_dir": "Carpeta de salida",
            "card_last_digits": "Últimos 4 dígitos de la tarjeta",
        }

        missing = [
            labels[k]
            for k in ("bank_statement_path", "output_dir", "card_last_digits")
            if not values[k]
        ]

        if missing:
            messagebox.showwarning(
                "Faltan datos",
                f"Completa los siguientes campos:\n\n• " + "\n• ".join(missing),
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
        self._awaiting_result = True

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
        self._awaiting_result = True

    def _handle_stop_clicked(self) -> None:
        if self._worker_process is None or not self._worker_process.is_alive():
            self.input_frame.set_idle_state("No hay un proceso en ejecución.")
            return

        self.input_frame.set_idle_state("Deteniendo proceso...")
        shutdown_worker_process(self._worker_process)
        self._worker_process = None
        self._awaiting_result = False
        messagebox.showinfo("Proceso detenido", "El scraping se detuvo correctamente.")

    def _handle_close(self) -> None:
        shutdown_worker_process(self._worker_process)
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
                    self._awaiting_result = False
                    self.input_frame.set_idle_state(
                        "Proceso finalizado." if success else "Proceso con errores."
                    )
                    if success:
                        messagebox.showinfo("Proceso finalizado", message)
                    else:
                        messagebox.showerror("Error en el proceso", message)

        except queue.Empty:
            pass
        except Exception as e:
            # Un error real al pintar un log (ej. un carácter que rompe el
            # Textbox) NO debe tragarse en silencio: lo mandamos a stderr
            # para poder diagnosticarlo, pero seguimos vivos.
            print(f"[GUI] Error inesperado procesando la cola de mensajes: {e}")

        # --- Vigilante: ¿el proceso hijo murió sin avisar? ---
        # Si estábamos esperando su resultado y el proceso ya no está vivo,
        # pero nunca llegó un mensaje MSG_FINISHED, es que se cayó de forma
        # anómala (crash nativo de Playwright/PyMuPDF, el navegador se
        # cerró, lo mató el antivirus, etc.). Sin este chequeo, la interfaz
        # se queda "congelada" para siempre: el botón sigue en "Ejecutando..."
        # y no hay ningún mensaje de error.
        if (
            self._awaiting_result
            and self._worker_process is not None
            and not self._worker_process.is_alive()
        ):
            self._awaiting_result = False
            exit_code = self._worker_process.exitcode
            self.input_frame.set_idle_state("El proceso se interrumpió inesperadamente.")
            messagebox.showerror(
                "Proceso interrumpido",
                "El proceso de scraping se cerró de forma inesperada "
                f"(código de salida: {exit_code}), sin reportar un error "
                "específico.\n\nEsto suele deberse a un cierre abrupto del "
                "navegador o un crash nativo al procesar un PDF puntual. "
                "Revisa logs/cronos_scraper.log para ver en qué punto exacto "
                "se detuvo.",
            )

        self.after(POLL_INTERVAL_MS, self._poll_queue)
