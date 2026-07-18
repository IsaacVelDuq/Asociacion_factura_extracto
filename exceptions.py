"""
Custom exceptions module.
Define excepciones específicas para diferenciar los tipos de fallo
durante el proceso de scraping.
"""


class ScraperBaseException(Exception):
    """Excepción base de la que heredan todas las excepciones del scraper."""
    pass


class LoginError(ScraperBaseException):
    """Se lanza cuando el login en Cronos falla."""
    pass


class ElementNotFoundError(ScraperBaseException):
    """Se lanza cuando no se encuentra un elemento esperado en la página."""
    pass


class NavigationError(ScraperBaseException):
    """Se lanza cuando falla la navegación hacia una URL."""
    pass


class DataExtractionError(ScraperBaseException):
    """Se lanza cuando falla la extracción de datos de la página."""
    pass
