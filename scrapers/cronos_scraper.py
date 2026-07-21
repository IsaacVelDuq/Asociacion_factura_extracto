"""
Cronos scraper module.
Define la clase CronosScraper, encargada de:
  1. Login manual (Cronos usa captcha, así que el login lo hace la
     persona a mano; el código solo pausa la ejecución para eso).
  2. Iterar sobre una lista de fechas, consultando en cada una la
     bandeja de casos filtrando por número de caso + fecha.
  3. Por cada fecha consultada, iterar sobre todos los casos que trae
     esa consulta, abrir su documento (PDF) y extraer el texto,
     interceptando la respuesta HTTP en vez de leer la pantalla.

El objetivo final es asociar cada factura (extraída del PDF) con su
movimiento correspondiente en el extracto bancario.
"""

import fitz  # PyMuPDF, para extraer texto de los PDFs
from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeoutError

from config import Config
from exceptions import DataExtractionError
from scrapers.base_scraper import BaseScraper


class CronosScraper(BaseScraper):
    """
    Scraper específico para el sistema Cronos.

    Hereda toda la lógica de manejo del navegador de BaseScraper
    y agrega la lógica de negocio propia de Cronos: navegación al
    módulo de reportes, consulta de la bandeja por caso + fecha,
    y extracción de datos y PDFs de cada caso encontrado.
    """

    # Selector del campo de fecha en el panel "Campos en bandeja".
    SELECTOR_DATE_INPUT = "#txt7bandeja"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.invoices_data = []  # Lista para almacenar los datos de las facturas procesadas

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------
    def login(self) -> None:
        """
        Cronos tiene captcha, así que el login no se puede automatizar.
        Este método simplemente pausa la ejecución para que la persona
        inicie sesión manualmente en la ventana del navegador. Al cerrar
        el Inspector de Playwright (o continuar desde ahí), el flujo sigue.
        """
        self.logger.info("Pausando para login manual (Cronos requiere captcha)...")
        self.navigate(Config.CRONOS_URL)
        self.logger.info("Login manual completado, continuando con el flujo.")

    # ------------------------------------------------------------------
    # Módulo de reportes
    # ------------------------------------------------------------------
    def go_to_reports_module(self, process_name: str = "CAUSACIONES") -> None:
        """
        Navega desde el menú principal hasta la pantalla de
        'Consulta de Casos' dentro del módulo de reportes,
        y selecciona el proceso indicado.

        Args:
            process_name: nombre del proceso a seleccionar en el combo
                          (ej: "CAUSACIONES").
        """
        self.logger.info("Navegando al módulo de reportes...")
        self.page.wait_for_timeout(1000)  # Espera breve para que el menú cargue
        self.page.get_by_role("button", name="MODULO").click()
        self.page.wait_for_timeout(1000)
        self.page.get_by_role("link", name="BPM").click()
        self.page.wait_for_timeout(1000)
        self.page.get_by_role("link", name="OPCIONES").click()
        self.page.wait_for_timeout(1000)
        self.page.get_by_role("link", name="Reportes").click()
        self.page.wait_for_timeout(1000)
        self.page.get_by_role("button", name="REPORTES...").click()
        self.page.wait_for_timeout(1000)
        self.page.get_by_role("link", name="Consulta de Casos").click()
        self.page.wait_for_timeout(1000)

        self.logger.info("Seleccionando proceso: %s", process_name)
        self.page.locator("span").filter(has_text="Seleccione el proceso...").nth(1).click()
        self.page.get_by_role("option", name=process_name).click()

    def search_by_case_and_date(self, case_number: str, date_str: str) -> None:
        """
        Consulta la bandeja de casos filtrando por número de caso y fecha.
        Sobreescribe ambos campos antes de cada consulta, para que cada
        iteración parta de un estado limpio.

        Args:
            case_number: número de caso/bandeja a buscar (ej: "860000018").
            date_str: fecha a buscar, en formato dd/mm/aaaa.
        """
        self.logger.info("Consultando caso=%s, fecha=%s...", case_number, date_str)

        self.page.get_by_role("button", name="Campos en bandeja").click()

        # Se sobreescribe el campo de caso en cada consulta
        self.page.locator("#txt1bandeja").fill(case_number)

        # Se sobreescribe el campo de fecha en cada consulta
        self.page.locator(self.SELECTOR_DATE_INPUT).fill(date_str)

        self.page.get_by_role("button", name="CONSULTAR").click()
        self._wait_for_grid_refresh()

    def _wait_for_grid_refresh(self) -> None:
        """
        Espera a que Kendo termine de refrescar la grilla después de
        una consulta. Sin esto, se corre el riesgo de contar las filas
        mientras la tabla todavía tiene datos de la consulta anterior
        a medio reemplazar, dando conteos incorrectos.
        """
        try:
            # Si la carga es rápida, puede que nunca lleguemos a ver la
            # máscara aparecer; en ese caso no pasa nada, seguimos.
            self.page.locator(".k-loading-mask").wait_for(state="visible", timeout=2000)
        except PlaywrightTimeoutError:
            pass

        try:
            self.page.locator(".k-loading-mask").wait_for(state="hidden", timeout=self.timeout)
        except PlaywrightTimeoutError:
            self.logger.warning("La máscara de carga de Kendo no desapareció a tiempo.")

    def wait_for_locator(self, locator: Locator, timeout: int = None) -> None:
        """
        Espera hasta que un Locator esté visible.
        Es el equivalente a wait_for_selector pero para objetos Locator
        (get_by_role, get_by_text, etc.) en vez de selectores CSS crudos.
        """
        try:
            locator.wait_for(state="visible", timeout=timeout or self.timeout)
        except PlaywrightTimeoutError as e:
            self._take_error_screenshot("locator_wait_timeout")
            raise DataExtractionError("El elemento esperado no apareció a tiempo.") from e

    # ------------------------------------------------------------------
    # Iteración sobre la tabla (grid) de resultados de la bandeja
    # ------------------------------------------------------------------
    def get_bandeja_rows(self) -> Locator:
        """
        Devuelve el locator de todas las filas de datos de la grilla
        de la bandeja (excluye el header, que es un elemento aparte
        en la estructura de Kendo UI Grid).
        """
        return self.page.locator("#gvbusquedabandeja tbody tr.k-master-row")

    def get_grid_headers(self) -> list:
        """
        Lee los títulos de columna del grid en el mismo orden en que
        aparecen las celdas de cada fila (usa data-title o, si no existe,
        data-field como respaldo).

        Leer los headers dinámicamente (en vez de hardcodear el orden
        de columnas) hace que el código no se rompa si Cronos agrega,
        quita o reordena columnas.
        """
        header_cells = self.page.locator("#gvbusquedabandeja .k-grid-header th")
        count = header_cells.count()

        headers = []
        for i in range(count):
            title = header_cells.nth(i).get_attribute("data-title")
            field = header_cells.nth(i).get_attribute("data-field")
            headers.append(title or field or f"col_{i}")

        return headers

    def extract_row_data(self, row: Locator, headers: list) -> dict:
        """
        Extrae los datos de una fila del grid como diccionario,
        usando los headers ya leídos para nombrar cada valor.

        Args:
            row: Locator de la fila (<tr>) a leer.
            headers: lista de nombres de columna, en el mismo orden
                     que las celdas de la fila (ver get_grid_headers).

        Returns:
            Diccionario {nombre_columna: valor_celda}.
        """
        cells = row.locator("td")
        count = cells.count()

        data = {}
        for i in range(count):
            key = headers[i] if i < len(headers) else f"col_{i}"
            data[key] = cells.nth(i).inner_text().strip()

        return data

    def process_current_bandeja_rows(self, supplier: str) -> None:
        """
        Recorre todas las filas de la bandeja YA CONSULTADA (para el
        caso y fecha actuales) y, por cada una, abre el documento y
        extrae su texto.

        La fila se vuelve a buscar en cada iteración (en vez de guardar
        todos los Locator de una sola vez), porque el grid de Kendo
        puede re-renderizar sus filas después de cerrar el visor de
        documento, dejando locators viejos "stale".
        """
        headers = self.get_grid_headers()
        total_rows = self.get_bandeja_rows().count()
        self.logger.info("Se encontraron %d casos en esta consulta.", total_rows)
        for i in range(total_rows):
            row = self.get_bandeja_rows().nth(i)
            row_data = self.extract_row_data(row, headers)
            invoice = row_data.get("Numero_factura", f"fila_{i}")
            invoice_date = row_data.get("Fecha_factura", f"fila_{i}")

            self.logger.info("Procesando factura %d/%d (Caso: %s)...", i + 1, total_rows, invoice)

            try:
                row.click()
                self.page.get_by_text("Documentos").click()
                self.page.get_by_role("button", name="ver documento").first.wait_for(
                    state="visible", timeout=self.timeout
                )

                text = self.extract_document_text(document_index=0)
                self.logger.debug("--- Factura %s (Fecha %s) ---\n%s", invoice, invoice_date, text)
                self.invoices_data.append({"invoice": invoice, "date": invoice_date, "text": text, "supplier": supplier})

                self.close_document_viewer()

            except Exception as e:
                self.logger.error("Error procesando la factura %s: %s", invoice, e)
                self._take_error_screenshot(f"invoice_{i}_error")

    def get_invoices_data(self) -> list:
        """
        Devuelve la lista de datos de facturas procesadas.
        Cada elemento es un diccionario con las claves:
        'invoice', 'date', 'text' y 'supplier'.
        """
        return self.invoices_data

    # ------------------------------------------------------------------
    # Flujo completo: iterar fechas -> iterar casos de cada fecha
    # ------------------------------------------------------------------
    def process_all_dates(self, case_number: list[str], dates: list, process_name: str = "CAUSACIONES") -> None:
        """
        Flujo completo: para cada fecha de la lista, consulta la bandeja
        filtrando por case_number (fijo) y esa fecha, y procesa todos
        los casos que trae esa consulta antes de pasar a la siguiente fecha.

        Args:
            case_number: número de caso/bandeja fijo a usar en cada consulta.
            dates: lista de fechas en formato dd/mm/aaaa a iterar.
            process_name: proceso a seleccionar antes de empezar a consultar.
        """
        self.go_to_reports_module(process_name=process_name)
        for case in case_number:
            self.logger.info("=== Consultando Proveedor: %s ===", case)
            for date_str in dates:
                self.logger.info("=== Consultando fecha: %s ===", date_str)
                self.search_by_case_and_date(case, date_str)
                self.process_current_bandeja_rows(case)

        self.logger.info("Procesamiento de todas las fechas finalizado.")

    # ------------------------------------------------------------------
    # Extracción de texto del PDF del caso
    # ------------------------------------------------------------------
    def extract_document_text(self, document_index: int = 0) -> str:
        """
        Hace click en 'ver documento' e intercepta la respuesta HTTP
        que trae el PDF directamente (sin abrir el visor ni depender
        del portapapeles / pyautogui), y extrae el texto con PyMuPDF.

        Este enfoque es mucho más confiable que leer la pantalla:
        funciona también en modo headless y no depende del foco
        de la ventana ni de tiempos de renderizado.

        Args:
            document_index: índice del botón "ver documento" a usar,
                             si hay varios documentos en la lista
                             (0 = el primero).

        Returns:
            El texto completo extraído del PDF.

        Raises:
            DataExtractionError: si no se pudo interceptar el PDF
                                  o no se pudo extraer el texto.
        """
        self.logger.info("Solicitando documento PDF (índice %d)...", document_index)

        try:
            with self.page.expect_response(
                lambda response: "application/pdf" in response.headers.get("content-type", "")
            ) as response_info:
                self.page.get_by_role("button", name="ver documento").nth(document_index).click()

            response = response_info.value
            pdf_bytes = response.body()

        except PlaywrightTimeoutError as e:
            self._take_error_screenshot("pdf_response_timeout")
            raise DataExtractionError(
                "No se recibió una respuesta PDF a tiempo. "
            ) from e

        self.logger.info("PDF recibido (%d bytes). Extrayendo texto...", len(pdf_bytes))

        try:
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                text = "\n".join(page.get_text() for page in doc)
        except Exception as e:
            raise DataExtractionError("No se pudo leer el contenido del PDF.") from e

        if not text.strip():
            self.logger.warning("El PDF se extrajo pero no contiene texto (¿podría ser escaneado/imagen?).")

        return text

    def close_document_viewer(self, button_name: str = "Cerrar", close_button_timeout: int = 3000) -> None:
        """
        Cierra el visor de documento/PDF después de extraer el texto,
        para dejar la pantalla lista para el siguiente caso.

        IMPORTANTE: el visor de PDF de Cronos está envuelto en una
        ventana Kendo UI (k-window), NO en el visor nativo de PDF del
        navegador. Esa ventana Kendo SÍ es DOM normal de la página, así
        que Playwright puede interactuar con ella (click en su botón de
        cierre, o Escape). Lo crítico es esperar a que la ventana
        realmente desaparezca del DOM antes de seguir: si el siguiente
        click a una fila se dispara mientras la ventana todavía está
        montada (aunque ya no sea visible), Playwright lo detecta como
        "subtree intercepts pointer events" y falla ese caso completo,
        perdiendo esa factura silenciosamente. Por eso NO alcanza con
        mandar Escape y seguir sin confirmar: hay que esperar el cierre.

        Args:
            button_name: nombre accesible del botón de cierre. Ajustar
                         según el texto real del sitio (ej: "Cerrar", "close", "X").
            close_button_timeout: timeout corto (en ms) para el intento
                         de encontrar el botón. Se usa un valor bajo
                         a propósito (en vez de self.timeout) porque
                         si el botón no existe, no tiene sentido esperar
                         el timeout completo de 30s en cada caso procesado.
        """
        # Selector específico de la ventana Kendo del VISOR DE PDF.
        # OJO: ".k-window.winDoc1" es AMBIGUO -- Cronos reutiliza esa
        # misma clase base tanto para la ventana "Documentos" (lista de
        # documentos) como para la ventana del visor de PDF, y cuando
        # ambas están montadas a la vez, ese selector matchea 2 elementos
        # y Playwright tira "strict mode violation" en el wait_for.
        # Por eso se apunta puntualmente por aria-labelledby, que sí
        # distingue una ventana de la otra. Se usa .last por si queda
        # algún duplicado oculto de una iteración anterior sin remover
        # del DOM todavía.
        pdf_window = self.page.locator('[aria-labelledby="winDocPdf_wnd_title"]').last

        try:
            close_button = self.page.get_by_role("button", name=button_name)
            close_button.wait_for(state="visible", timeout=close_button_timeout)
            close_button.click()
        except PlaywrightTimeoutError:
            self.logger.debug(
                "No se encontró el botón de cierre ('%s') en %dms. Usando Escape...",
                button_name,
                close_button_timeout,
            )
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass

        # CRÍTICO: esperar a que la ventana realmente desaparezca del DOM,
        # no solo asumir que el click/Escape la cerró.
        try:
            pdf_window.wait_for(state="hidden", timeout=self.timeout)
            self.logger.info("Visor de documento cerrado correctamente.")
        except PlaywrightTimeoutError:
            self.logger.warning(
                "La ventana del visor de PDF sigue presente en el DOM tras el intento "
                "de cierre. Esto puede bloquear el click de la siguiente fila."
            )