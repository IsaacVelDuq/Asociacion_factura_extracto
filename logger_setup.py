"""
Logger setup module.
Configura un logger reutilizable en todo el proyecto,
con salida a consola y a archivo rotativo.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
import sys
from datetime import datetime
from pathlib import Path

from config import Config


def get_logger(name: str) -> logging.Logger:
    """
    Crea (o recupera) un logger configurado con el nombre indicado.

    Args:
        name: nombre del logger, normalmente __name__ del módulo que lo llama.

    Returns:
        Instancia de logging.Logger lista para usar.
    """
    logger = logging.getLogger(name)

    # Evita agregar handlers duplicados si el logger ya fue configurado
    if logger.handlers:
        return logger

    # Evita que los loggers del proceso hijo reimpriman en la consola del
    # proceso padre cuando ya se están usando handlers de cola/GUI.
    logger.propagate = True

    logger.setLevel(Config.LOG_LEVEL)

    # Formato común para ambos handlers
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Handler de consola ---
    if os.getenv("DISABLE_CONSOLE_LOGGING", "").lower() not in {"1", "true", "yes", "on"}:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(Config.LOG_LEVEL)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # --- Handler de archivo (un archivo por ejecución) ---
    # Determinar ubicación: si la app está congelada (PyInstaller), crear el log
    # junto al ejecutable; en modo desarrollo usar el directorio de logs del proyecto.
    try:
        if getattr(sys, "frozen", False):
            # Cuando PyInstaller crea un ejecutable (onefile u onedir),
            # `sys.argv[0]` apunta al ejecutable real. Usamos su carpeta
            # para colocar los logs al lado del .exe (funciona para --onefile).
            base_dir = Path(sys.argv[0]).resolve().parent
        else:
            base_dir = Path(Config.LOG_FILE).parent
    except Exception:
        base_dir = Path(Config.LOG_FILE).parent

    # Asegurar que exista el directorio
    base_dir.mkdir(parents=True, exist_ok=True)

    # Crear un único archivo por ejecución y compartir su ruta vía
    # la variable de entorno `CRONOS_RUN_LOG` para que procesos
    # hijos apunten al mismo archivo.
    # Nota: RotatingFileHandler no es completamente seguro en
    # escenarios multiproceso — para robustez use QueueHandler/QueueListener.
    run_log_env = os.getenv("CRONOS_RUN_LOG")
    if run_log_env:
        log_path = Path(run_log_env)
    else:
        # elegir directorio para el log
        log_dir = base_dir if getattr(sys, "frozen", False) else Path(Config.LOG_FILE).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"cronos_scraper-{timestamp}.log"
        log_path = log_dir / log_filename
        # exponer la ruta para que procesos hijas la reutilicen
        os.environ["CRONOS_RUN_LOG"] = str(log_path)

    file_handler = RotatingFileHandler(
        filename=str(log_path),
        maxBytes=5 * 1024 * 1024,  # 5 MB por archivo
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(Config.LOG_LEVEL)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
