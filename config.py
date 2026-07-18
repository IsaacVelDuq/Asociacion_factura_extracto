"""
Configuration module.
Centraliza todas las variables de configuración del proyecto.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Carga las variables de entorno desde el archivo .env
load_dotenv()

# Directorio raíz del proyecto
BASE_DIR = Path(__file__).resolve().parent

# Directorio donde se guardarán los logs
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Directorio donde se guardarán screenshots de error (debugging)
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)


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
    LOG_FILE: Path = LOGS_DIR / "cronos_scraper.log"

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
