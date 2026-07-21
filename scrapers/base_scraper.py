"""
Base scraper module.
Define la clase base con toda la lógica común de Playwright
(inicio, cierre, navegación, utilidades) que las clases hijas
(como CronosScraper) van a heredar y extender.
"""

from datetime import datetime
from typing import Optional

from playwright.sync_api import (
    sync_playwright,
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from config import Config, SCREENSHOTS_DIR
from exceptions import NavigationError, ElementNotFoundError
from logger_setup import get_logger


class BaseScraper:
    """
    Clase base para scrapers construidos con Playwright.

    Maneja el ciclo de vida del navegador (abrir/cerrar) y expone
    métodos utilitarios comunes (navegar, click, fill, esperar elementos,
    tomar screenshots, etc.).
    """

    def __init__(
        self,
        headless: bool = Config.HEADLESS,
        browser_type: str = Config.BROWSER_TYPE,
        timeout: int = Config.DEFAULT_TIMEOUT,
        slow_mo: int = Config.SLOW_MO,
    ) -> None:

        self.headless = headless
        self.browser_type = browser_type
        self.timeout = timeout
        self.slow_mo = slow_mo

        self.logger = get_logger(self.__class__.__name__)

        self._playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inicia Playwright y abre el navegador."""

        self.logger.info(
            "Iniciando Playwright y lanzando navegador (%s)...",
            self.browser_type,
        )

        self._playwright = sync_playwright().start()
        browser_launcher = getattr(self._playwright, self.browser_type)

        self.browser = browser_launcher.launch(
            headless=self.headless,
            channel="chrome",
            slow_mo=self.slow_mo,
            args=["--start-maximized"],
        )

        self.context = self.browser.new_context(
            no_viewport=True,
        )

        self.page = self.context.new_page()
        self.page.set_default_timeout(self.timeout)

        self.logger.info("Navegador iniciado correctamente.")

    def stop(self) -> None:
        """Cierra el navegador y libera recursos."""

        self.logger.info("Cerrando navegador y liberando recursos...")

        if self.context:
            self.context.close()

        if self.browser:
            self.browser.close()

        if self._playwright:
            self._playwright.stop()

        self.logger.info("Recursos liberados correctamente.")

    def __enter__(self) -> "BaseScraper":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Navegación
    # ------------------------------------------------------------------

    def navigate(self, url: str) -> None:
        """Navega hacia la URL indicada."""

        try:
            self.logger.info("Navegando a: %s", url)
            self.page.goto(url)

        except PlaywrightTimeoutError as e:
            self._take_error_screenshot("navigate_timeout")
            raise NavigationError(
                f"No se pudo navegar a {url}"
            ) from e

    # ------------------------------------------------------------------
    # Interacción con Locators
    # ------------------------------------------------------------------

    def safe_fill(
        self,
        locator: Locator,
        value: str,
        field_name: str = "",
    ) -> None:
        """Llena un campo utilizando un Locator."""

        try:
            self.logger.debug(
                "Llenando campo '%s'",
                field_name or "sin nombre",
            )

            locator.fill(value)

        except PlaywrightTimeoutError as e:
            self._take_error_screenshot("fill_error")
            raise ElementNotFoundError(
                f"No fue posible llenar el campo '{field_name}'."
            ) from e

    def safe_click(
        self,
        locator: Locator,
        description: str = "",
    ) -> None:
        """Hace clic sobre un Locator."""

        try:
            self.logger.debug(
                "Haciendo click en '%s'",
                description or "elemento",
            )

            locator.click()

        except PlaywrightTimeoutError as e:
            self._take_error_screenshot("click_error")
            raise ElementNotFoundError(
                f"No fue posible hacer click en '{description}'."
            ) from e

    def wait_for(
        self,
        locator: Locator,
        timeout: Optional[int] = None,
    ) -> None:
        """Espera a que un Locator sea visible."""

        try:
            locator.wait_for(
                state="visible",
                timeout=timeout or self.timeout,
            )

        except PlaywrightTimeoutError as e:
            self._take_error_screenshot("wait_timeout")
            raise ElementNotFoundError(
                "El elemento no apareció dentro del tiempo esperado."
            ) from e

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------

    def _take_error_screenshot(self, tag: str) -> None:
        """Guarda un screenshot cuando ocurre un error."""

        if not self.page:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = SCREENSHOTS_DIR / f"{tag}_{timestamp}.png"

        try:
            self.page.screenshot(path=str(filepath))
            self.logger.info(
                "Screenshot de error guardado en: %s",
                filepath,
            )
        except Exception:
            self.logger.warning(
                "No se pudo guardar el screenshot de error."
            )