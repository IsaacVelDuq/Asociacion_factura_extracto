"""
Configuration module.
Centraliza todas las variables de configuración del proyecto.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import tempfile
from dotenv import load_dotenv

# Carga las variables de entorno desde el archivo .env
load_dotenv()

# Directorio raíz del proyecto
BASE_DIR = Path(__file__).resolve().parent

# Determinar base dir: junto al ejecutable si estamos congelados, sino la raíz del repo
if getattr(sys, "frozen", False):
    BASE_RUNTIME_DIR = Path(sys.argv[0]).resolve().parent
else:
    BASE_RUNTIME_DIR = BASE_DIR

# Directorio donde se guardarán los logs (junto al exe cuando esté frozen)
LOGS_DIR = BASE_RUNTIME_DIR / "logs"
try:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
except PermissionError:
    # Fallback a %LOCALAPPDATA% en Windows o al temp dir
    fallback_base = Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir())
    LOGS_DIR = fallback_base / "Asociacion_logs"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Crear un archivo de log único por ejecución y exponer su ruta en
# `CRONOS_RUN_LOG` para que procesos hijos la reutilicen.
_run_log_env = os.getenv("CRONOS_RUN_LOG")
if _run_log_env:
    RUN_LOG_PATH = Path(_run_log_env)
else:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    RUN_LOG_PATH = LOGS_DIR / f"cronos_scraper-{ts}.log"
    os.environ["CRONOS_RUN_LOG"] = str(RUN_LOG_PATH)

# Directorio donde se guardarán screenshots de error (debugging)
# (usar la misma base runtime para que queden junto al exe cuando esté frozen)
SCREENSHOTS_DIR = BASE_RUNTIME_DIR / "screenshots"
try:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
except PermissionError:
    fallback_base = Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir())
    SCREENSHOTS_DIR = fallback_base / "Asociacion_screenshots"
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Crear un directorio único por ejecución para screenshots y exponerlo
# vía la variable de entorno `CRONOS_RUN_SCREENSHOTS` para que procesos
# hijos reutilicen la misma ruta.
_run_screenshots_env = os.getenv("CRONOS_RUN_SCREENSHOTS")
if _run_screenshots_env:
    RUN_SCREENSHOTS_DIR = Path(_run_screenshots_env)
else:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    RUN_SCREENSHOTS_DIR = SCREENSHOTS_DIR / ts
    RUN_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["CRONOS_RUN_SCREENSHOTS"] = str(RUN_SCREENSHOTS_DIR)


class Config:
    """Clase que agrupa toda la configuración de la aplicación."""

    # --- Credenciales y URL de Cronos ---
    CRONOS_URL: str = os.getenv("CRONOS_URL", "")
    CRONOS_USERNAME: str = os.getenv("CRONOS_USERNAME", "")
    CRONOS_PASSWORD: str = os.getenv("CRONOS_PASSWORD", "")

    # --- Configuración del navegador (Playwright) ---
    HEADLESS: bool = os.getenv("HEADLESS", "true").lower() == "true"
    BROWSER_TYPE: str = os.getenv("BROWSER_TYPE", "chromium")  # chromium, firefox, webkit
    DEFAULT_TIMEOUT: int = int(os.getenv("DEFAULT_TIMEOUT", "30000"))  # milisegundos
    SLOW_MO: int = int(os.getenv("SLOW_MO", "0"))  # milisegundos, útil para debug

    # --- Configuración de logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: Path = RUN_LOG_PATH

    @classmethod
    def validate(cls) -> None:
        """
        Valida que las variables críticas estén configuradas.
        Lanza un error claro si falta alguna credencial.
        """
        missing = []
        if not cls.CRONOS_URL:
            missing.append("CRONOS_URL")
        if not cls.CRONOS_USERNAME:
            missing.append("CRONOS_USERNAME")
        if not cls.CRONOS_PASSWORD:
            missing.append("CRONOS_PASSWORD")

        if missing:
            raise EnvironmentError(
                f"Faltan variables de entorno requeridas: {', '.join(missing)}. "
                f"Revisa tu archivo .env"
            )
