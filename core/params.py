"""
Scraper params.
Vive en su propio módulo, separado de `core/worker.py`, a propósito:
`gui/app.py` (que corre en el PROCESO DE LA GUI) necesita la clase
`ScraperParams`, pero NO debe arrastrar los imports pesados de
`core/worker.py` (Playwright, pandas, PyMuPDF, y — más importante — la
creación de un logger con su propio archivo abierto vía `get_logger()`).

Antes, `gui/app.py` importaba `ScraperParams` directamente desde
`core.worker`, lo que hacía que el proceso de la GUI también ejecutara
`logger = get_logger(__name__)` a nivel de módulo, abriendo su propio
`RotatingFileHandler` sobre el MISMO archivo (`logs/cronos_scraper.log`)
que usa el proceso hijo. Dos procesos con el mismo archivo de log abierto
para escritura es una fuente real de logs corruptos/entrelazados sin
sentido, especialmente si llegas a tener un proceso hijo "colgado" de una
corrida anterior mientras arrancas una nueva ventana.
"""

import os
from dataclasses import dataclass

CASE_EXITO = "900640173"
CASE_AVIATUR = "860000018"
CASE_NUMBERS = [CASE_EXITO, CASE_AVIATUR]

@dataclass
class ScraperParams:
    """Datos que el usuario ingresa en la interfaz.

    Debe ser picklable (solo tipos simples), porque se envía como
    argumento al crear el proceso hijo.
    """

    bank_statement_path: str
    output_dir: str
    card_last_digits: str

