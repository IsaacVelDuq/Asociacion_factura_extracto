import re
from itertools import zip_longest

import pandas as pd
import pdfplumber as plumb

from logger_setup import get_logger


class PDFMovementsExtractor:
    """
    Extrae la tabla de movimientos de un extracto PDF de tarjeta de crédito.

    Uso
    ----
    extractor = PDFMovementsExtractor()
    df = extractor.extract_movements
    (r"C:\\Extracto.pdf")
    """

    _PRIMARY_SETTINGS = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "text",
        "intersection_tolerance": 4,
        "snap_tolerance": 3,
        "join_tolerance": 1,
        "edge_min_length": 3,
        "text_x_tolerance": 3,
    }

    _FALLBACK_SETTINGS = [
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "intersection_tolerance": 5,
            "snap_tolerance": 4,
            "join_tolerance": 2,
            "edge_min_length": 3,
            "text_x_tolerance": 4,
        },
        {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "intersection_tolerance": 6,
            "snap_tolerance": 5,
            "join_tolerance": 3,
            "edge_min_length": 2,
            "text_x_tolerance": 3,
        },
    ]

    _MOVEMENTS_REQUIRED_KEYWORDS = [
        "fecha",
        "descripci",
        "saldo",
    ]

    _MOVEMENTS_REJECT_KEYWORDS = [
        "cheque",
        "cod. banco",
        "cod banco",
    ]

    def __init__(self) -> None:
        self.logger = get_logger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize_table(self, table):
        """
        Convierte la tabla extraída por pdfplumber en un DataFrame,
        expandiendo las celdas que contienen saltos de línea.
        """

        headers = table[0]
        rows = table[1:]

        split_rows = []

        for row in rows:

            split_cells = []

            for cell in row:

                if cell in [None, ""]:
                    split_cells.append([""])
                else:
                    split_cells.append(str(cell).split("\n"))

            for values in zip_longest(*split_cells, fillvalue=""):
                split_rows.append(values)

        return pd.DataFrame(split_rows, columns=headers)

    def _adjust_cells(self, df):

        if ("Descripción" not in df.columns) or ("to Fecha" not in df.columns):
            self.logger.debug("_adjust_cells: columnas necesarias no presentes, se retorna sin cambios.")
            return df

        def adjust_string(texto, caracter):

            if caracter in texto:
                izquierda, derecha = texto.split(caracter, 1)
                return izquierda, derecha

            return texto, ""

        def process_row(row):

            descripcion = str(row["Descripción"]) or ""
            fecha = str(row["to Fecha"]) or ""

            if fecha.strip() != "" and descripcion and descripcion[0].isdigit():

                nueva_fecha = fecha + descripcion[0]
                nueva_descripcion = descripcion[1:]

            else:

                nueva_fecha = fecha
                nueva_descripcion = descripcion

            return pd.Series(
                {
                    "to Fecha": nueva_fecha,
                    "Descripción": nueva_descripcion,
                }
            )

        df[["to Fecha", "Descripción"]] = df.apply(
            process_row,
            axis=1,
        )

        def process_valor(item):

            izquierda, derecha = adjust_string(
                str(item["Valor a Pagar"]),
                "$",
            )

            nuevo_valor = (
                str(item["Valor"]) + izquierda
            ).replace("$", "").strip()

            return pd.Series(
                {
                    "Valor": nuevo_valor,
                    "Valor a Pagar": derecha,
                }
            )

        df[["Valor", "Valor a Pagar"]] = df.apply(
            process_valor,
            axis=1,
        )

        def process_saldo(item):

            izquierda, derecha = adjust_string(
                str(item["Saldo Pendiente"]),
                "$",
            )

            nuevo_valor = (
                str(item["Valor a Pagar"]) + izquierda
            ).replace("$", "").strip()

            return pd.Series(
                {
                    "Valor a Pagar": nuevo_valor,
                    "Saldo Pendiente": derecha,
                }
            )

        df[["Valor a Pagar", "Saldo Pendiente"]] = df.apply(
            process_saldo,
            axis=1,
        )

        def normalizar_signo(numero):

            numero = str(numero).strip()

            if numero.endswith(("+", "-")):
                signo = numero[-1]
                numero = signo + numero[:-1]

            return numero

        df["Valor a Pagar"] = df["Valor a Pagar"].apply(
            normalizar_signo
        )

        return df

    # ------------------------------------------------------------------
    # Validación de tablas
    # ------------------------------------------------------------------

    def _is_movements_table(self, table):

        if not table:
            return False

        headers = " ".join(
            str(h or "").lower()
            for h in table[0]
        )

        for keyword in self._MOVEMENTS_REJECT_KEYWORDS:

            if keyword in headers:
                return False

        for keyword in self._MOVEMENTS_REQUIRED_KEYWORDS:

            if keyword not in headers:
                return False

        self.logger.debug("_is_movements_table: cabeceras válidas detectadas.")
        return True
    
        # ------------------------------------------------------------------
    # Reparación de tablas de 9 columnas
    # ------------------------------------------------------------------

    def _detect_missing_column(self, headers):
        """
        Determina dónde insertar la columna faltante cuando pdfplumber
        devuelve una tabla de 9 columnas.
        """

        valor_indices = [
            i
            for i, h in enumerate(headers)
            if "Valor" in str(h)
        ]

        if len(valor_indices) == 1:
            return valor_indices[0] + 1

        tasa_indices = [
            i
            for i, h in enumerate(headers)
            if "Tasa" in str(h) or "tasa" in str(h)
        ]

        if len(tasa_indices) < 2:
            return len(headers)

        return 4

    def _repair_9_col_table(self, table):

        if not table or len(table[0]) != 9:
            return table

        self.logger.debug(
            "_repair_9_col_table: reparando tabla de 9 columnas (insert_pos=%s).",
            self._detect_missing_column([str(h or "").strip() for h in table[0]]),
        )

        headers = [
            str(h or "").strip()
            for h in table[0]
        ]

        insert_pos = self._detect_missing_column(headers)

        repaired = []

        for row in table:
            row = list(row)
            row.insert(insert_pos, None)
            repaired.append(row)

        return repaired

    # ------------------------------------------------------------------
    # Parseo final
    # ------------------------------------------------------------------

    def _parse(self, df):

        df.columns = [
            "Documen No.",
            "to Fecha",
            "Descripción",
            "Valor",
            "Valor a Pagar",
            "Saldo Pendiente",
            "No.Cuota",
            "Cuota sPend.",
            "sTasa E.A.",
            "Tasa M.V",
        ]

        df = df.drop([0, 1])

        df["to Fecha"] = (
            pd.to_datetime(
                df["to Fecha"],
                format="%Y%m%d",
            )
            .dt.date
        )

        numeric_cols = [
            "Valor",
            "Valor a Pagar",
            "Saldo Pendiente",
            "No.Cuota",
            "Cuota sPend.",
            "sTasa E.A.",
            "Tasa M.V",
        ]

        for col in numeric_cols:

            df[col] = (
                df[col]
                .astype(str)
                .str.replace(r"[\",$]", "", regex=True)
                .str.strip()
            )

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce",
            )

        self.logger.debug("_parse: conversión numérica completada para %d columnas.", len(numeric_cols))
        return df

    # ------------------------------------------------------------------
    # Extracción principal
    # ------------------------------------------------------------------

    def extract_movements(self, pdf_path: str) -> pd.DataFrame:
        """
        Extrae la tabla de movimientos del PDF.

        Parameters
        ----------
        pdf_path : str
            Ruta del PDF.

        Returns
        -------
        pandas.DataFrame
        """

        pattern = re.compile(
            r"MOVIMIENTOS",
            re.IGNORECASE,
        )

        all_settings = (
            [self._PRIMARY_SETTINGS]
            + self._FALLBACK_SETTINGS
        )

        dfs = []

        with plumb.open(pdf_path) as pdf:

            total_pages = len(pdf.pages)
            self.logger.info("Abriendo PDF '%s' con %d página(s) para extraer MOVIMIENTOS.", pdf_path, total_pages)

            for page_num, page in enumerate(pdf.pages, start=1):

                text = page.extract_text() or ""

                if not pattern.search(text):
                    self.logger.debug("Página %d: no contiene sección 'MOVIMIENTOS'.", page_num)
                    continue

                best_tables = None
                used_attempt = -1

                # ----------------------------------------------------------
                # Intentar diferentes estrategias de extracción
                # ----------------------------------------------------------

                for attempt, settings in enumerate(all_settings):

                    tables = page.extract_tables(settings)

                    candidates = [
                        table
                        for table in tables
                        if len(table) > 3
                        and len(table[0]) in (9, 10)
                        and self._is_movements_table(table)
                    ]

                    has_10 = any(
                        len(table[0]) == 10
                        for table in candidates
                    )

                    self.logger.debug(
                        "Página %d intento %d: %d tabla(s) candidatas encontradas (has_10=%s).",
                        page_num,
                        attempt,
                        len(candidates),
                        has_10,
                    )

                    if has_10:
                        best_tables = candidates
                        used_attempt = attempt
                        break

                    if candidates and best_tables is None:
                        best_tables = candidates
                        used_attempt = attempt


                if not best_tables:
                    self.logger.debug("Página %d: no se encontraron tablas válidas con ninguna estrategia.", page_num)
                    continue

                self.logger.info(
                    "Página %d: %d tabla(s) seleccionadas por intento %d.",
                    page_num,
                    len(best_tables),
                    used_attempt,
                )

                # ----------------------------------------------------------
                # Procesar tablas encontradas
                # ----------------------------------------------------------

                for table in best_tables:

                    ncols = len(table[0])

                    if ncols == 9:
                        table = self._repair_9_col_table(table)
                        ncols = len(table[0])

                    if ncols != 10:
                        continue

                    if len(table) <= 3:
                        continue

                    df = self._normalize_table(table)
                    df = self._adjust_cells(df)
                    df = self._parse(df)

                    dfs.append(df)

        if not dfs:
            return pd.DataFrame()

        result = pd.concat(
            dfs,
            ignore_index=True,
        )

        return result
    
    def extract_period(self, pdf_path: str) -> str:
        """
        Extrae el período liquidado final del PDF.

        Ejemplo:
            Periodo liquidado JUN.08/26 - JUL.08/26
            -> "JULIO -2026"
        """

        pattern = re.compile(
            r"Periodo\s+liquidado\s+[A-Z]{3}\.\d{2}/\d{2}\s*-\s*([A-Z]{3})\.\d{2}/(\d{2})",
            re.IGNORECASE,
        )

        month_map = {
            "ENE": "ENERO",
            "FEB": "FEBRERO",
            "MAR": "MARZO",
            "ABR": "ABRIL",
            "MAY": "MAYO",
            "JUN": "JUNIO",
            "JUL": "JULIO",
            "AGO": "AGOSTO",
            "SEP": "SEPTIEMBRE",
            "OCT": "OCTUBRE",
            "NOV": "NOVIEMBRE",
            "DIC": "DICIEMBRE",
        }

        with plumb.open(pdf_path) as pdf:
            for page in pdf.pages:

                text = page.extract_text() or ""

                match = pattern.search(text)

                if match:
                    month_abbr = match.group(1).upper()  # JUL
                    year_short = match.group(2)          # 26

                    month_name = month_map.get(month_abbr)

                    if month_name:
                        self.logger.info("Período liquidado encontrado: %s -20%s", month_name, year_short)
                        return f"{month_name}_20{year_short}"
        self.logger.warning("No se encontró el período liquidado en el PDF '%s'.", pdf_path)            
        return ""