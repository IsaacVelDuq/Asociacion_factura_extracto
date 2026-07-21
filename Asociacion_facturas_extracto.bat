@echo off
setlocal

:: Ejecutable en la red
set "NETWORK_EXE=O:\Finanzas\Tesoreria\Automatizaciones\Asociacion facturas con extracto\dist\Asociacion_facturas_extracto.exe"

:: Carpeta local
set "LOCAL_DIR=%LOCALAPPDATA%\Automatización_asociacion_factura_extracto"

:: Ejecutable local
set "LOCAL_EXE=%LOCAL_DIR%\Asociacion_facturas_extracto.exe"

:: Crear la carpeta si no existe
if not exist "%LOCAL_DIR%" mkdir "%LOCAL_DIR%"

:: Copiar si no existe
if not exist "%LOCAL_EXE%" (
    copy "%NETWORK_EXE%" "%LOCAL_EXE%" >nul
)

:: Actualizar si hay una versión más reciente
xcopy "%NETWORK_EXE%" "%LOCAL_EXE%" /D /Y >nul


::==================================================
:: Ejecutar aplicacion
::==================================================

echo.
echo ============================================
echo Ejecutando aplicacion...
echo ============================================
echo.

:: Ejecutar
start "" "%LOCAL_EXE%"

   
