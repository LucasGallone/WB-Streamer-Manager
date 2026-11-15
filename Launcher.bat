@echo off
chcp 65001 >nul
cd /d "%~dp0"
title WB-Streamer Manager - Launcher

set "IS_FR=0"
for /f "tokens=3" %%A in ('reg query "HKCU\Control Panel\International" /v LocaleName 2^>nul') do (
    set "USER_LOCALE=%%A"
)
if defined USER_LOCALE (
    if /i "%USER_LOCALE:~0,2%"=="fr" set "IS_FR=1"
) else (
    for /f "tokens=3" %%A in ('reg query "HKCU\Control Panel\International" /v sLanguage 2^>nul') do (
        set "USER_SLANG=%%A"
    )
    if defined USER_SLANG (
        if /i "%USER_SLANG:~0,2%"=="fr" set "IS_FR=1"
    )
)

if "%IS_FR%"=="1" (
    echo =====================================================
    echo    PRÉPARATION DU MANAGER ET VÉRIFICATION REQUISE
    echo =====================================================
    echo.
    echo Vérification des fichiers requis... et si manquants, installation des dépendances.
    echo ^(Cette étape peut prendre quelques instants lors du tout premier lancement.^)
    echo.
) else (
    echo ======================================================
    echo    PREPARING THE MANAGER AND VERIFYING REQUIREMENTS
    echo ======================================================
    echo.
    echo Verification of required files... and if missing, installation of dependencies.
    echo ^(This step may take a few moments when launching for the first time.^)
    echo.
)

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    if "%IS_FR%"=="1" (
        echo [ERREUR] Python n'est pas installé ou est manquant au PATH Windows.
        echo Veuillez installer Python ^(Version 3.10 ou supérieure^) en vous assurant de cocher "Add Python to PATH" lors de l'installation.
    ) else (
        echo [ERROR] Python is not installed or not added to the Windows PATH.
        echo Please install Python ^(Version 3.10 or newer^) and make sure to check "Add Python to PATH" in the setup wizard.
    )
    echo.
    pause
    exit /b
)

for /f "delims=" %%V in ('python --version 2^>^&1') do set "PY_VER=%%V"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    if "%IS_FR%"=="1" (
        echo [ERREUR] Version de Python incompatible détectée ^(%PY_VER%^).
        echo Veuillez installer Python ^(Version 3.10 ou supérieure^) en vous assurant de cocher "Add Python to PATH" lors de l'installation.
    ) else (
        echo [ERROR] Incompatible Python version detected ^(%PY_VER%^).
        echo Please install Python ^(Version 3.10 or newer^) and make sure to check "Add Python to PATH" in the setup wizard.
    )
    echo.
    pause
    exit /b
)

python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    if "%IS_FR%"=="1" (
        echo [ERREUR] Le module Tkinter ^(interface graphique^) est manquant dans votre installation Python.
        echo Veuillez réinstaller Python en cochant l'option "tcl/tk and IDLE".
    ) else (
        echo [ERROR] The Tkinter module ^(GUI^) is missing from your Python installation.
        echo Please reinstall Python and make sure "tcl/tk and IDLE" is checked.
    )
    echo.
    pause
    exit /b
)

python -c "import re; from importlib.metadata import version; v = lambda p: tuple(map(int, re.match(r'(\d+)\.(\d+)', version(p)).groups())); import flask, werkzeug, psutil; assert (2, 3) <= v('flask') < (4, 0) and (2, 3) <= v('werkzeug') < (4, 0) and (5, 9) <= v('psutil') < (8, 0)" >nul 2>&1
if errorlevel 1 (
    python -m pip install --quiet --disable-pip-version-check "flask>=3.0.0,<4.0.0" "werkzeug>=3.0.0,<4.0.0" "psutil>=5.9.0,<8.0.0"
    if errorlevel 1 (
        echo.
        if "%IS_FR%"=="1" (
            echo [ERREUR] Échec de l'installation des dépendances requises.
            echo Vérifiez votre connexion Internet ainsi que l'outil pip, puis réessayez.
        ) else (
            echo [ERROR] Failed to install required dependencies.
            echo Please check your Internet connection and pip installation, then try again.
        )
        echo.
        pause
        exit /b
    )
)

if "%IS_FR%"=="1" (
    echo.
    echo ==========================================================
    echo    LANCEMENT DU MANAGER EN COURS... VEUILLEZ PATIENTER.
    echo ==========================================================
    echo.
    echo IMPORTANT : Vous devez garder ce terminal ouvert, sinon le manager se fermera !
    echo.
) else (
    echo.
    echo ================================================
    echo    MANAGER LAUNCH IN PROGRESS... PLEASE WAIT.
    echo ================================================
    echo.
    echo IMPORTANT: You must keep this terminal open, otherwise the manager will close!
    echo.
)

python manager.py

echo.
pause