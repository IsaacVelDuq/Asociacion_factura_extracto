"""Utilidades para manejar el ciclo de vida de procesos de scraping."""

import multiprocessing
from typing import Optional


def shutdown_worker_process(
    worker_process: Optional[multiprocessing.Process],
    timeout: float = 3.0,
) -> None:
    """Finaliza un proceso hijo de forma segura.

    Primero intenta un cierre ordenado con ``terminate()`` y espera unos
    segundos. Si el proceso sigue vivo, fuerza su salida con ``kill()``.
    """
    if worker_process is None:
        return

    if not worker_process.is_alive():
        return

    worker_process.terminate()
    worker_process.join(timeout=timeout)

    if worker_process.is_alive():
        worker_process.kill()
        worker_process.join(timeout=timeout)
