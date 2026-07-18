"""
Logger setup module.
Configura un logger reutilizable en todo el proyecto,
con salida a consola y a archivo rotativo.
"""

import logging
from logging.handlers import RotatingFileHandler

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

    logger.setLevel(Config.LOG_LEVEL)

    # Formato común para ambos handlers
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Handler de consola ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(Config.LOG_LEVEL)
    console_handler.setFormatter(formatter)

    # --- Handler de archivo (con rotación para no crecer indefinidamente) ---
    file_handler = RotatingFileHandler(
        filename=Config.LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5 MB por archivo
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(Config.LOG_LEVEL)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
