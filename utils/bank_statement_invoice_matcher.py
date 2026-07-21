"""
Invoice/bank reconciliation module.
Asocia facturas (extraídas previamente de Cronos, con su texto de PDF ya
parseado) con sus movimientos correspondientes en el extracto bancario.

Cada proveedor tiene una estructura de factura distinta, así que la forma
de obtener "valores candidatos" a buscar en el extracto varía por
proveedor (ver ReconciliationStrategy y sus implementaciones más abajo).
La lógica de matching contra el extracto (_find_candidate_indices) es
única y compartida por todos los proveedores: no le importa de dónde
salieron los valores candidatos, solo sabe buscarlos en el DataFrame.
"""

import itertools
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Optional

import pandas as pd

from logger_setup import get_logger


# ---------------------------------------------------------------------
# Utilidades de parseo de moneda, compartidas entre proveedor y proveedor
# ---------------------------------------------------------------------
def parse_colombian_currency(raw_value) -> Optional[float]:
    """
    Convierte un valor en formato colombiano (ej: "98.770,00", con punto
    como separador de miles y coma como decimal) a float (ej: 98770.00).
    """
    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float)):
        return round(float(raw_value), 0)

    try:
        cleaned = str(raw_value).strip().replace(".", "").replace(",", ".")
        return round(float(cleaned), 0)
    except (ValueError, AttributeError):
        return None


def parse_us_currency(raw_value) -> Optional[float]:
    """
    Convierte un valor en formato estadounidense (ej: "337,286.00", con
    coma como separador de miles y punto como decimal) a float
    (ej: 337286.00).
    """
    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float)):
        return round(float(raw_value), 0)

    try:
        cleaned = str(raw_value).strip().replace(",", "")
        return round(float(cleaned), 0)
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------
# Estrategias de conciliación por proveedor
# ---------------------------------------------------------------------
class ReconciliationStrategy(ABC):
    """
    Interfaz que debe implementar cada proveedor para poder conciliarse.

    Cada estrategia sabe, a partir del texto de la factura:
      1. Extraer la fecha de expedición.
      2. Generar una o más "hipótesis" de valores candidatos, en orden
         de prioridad.

    Una hipótesis es una lista de valores que, TODOS JUNTOS, deben
    matchear movimientos DISTINTOS y disponibles del extracto (mismo
    contrato que ya espera _find_candidate_indices, sin cambios).

    Devolver una lista vacía significa "esta factura no aplica para esta
    conciliación" y se descarta sin pasar por unresolved_invoices.
    """

    @abstractmethod
    def extract_expedition_date(self, text: str) -> Optional[pd.Timestamp]:
        ...

    @abstractmethod
    def get_candidate_value_lists(self, text: str) -> list:
        ...


class CardPaymentStrategy(ReconciliationStrategy):
    """
    Estrategia original y ya validada en producción: facturas que traen
    un bloque "Pagos" con el número de tarjeta enmascarado y el valor
    pagado (proveedor 860000018 / AVIATUR).

    Comportamiento preservado exactamente igual al de la versión anterior:
    - Si no hay ningún pago con la tarjeta configurada -> lista vacía
      (la factura se descarta, es de otra tarjeta).
    - Si hay pagos -> UNA sola hipótesis con todos ellos.
    """

    DATE_PATTERN = re.compile(
        r"Fecha Expedici[oó]n\s+(\d{1,2}/\d{1,2}/\d{4})"
    )

    PAYMENT_PATTERN = re.compile(
        r"Pagos:\s*Comp:\s*\d+\s*\([^)]*?(\d{4})\)\s*\n\(?\s*([\d.,]+)\s*\)?"
    )

    def __init__(self, card_last_digits: str) -> None:
        self.card_last_digits = str(card_last_digits)

    def extract_expedition_date(self, text: str) -> Optional[pd.Timestamp]:
        match = self.DATE_PATTERN.search(text)
        if not match:
            return None
        date_str = match.group(1)
        try:
            return pd.to_datetime(date_str, dayfirst=True).normalize()
        except (ValueError, TypeError):
            return None

    def get_candidate_value_lists(self, text: str) -> list:
        values = []
        for match in self.PAYMENT_PATTERN.finditer(text):
            card_digits, raw_value = match.group(1), match.group(2)
            if card_digits != self.card_last_digits:
                continue
            value = parse_colombian_currency(raw_value)
            if value is not None:
                values.append(value)

        if not values:
            return []

        # Una sola hipótesis: exactamente el mismo comportamiento que
        # tenía la versión anterior (una única lista payment_values).
        return [values]


class PurchaseGroupingStrategy(ReconciliationStrategy):
    """
    Estrategia para facturas de EXITO VIAJES Y TURISMO S.A.S.
    (proveedor 9006401736).

    No hay bloque "Pagos" ni número de tarjeta: son facturas con N líneas
    "Venta a Nombre de <proveedor> NIT.<10 dígitos><valor>" (el valor va
    pegado al NIT sin separador, en formato estadounidense: coma de
    miles, punto decimal).

    Como no sabemos si el banco procesó el pago como un solo movimiento,
    por proveedor (NIT), por línea, o agrupando algunas líneas, se
    generan varias HIPÓTESIS de valores candidatos, en este orden de
    prioridad:
      1. Agrupadas por NIT del proveedor (si hay más de un NIT distinto).
      2. Total de la factura (todas las compras en un solo movimiento).
      3. Cada compra individual (una compra = un movimiento).
      4. Combinaciones agrupando 2 compras en un movimiento y el resto
         individual (una hipótesis por cada combinación posible de 2).
      5. Lo mismo agrupando 3, 4... hasta N-1 compras (agrupar las N
         compras sería igual al "Total", por eso no se repite).
    """

    DATE_PATTERN = re.compile(
        r"Fecha Validaci[oó]n DIAN:\s*(\d{4}-\d{2}-\d{2})"
    )

    # El NIT puede tener distinta cantidad de dígitos según el proveedor:
    # las empresas colombianas suelen traer 10 (9 + dígito de
    # verificación), pero proveedores extranjeros (ej: RESTEL S.A.,
    # España) pueden traer 9 o menos. Por eso NO se fija un ancho exacto
    # de dígitos para el NIT -- en cambio, se ancla el fin del NIT por la
    # FORMA del monto que le sigue (agrupado de a 3 dígitos con comas,
    # terminado en 2 decimales), que sí es consistente siempre. El NIT
    # se captura de forma no-codiciosa (\d+?) y el monto exige el
    # agrupamiento estricto de miles para no confundirse con dígitos
    # sueltos del NIT.
    VENTA_LINE_PATTERN = re.compile(
        r"Venta a Nombre de\s+(.*?)\s+NIT\.(\d+?)\s*(\d{1,3}(?:,\d{3})*\.\d{2})",
        re.DOTALL,
    )

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    def extract_expedition_date(self, text: str) -> Optional[pd.Timestamp]:
        match = self.DATE_PATTERN.search(text)
        if not match:
            return None
        try:
            return pd.to_datetime(match.group(1)).normalize()
        except (ValueError, TypeError):
            return None

    def extract_purchase_values(self, text: str) -> list:
        purchases = []
        matches = list(self.VENTA_LINE_PATTERN.finditer(text))

        self.logger.info("Se encontraron %d líneas de compra.", len(matches))

        for match in matches:
            supplier_name = match.group(1).strip()
            nit = match.group(2)
            raw_value = match.group(3)

            self.logger.info(
                "Proveedor: %s | NIT: %s | Valor: %s",
                supplier_name, nit, raw_value,
            )

            value = parse_us_currency(raw_value)
            if value is not None:
                purchases.append({"supplier": supplier_name, "nit": nit, "value": value})

        return purchases

    def get_candidate_value_lists(self, text: str) -> list:
        purchase_values = self.extract_purchase_values(text)
        if not purchase_values:
            return []
        return self._build_candidate_lists(purchase_values)

    @staticmethod
    def _build_candidate_lists(purchase_values: list) -> list:
        """
        Genera las hipótesis de valores candidatos a partir de las compras
        extraídas de la factura, en orden de prioridad:
        1. Agrupadas por NIT del proveedor (cuando exista más de un NIT).
        2. Total de la factura.
        3. Compras individuales.
        4. Combinaciones agrupando k compras (k de 2 a n-1).
        """
        n = len(purchase_values)
        candidates = []
        individual_values = [item["value"] for item in purchase_values]

        # 1. Agrupar por NIT
        grouped_by_nit = defaultdict(float)
        for item in purchase_values:
            grouped_by_nit[item["nit"]] += item["value"]

        if len(grouped_by_nit) > 1:
            candidates.append([round(value, 2) for value in grouped_by_nit.values()])

        # 2. Total de la factura
        total = round(sum(individual_values), 2)
        candidates.append([total])

        # 3. Compras individuales
        if n > 1:
            candidates.append(list(individual_values))

        # 4. Combinaciones
        for k in range(2, n):
            for combo_indices in itertools.combinations(range(n), k):
                combo_set = set(combo_indices)
                grouped_value = round(
                    sum(individual_values[i] for i in combo_indices), 2
                )
                remaining_values = [
                    individual_values[i] for i in range(n) if i not in combo_set
                ]
                candidates.append([grouped_value] + remaining_values)

        return candidates


class InvoiceBankReconciler:
    """
    Reconciliador de facturas contra el extracto bancario.

    Recibe:
      - invoices_data: lista de diccionarios con la estructura
        {"invoice": <número de factura>, "text": <texto extraído del PDF>,
         "supplier": <NIT del proveedor, como string>}
      - bank_statements: DataFrame con columnas
        ["to Fecha", "Descripción", "Valor"] (la columna "Factura" es
        opcional: si no viene, se crea automáticamente vacía)
      - card_last_digits: últimos 4 dígitos de la tarjeta a filtrar para
        el proveedor 860000018 (comportamiento original, sin cambios)
      - supplier_strategies: dict opcional {supplier: ReconciliationStrategy}
        para registrar proveedores ADICIONALES sin tocar el proveedor
        860000018 (que siempre usa CardPaymentStrategy internamente).

    IMPORTANTE - Asignación atómica por factura: de todas las hipótesis
    de valores candidatos que ofrezca la estrategia del proveedor, se
    prueban en orden hasta que UNA logre encontrar un movimiento
    disponible y distinto para CADA uno de sus valores. Recién ahí se
    confirma la asignación en el DataFrame. Si ninguna hipótesis
    funciona en la primera pasada (fecha exacta), la factura completa se
    guarda en self.unresolved_invoices -- CON TODAS sus hipótesis
    intactas -- para la segunda pasada.

    El proceso se realiza en dos pasadas:
      1. Coincidencia exacta por fecha y valor (probando cada hipótesis
         de la estrategia del proveedor en orden).
      2. Para lo que quedó sin resolver: se reintentan TODAS las mismas
         hipótesis, en el mismo orden de prioridad, pero sin exigir
         fecha exacta (se toma el movimiento con la fecha más cercana).
         Esto no revive una única hipótesis "recordada": se prueban
         todas de nuevo, exactamente como en la primera pasada.
    """

    CREDIT_NOTE_PATTERN = re.compile(r"Nota\s+Cr[eé]dito", re.IGNORECASE)
    EXCLUDED_DESCRIPTION_KEYWORDS = "COMPRAS|IMP 4XMIL|REVERSIO"

    def __init__(
        self,
        invoices_data: list,
        bank_statements: pd.DataFrame,
        card_last_digits: str,
        supplier_strategies: Optional[dict] = None,
    ) -> None:
        self.logger = get_logger(self.__class__.__name__)

        self.invoices_data = invoices_data
        self.bank_statements = bank_statements
        self.card_last_digits = str(card_last_digits)

        self.strategies: dict = {
            "860000018": CardPaymentStrategy(card_last_digits=self.card_last_digits),
        }
        if supplier_strategies:
            self.strategies.update(supplier_strategies)

        self.unresolved_invoices: list = []
        self.excluded_invoices: list = []
        self.discarded_invoices: list = []

        self._normalize_bank_statements()

    # ------------------------------------------------------------------
    # Normalización inicial del extracto bancario
    # ------------------------------------------------------------------
    def _normalize_bank_statements(self) -> None:
        self.logger.info("Normalizando columnas del extracto bancario...")

        self.bank_statements = self._filter_irrelevant_movements(self.bank_statements)

        self.bank_statements["to Fecha"] = self._parse_bank_dates(
            self.bank_statements["to Fecha"]
        )

        if self.bank_statements["Valor"].dtype == object:
            self.logger.debug("Columna 'Valor' es texto, convirtiendo a numérico...")
            self.bank_statements["Valor"] = self.bank_statements["Valor"].apply(
                parse_colombian_currency
            )

        keep_cols = ["to Fecha", "Descripción", "Valor"]
        if "Factura" in self.bank_statements.columns:
            keep_cols.append("Factura")
        self.bank_statements = self.bank_statements[keep_cols]

        if "Factura" not in self.bank_statements.columns:
            self.logger.info("Columna 'Factura' no existía en el extracto, se crea vacía (pd.NA).")
            self.bank_statements["Factura"] = pd.NA

    def _filter_irrelevant_movements(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = (
            df["Descripción"]
            .str.strip()
            .str.upper()
            .str.contains(self.EXCLUDED_DESCRIPTION_KEYWORDS, na=False)
        )

        excluded_count = int(mask.sum())
        if excluded_count:
            self.logger.info(
                "Se excluyeron %d movimiento(s) del extracto por descripción (%s).",
                excluded_count,
                self.EXCLUDED_DESCRIPTION_KEYWORDS,
            )

        return df[~mask].copy()

    @staticmethod
    def _parse_bank_dates(series: pd.Series) -> pd.Series:
        if pd.api.types.is_datetime64_any_dtype(series):
            return series.dt.normalize()

        non_null = series.dropna()
        sample = str(non_null.iloc[0]) if not non_null.empty else ""
        is_iso_format = bool(re.match(r"^\d{4}-\d{2}-\d{2}", sample))

        if is_iso_format:
            return pd.to_datetime(series, format="%Y-%m-%d").dt.normalize()

        return pd.to_datetime(series, dayfirst=True).dt.normalize()

    # ------------------------------------------------------------------
    # Punto de entrada principal
    # ------------------------------------------------------------------
    def reconcile(self) -> tuple:
        self.logger.info(
            "Iniciando conciliación de %d factura(s) contra %d movimiento(s) bancario(s)...",
            len(self.invoices_data),
            len(self.bank_statements),
        )

        for entry in self.invoices_data:
            self._process_invoice(entry)

        self._second_pass()

        self._remove_resolved_from_unresolved()

        self.logger.info(
            "Conciliación finalizada. %d factura(s) quedaron sin resolver, "
            "%d excluida(s) (Notas Crédito), %d descartada(s) (sin valores/proveedor no soportado).",
            len(self.unresolved_invoices),
            len(self.excluded_invoices),
            len(self.discarded_invoices),
        )
        if self.discarded_invoices:
            self.logger.info(
                "Detalle de descartadas: %s",
                [f"{d['invoice']} ({d['reason']})" for d in self.discarded_invoices],
            )

        unresolved_df = self._build_unresolved_dataframe()

        return self.bank_statements, unresolved_df

    def _build_unresolved_dataframe(self) -> pd.DataFrame:
        columns = ["invoice", "text", "supplier", "payment_values"]

        if not self.unresolved_invoices:
            return pd.DataFrame(columns=columns)

        # Se exportan solo las columnas relevantes (candidate_value_lists
        # es información interna para la segunda pasada, no hace falta
        # en el reporte final).
        rows = [
            {
                "invoice": entry.get("invoice"),
                "text": entry.get("text"),
                "supplier": entry.get("supplier"),
                "payment_values": entry.get("payment_values", []),
            }
            for entry in self.unresolved_invoices
        ]
        df = pd.DataFrame(rows, columns=columns)

        df["payment_values"] = df["payment_values"].apply(
            lambda values: ", ".join(map(str, values)) if values else ""
        )

        return df

    # ------------------------------------------------------------------
    # Procesamiento de una factura individual
    # ------------------------------------------------------------------
    def _process_invoice(self, entry: dict) -> None:
        """
        Procesa una factura: usa la estrategia del proveedor para extraer
        fecha y valores candidatos, y prueba cada hipótesis de valores
        contra el extracto hasta que una tenga éxito.

        Si ninguna hipótesis funciona con fecha exacta, la factura se
        guarda en unresolved_invoices CON TODAS sus hipótesis intactas
        (candidate_value_lists), para que la segunda pasada pueda
        volver a probarlas todas, en el mismo orden, sin fecha exacta.
        """
        invoice_number = entry.get("invoice")
        text = entry.get("text", "") or ""
        supplier = entry.get("supplier")

        self.logger.info("Procesando factura %s (proveedor: %s)...", invoice_number, supplier)

        if self.CREDIT_NOTE_PATTERN.search(text):
            self.logger.info(
                "Factura %s es una Nota Crédito, se excluye completamente del proceso.",
                invoice_number,
            )
            self.excluded_invoices.append(entry)
            return

        strategy = self.strategies.get(str(supplier))
        if strategy is None:
            self.logger.warning(
                "Factura %s: el proveedor '%s' no tiene estrategia de conciliación registrada. Se descarta.",
                invoice_number, supplier,
            )
            self.discarded_invoices.append({
                "invoice": invoice_number, "supplier": supplier,
                "reason": "proveedor sin estrategia registrada",
            })
            return

        candidate_value_lists = strategy.get_candidate_value_lists(text)
        if not candidate_value_lists:
            self.logger.info(
                "Factura %s: no se encontraron valores candidatos para el proveedor '%s'. Se descarta.",
                invoice_number, supplier,
            )
            self.discarded_invoices.append({
                "invoice": invoice_number, "supplier": supplier,
                "reason": "sin valores candidatos",
            })
            return

        expedition_date = strategy.extract_expedition_date(text)
        if expedition_date is None:
            self.logger.warning(
                "Factura %s: no se encontró la fecha de expedición en el texto. Se envía a revisión.",
                invoice_number,
            )
            unresolved_entry = entry.copy()
            unresolved_entry["payment_values"] = candidate_value_lists[0]
            unresolved_entry["candidate_value_lists"] = candidate_value_lists
            self.unresolved_invoices.append(unresolved_entry)
            return

        self.logger.info(
            "Factura %s: fecha=%s, %d hipótesis de valores a probar.",
            invoice_number, expedition_date.date(), len(candidate_value_lists),
        )

        for hypothesis_index, payment_values in enumerate(candidate_value_lists, start=1):
            candidate_indices = self._find_candidate_indices(expedition_date, payment_values)

            if candidate_indices is not None:
                for idx in candidate_indices:
                    self.bank_statements.at[idx, "Factura"] = invoice_number

                self.logger.info(
                    "Factura %s asociada correctamente (hipótesis %d/%d, %d movimiento(s)).",
                    invoice_number, hypothesis_index, len(candidate_value_lists), len(candidate_indices),
                )
                return

        # Ninguna hipótesis funcionó con fecha exacta: se guarda TODO el
        # conjunto de hipótesis (candidate_value_lists), no solo la
        # primera, para que la segunda pasada pueda volver a probarlas
        # todas sin exigir fecha exacta.
        self.logger.warning(
            "Factura %s: no se pudo asociar con ninguna de las %d hipótesis (fecha exacta). "
            "Se envía a revisión para reintentar en la segunda pasada.",
            invoice_number, len(candidate_value_lists),
        )
        unresolved_entry = entry.copy()
        unresolved_entry["payment_values"] = candidate_value_lists[0]
        unresolved_entry["candidate_value_lists"] = candidate_value_lists
        self.unresolved_invoices.append(unresolved_entry)

    # ------------------------------------------------------------------
    # Búsqueda de movimientos candidatos en el extracto bancario
    # ------------------------------------------------------------------
    def _find_candidate_indices(
        self,
        expedition_date: pd.Timestamp,
        payment_values: list,
        nearest_date: bool = False,
    ) -> Optional[list]:
        """
        NO MODIFICAR: agnóstica a de dónde salieron los valores
        candidatos (tarjeta, agrupación de compras, o estrategia futura).
        """
        reserved_indices = set()
        candidate_indices = []

        for value in payment_values:

            if not nearest_date:
                subset = self.bank_statements[
                    (self.bank_statements["to Fecha"] == expedition_date)
                    & (self.bank_statements["Valor"].round(2) == value)
                    & (self.bank_statements["Factura"].isna())
                    & (~self.bank_statements.index.isin(reserved_indices))
                ]
            else:
                subset = self.bank_statements[
                    (self.bank_statements["Valor"].round(2) == value)
                    & (self.bank_statements["Factura"].isna())
                    & (~self.bank_statements.index.isin(reserved_indices))
                ].copy()

                if not subset.empty:
                    subset["diff_days"] = (subset["to Fecha"] - expedition_date).abs()
                    subset = subset.sort_values("diff_days")

            if subset.empty:
                self.logger.debug(
                    "Sin movimiento disponible para %svalor=%s",
                    "" if nearest_date else f"fecha={expedition_date.date()}, ",
                    value,
                )
                return None

            chosen_index = subset.index[0]
            reserved_indices.add(chosen_index)
            candidate_indices.append(chosen_index)

        return candidate_indices

    def _second_pass(self) -> None:
        """
        Reintenta conciliar las facturas que no pudieron asociarse en la
        primera pasada. A diferencia de antes, aquí se prueban TODAS las
        hipótesis originales (candidate_value_lists), en el mismo orden
        de prioridad de la primera pasada, con nearest_date=True. No se
        limita a una única hipótesis "recordada": se reconstruye la
        búsqueda completa sobre todas las opciones disponibles.
        """
        self.logger.info(
            "Iniciando segunda pasada sobre %d factura(s) sin resolver...",
            len(self.unresolved_invoices),
        )

        still_unresolved = []

        for entry in self.unresolved_invoices:
            invoice_number = entry["invoice"]
            supplier = entry.get("supplier")

            # Compatibilidad: si por algún motivo no hay
            # candidate_value_lists (entradas antiguas), se cae de
            # vuelta a la única lista disponible.
            candidate_value_lists = entry.get("candidate_value_lists")
            if not candidate_value_lists:
                single_list = entry.get("payment_values", [])
                candidate_value_lists = [single_list] if single_list else []

            if not candidate_value_lists:
                still_unresolved.append(entry)
                continue

            strategy = self.strategies.get(str(supplier))
            if strategy is None:
                still_unresolved.append(entry)
                continue

            expedition_date = strategy.extract_expedition_date(entry.get("text", ""))
            if expedition_date is None:
                still_unresolved.append(entry)
                continue

            resolved = False
            for hypothesis_index, payment_values in enumerate(candidate_value_lists, start=1):
                candidate_indices = self._find_candidate_indices(
                    expedition_date=expedition_date,
                    payment_values=payment_values,
                    nearest_date=True,
                )

                if candidate_indices is not None:
                    for idx in candidate_indices:
                        self.bank_statements.at[idx, "Factura"] = invoice_number

                    self.logger.info(
                        "Factura %s conciliada en segunda pasada "
                        "(hipótesis %d/%d, %d movimiento(s)).",
                        invoice_number, hypothesis_index,
                        len(candidate_value_lists), len(candidate_indices),
                    )
                    resolved = True
                    break

            if not resolved:
                still_unresolved.append(entry)

        self.unresolved_invoices = still_unresolved

    def _remove_resolved_from_unresolved(self) -> None:
        resolved_invoices = set(
            self.bank_statements.loc[
                self.bank_statements["Factura"].notna(), "Factura",
            ]
        )

        self.unresolved_invoices = [
            entry for entry in self.unresolved_invoices
            if entry["invoice"] not in resolved_invoices
        ]