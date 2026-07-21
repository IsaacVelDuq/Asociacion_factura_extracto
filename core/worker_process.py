"""
Worker process entry point.

Función de nivel de módulo (requisito de `multiprocessing` en Windows,
que usa el método de arranque "spawn": el objetivo de un `Process` debe
poder importarse por su ruta, no puede ser un método de una instancia ni
una función anidada/lambda).

Se ejecuta COMPLETAMENTE en un proceso aparte al de la interfaz, con su
propio intérprete y su propio GIL. Esto es lo que garantiza que, sin
importar qué tan pesado sea el trabajo de Playwright o pandas, la ventana
de CustomTkinter (que vive en el proceso principal) nunca se congele por
contención del GIL.

Motivo del cambio (antes se usaba un hilo, no un proceso):
Aunque un hilo separado *en teoría* debería dejar libre al hilo de la GUI
gracias a que Python libera el GIL en operaciones de E/S, en la práctica
el trabajo intensivo de Playwright/pandas puede retener el GIL el tiempo
suficiente como para que Windows marque la ventana como "no responde".
Un proceso aparte elimina por completo esa competencia: cada proceso
tiene su propio GIL.
"""

import multiprocessing
import os

os.environ["DISABLE_CONSOLE_LOGGING"] = "1"

from core.execution_controller import ExecutionController
from core.gui_logging import MSG_FINISHED, MSG_PAUSED, attach_gui_handler
from core.worker import ScraperParams, execute_scraper_flow
from exceptions import ScraperBaseException
from logger_setup import get_logger


def run_worker_process(
    params: ScraperParams,
    message_queue: "multiprocessing.Queue",
    resume_event: "multiprocessing.synchronize.Event",
) -> None:
    """Se ejecuta dentro del proceso hijo. Punto de entrada único.

    - Engancha el logging de este proceso a `message_queue` (cada proceso
      tiene su propio logging.Logger; hay que engancharlo aquí, no en el
      proceso principal).
    - Construye un `ExecutionController` alrededor del `resume_event`
      compartido, para poder pausar en el login manual.
    - Ejecuta el flujo y reporta el resultado final por la misma cola.
    """
    attach_gui_handler(message_queue)
    logger = get_logger(__name__)

    execution_controller = ExecutionController(resume_event=resume_event)
    execution_controller.set_on_pause_callback(lambda: message_queue.put((MSG_PAUSED,)))

    try:
        execute_scraper_flow(params, execution_controller)
    except ScraperBaseException as e:
        logger.error("El proceso de scraping falló: %s", e)
        message_queue.put((MSG_FINISHED, False, str(e)))
        return
    except BaseException as e:
        # BaseException (no solo Exception) a propósito: así también se
        # reporta a la GUI ante KeyboardInterrupt/SystemExit u otras
        # señales que interrumpan el proceso, en vez de dejarlo morir en
        # silencio. Un crash nativo real (segfault en una librería C) sigue
        # sin poder capturarse aquí -- para eso existe el vigilante en
        # gui/app.py que detecta cuando el proceso muere sin este mensaje.
        logger.exception("Error inesperado durante el scraping: %s", e)
        message_queue.put((MSG_FINISHED, False, str(e)))
        return

    message_queue.put((MSG_FINISHED, True, "Proceso finalizado correctamente."))
