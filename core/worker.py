
import pandas as pd
import os 
from logger_setup import get_logger
from scrapers.cronos_scraper import CronosScraper
from utils.bank_statement_invoice_matcher import (
    InvoiceBankReconciler,
    PurchaseGroupingStrategy,
)
from utils.excel_formatter import ExcelFormatter
from utils.pdf_bank_statements import PDFMovementsExtractor

from core.execution_controller import ExecutionController
from core.params import (
    CASE_EXITO,
    CASE_NUMBERS,
    ScraperParams,
)

logger = get_logger(__name__)


def add_subtotal_total(df, columna_valor="Valor", columna_4x1000="4x1000"):
    """
    Agrega filas de SUBTOTAL y TOTAL al final del DataFrame.

    SUBTOTAL = Suma de Valor
    4x1000 SUBTOTAL = Suma de 4x1000
    TOTAL = SUBTOTAL + 4x1000 SUBTOTAL
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    suma_valor = df[columna_valor].sum()
    suma_4x1000 = df[columna_4x1000].sum() if columna_4x1000 in df.columns else 0
    total_general = suma_valor + suma_4x1000

    fila_subtotal = {col: "" for col in df.columns}
    fila_subtotal["Descripción"] = "SUBTOTAL"
    fila_subtotal[columna_valor] = suma_valor
    if columna_4x1000 in df.columns:
        fila_subtotal[columna_4x1000] = suma_4x1000

    fila_total = {col: "" for col in df.columns}
    fila_total["Descripción"] = "TOTAL"
    fila_total[columna_valor] = total_general
    if columna_4x1000 in df.columns:
        fila_total[columna_4x1000] = ""

    df = pd.concat(
        [df, pd.DataFrame([fila_subtotal]), pd.DataFrame([fila_total])],
        ignore_index=True,
    )

    return df



def execute_scraper_flow(params: ScraperParams, execution_controller: ExecutionController) -> None:
    """Ejecuta el flujo completo de scraping/conciliación.

    No captura sus propias excepciones: `ScraperBaseException` o cualquier
    otra excepción se propagan para que quien la invoque (el punto de
    entrada del proceso) decida cómo reportarlas.
    """
    p = params
    global PERIOD
    PERIOD = PDFMovementsExtractor().extract_period(p.bank_statement_path)
    filename ="LEGALIZACION_" + str(PERIOD) + "_" + str(p.card_last_digits) + ".xlsx"
    output_path = os.path.join(p.output_dir, filename)

    with CronosScraper(headless=False) as scraper:
        logger.info("Iniciando sesión en Cronos, esperando login manual...")
        scraper.login()

        # Punto de pausa: bloquea la ejecución hasta que el usuario haga
        # clic en "Proceder" en la interfaz (ya autenticado).
        logger.info(
            "Esperando confirmación del usuario para continuar "
            "(login/captcha resuelto manualmente)."
        )
        execution_controller.pause_and_wait()
        logger.info("Confirmado por el usuario, reanudando ejecución.")

        df_bank_statements = PDFMovementsExtractor().extract_movements(p.bank_statement_path)


        mask = (
            df_bank_statements["Descripción"]
            .str.strip()
            .str.upper()
            .str.contains("COMPRAS|IMP 4XMIL|REVERSIO|PAGO DEBITO AUT", na=False)
        )

        df_bank_statements = df_bank_statements[~mask]
        df_bank_statements["to Fecha"] = pd.to_datetime(df_bank_statements["to Fecha"])

        cols = ["to Fecha", "Descripción", "Valor"]
        df_bank_statements = df_bank_statements[cols]

        dates_to_process = (
            pd.date_range(
                start=df_bank_statements["to Fecha"].min(),
                end=df_bank_statements["to Fecha"].max(),
                freq="D",
            )
            .strftime("%d/%m/%Y")
            .tolist()
        )
        logger.info("Fechas a procesar: %s", dates_to_process)

        scraper.process_all_dates(
            case_number=CASE_NUMBERS,
            dates=dates_to_process,
        )
        invoices_data = scraper.get_invoices_data()

        logger.info("Total de facturas capturadas: %d", len(invoices_data))
        logger.info(
            "Facturas únicas: %s",
            sorted(set(i["invoice"] for i in invoices_data)),
        )
        for i in invoices_data:
            logger.debug("Factura: %s, Fecha: %s", i["invoice"], i["date"])

        logger.info("Flujo de scraping finalizado correctamente.")

    # ============================================================
    # Conciliar facturas contra el extracto bancario
    # ============================================================
    reconciler = InvoiceBankReconciler(
        invoices_data=invoices_data,
        bank_statements=df_bank_statements,
        card_last_digits=p.card_last_digits,
        supplier_strategies={
            CASE_EXITO: PurchaseGroupingStrategy(),
        },
    )
    result, no_result = reconciler.reconcile()

    result["4x1000"] = (result["Valor"] * 0.004).round().astype("Int64")
    result = add_subtotal_total(result, columna_valor="Valor", columna_4x1000="4x1000")

    # ============================================================
    # Exportar a Excel
    # ============================================================
    formatter = ExcelFormatter()

    if result is not None and not result.empty:
        formatter.export(
            df=result,
            excel_path= output_path,
            sheet_name="Movimientos",
            period=PERIOD,
            card_number=p.card_last_digits,
            horizontal=False,
        )
        logger.info("Hoja 'Movimientos' exportada con %d registros", len(result))
    else:
        logger.warning("result está vacío, no se exporta 'Movimientos'")

    if no_result is not None and not no_result.empty:
        formatter.export(
            df=no_result,
            excel_path=output_path,
            sheet_name="Movimientos_Sin_Asociar",
            period=PERIOD,
            card_number=p.card_last_digits,
            horizontal=False,
        )
        logger.info(
            "Hoja 'Movimientos_Sin_Asociar' exportada con %d registros",
            len(no_result),
        )
    else:
        logger.warning("no_result está vacío, no se exporta 'Movimientos_Sin_Asociar'")
