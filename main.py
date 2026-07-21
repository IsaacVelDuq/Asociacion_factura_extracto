"""
Entry point de la interfaz gráfica.

ARQUITECTURA (importante, no cambiar sin razón):

  La GUI (CustomTkinter) corre en el proceso principal, en su hilo
  principal — el escenario más confiable para Tkinter en cualquier
  sistema operativo.

  El flujo de scraping (Playwright + pandas + Excel) corre en un PROCESO
  HIJO aparte (`multiprocessing.Process`, ver `core/worker_process.py`),
  no en un hilo. La razón: los hilos comparten el GIL de Python, así que
  un hilo con trabajo pesado (Playwright/pandas) puede terminar quitándole
  tiempo de CPU al hilo de la GUI, lo que hace que Windows marque la
  ventana como "no responde" aunque siga viva. Un proceso aparte tiene su
  propio GIL: sin importar qué tan pesado sea el trabajo del scraper, la
  ventana nunca se congela.

  La comunicación entre proceso principal (GUI) y proceso hijo (worker) es
  100% a través de primitivas de `multiprocessing`:
    - `multiprocessing.Queue`: hijo -> GUI (logs, pausa, fin de proceso)
    - `multiprocessing.Event`: GUI -> hijo (botón "Proceder")
  Nunca se toca un widget de Tkinter desde fuera de su propio hilo/proceso.

Requisitos:
    pip install customtkinter

Este archivo debe ejecutarse desde la raíz de tu proyecto (donde ya
existen config.py, exceptions.py, logger_setup.py, scrapers/, utils/),
de modo que los imports de core/worker.py se resuelvan correctamente.
"""

import multiprocessing

from gui.app import App


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    # Necesario en Windows/macOS para que multiprocessing funcione
    # correctamente si el proyecto llega a empaquetarse con PyInstaller.
    multiprocessing.freeze_support()
    main()
