"""
GUI logging bridge.
Puente thread-safe entre el sistema de logging estándar de Python y la
interfaz CustomTkinter, usando una `queue.Queue` como canal de comunicación.

No se debe tocar ningún widget desde el hilo worker: este handler solo
serializa el registro y lo deposita en la cola. El hilo de la GUI es el
único que la vacía (vía `after`) y actualiza el Textbox.
"""

import logging
import queue
from dataclasses import dataclass


# Tipo de mensaje que viaja por la cola.
MSG_LOG = "LOG"
MSG_PAUSED = "PAUSED"
MSG_FINISHED = "FINISHED"


@dataclass(frozen=True)
class LevelStyle:
    color: str
    bold: bool = False


# Paleta pensada para un Textbox en modo oscuro.
LEVEL_STYLES = {
    "DEBUG": LevelStyle(color="#7f849c"),
    "INFO": LevelStyle(color="#a6e3a1"),
    "WARNING": LevelStyle(color="#f9c74f"),
    "ERROR": LevelStyle(color="#f38ba8"),
    "CRITICAL": LevelStyle(color="#ff5555", bold=True),
}


class QueueLogHandler(logging.Handler):
    """Handler de logging que envía cada registro formateado a una cola.

    Se engancha al logger raíz para capturar los registros de todos los
    loggers del proyecto (que por defecto propagan hacia arriba), sin
    necesidad de modificar `logger_setup.py`.
    """

    def __init__(self, log_queue: "queue.Queue") -> None:
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            self._queue.put((MSG_LOG, record.levelname, message))
        except Exception:
            self.handleError(record)


def attach_gui_handler(log_queue: "queue.Queue", level: int = logging.DEBUG) -> QueueLogHandler:
    """Crea y engancha el QueueLogHandler al logger raíz.

    Como los loggers creados con `get_logger()` tienen `propagate=True`
    (comportamiento por defecto), cada registro que pasa por ellos también
    llega al logger raíz y, por lo tanto, a este handler.
    """
    handler = QueueLogHandler(log_queue)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    if root_logger.level > level:
        root_logger.setLevel(level)
    return handler
