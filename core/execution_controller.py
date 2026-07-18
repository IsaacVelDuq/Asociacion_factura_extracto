"""
Execution controller.
Sincroniza el hilo/proceso de ejecución (worker) con la interfaz.

Cuando el flujo llega al punto de login manual (captcha), el worker llama a
`pause_and_wait()`, lo que:
  1. Limpia el evento de reanudación.
  2. Notifica (vía callback) que se debe habilitar el botón "Proceder".
  3. Bloquea la ejecución hasta que la GUI llame a `resume()`.

Este objeto NO toca directamente ningún widget de Tkinter: solo expone un
callback que la capa de GUI define.

Acepta cualquier objeto tipo "Event" (con `.set()`, `.clear()`, `.wait()`):
tanto `threading.Event` como `multiprocessing.Event` cumplen esa interfaz,
lo que permite usar este mismo controlador sin importar si el worker corre
en un hilo o en un proceso separado.
"""

import threading
from typing import Callable, Optional


class ExecutionController:
    """Gestiona la pausa/reanudación de la ejecución del scraper."""

    def __init__(self, resume_event: Optional[object] = None) -> None:
        self._resume_event = resume_event if resume_event is not None else threading.Event()
        self._on_pause_callback: Optional[Callable[[], None]] = None

    def set_on_pause_callback(self, callback: Callable[[], None]) -> None:
        """Registra la función a invocar cuando el worker se pausa.

        La función registrada debe limitarse a encolar un mensaje (nunca
        tocar widgets directamente), porque puede ejecutarse en un hilo o
        proceso distinto al de Tkinter.
        """
        self._on_pause_callback = callback

    def pause_and_wait(self) -> None:
        """Pausa la ejecución actual hasta que se llame a `resume()`.

        Debe ejecutarse desde el worker, justo después de `scraper.login()`.
        """
        self._resume_event.clear()
        if self._on_pause_callback is not None:
            self._on_pause_callback()
        self._resume_event.wait()

    def resume(self) -> None:
        """Reanuda la ejecución que esté esperando en `pause_and_wait()`."""
        self._resume_event.set()

    def reset(self) -> None:
        """Reinicia el controlador para una nueva ejecución."""
        self._resume_event.clear()
