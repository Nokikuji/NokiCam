@echo off
setlocal enableextensions enabledelayedexpansion
cd /d "%~dp0"
color 0A

:: ============================================================
::  NokiCam Windows Installer
::  Double-click this file to install NokiCam automatically.
:: ============================================================

echo.
echo  ============================================
echo.
echo       NokiCam  --  Windows Installer
echo       Webcam Fisheye Correction + 50mm Sim
echo.
echo  ============================================
echo.
echo  Welcome! This installer will set up NokiCam on your PC.
echo  No technical knowledge needed -- just follow the prompts.
echo.
echo  What will be installed:
echo    - Python 3.11 (if not already present)
echo    - A self-contained virtual environment (.venv\)
echo    - OpenCV, NumPy, PyQt5, MediaPipe, and pyvirtualcam
echo    - Desktop and Start Menu shortcuts
echo.
echo  Installation folder: %~dp0
echo.
pause

:: ============================================================
::  STEP 1 -- Check Python 3.10+
:: ============================================================
echo.
echo [1/7] Checking Python version...
echo.

set PYTHON_EXE=
set PYTHON_OK=0

:: Try 'python' first
python --version >nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=2" %%V in ('python --version 2^>^&1') do set PY_VER=%%V
    call :check_version "%PY_VER%"
    if !VERSION_OK! == 1 (
        set PYTHON_EXE=python
        set PYTHON_OK=1
    )
)

:: Try 'python3' if 'python' didn't work
if "%PYTHON_OK%" == "0" (
    python3 --version >nul 2>&1
    if %errorlevel% == 0 (
        for /f "tokens=2" %%V in ('python3 --version 2^>^&1') do set PY_VER=%%V
        call :check_version "%PY_VER%"
        if !VERSION_OK! == 1 (
            set PYTHON_EXE=python3
            set PYTHON_OK=1
        )
    )
)

:: Python not found or version too old -- try winget install
if "%PYTHON_OK%" == "0" (
    echo  Python 3.10+ not found. Attempting automatic install via winget...
    echo  (Requires Windows 10 version 1709 or later)
    echo.
    winget install --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo.
        color 0C
        echo  [!] winget installation failed.
        echo.
        echo  Please install Python manually:
        echo    1. Open this link in your browser:
        echo       https://www.python.org/downloads/
        echo    2. Download Python 3.11 (or later) for Windows.
        echo    3. Run the installer.
        echo       IMPORTANT: Check "Add Python to PATH" on the first screen!
        echo    4. Re-run this setup file after installing.
        echo.
        start https://www.python.org/downloads/
        goto :fatal_pause
    )

    :: Refresh PATH so newly installed python is found
    :: Re-check after install
    python --version >nul 2>&1
    if %errorlevel% == 0 (
        for /f "tokens=2" %%V in ('python --version 2^>^&1') do set PY_VER=%%V
        call :check_version "%PY_VER%"
        if !VERSION_OK! == 1 (
            set PYTHON_EXE=python
            set PYTHON_OK=1
        )
    )

    if "%PYTHON_OK%" == "0" (
        color 0C
        echo.
        echo  [!] Python was installed but could not be detected automatically.
        echo      This usually means the PATH was not updated yet.
        echo.
        echo  Please close this window and re-run setup_windows.bat.
        goto :fatal_pause
    )
)

echo  [OK] Python %PY_VER% found  (%PYTHON_EXE%)

:: ============================================================
::  STEP 2 -- Create virtual environment
:: ============================================================
echo.
echo [2/7] Creating virtual environment at .venv\ ...
echo.

if exist ".venv\Scripts\python.exe" (
    echo  [OK] Virtual environment already exists, skipping creation.
) else (
    %PYTHON_EXE% -m venv .venv
    if %errorlevel% neq 0 (
        color 0C
        echo.
        echo  [!] Failed to create virtual environment.
        echo      Make sure Python was installed with the standard library included.
        goto :fatal_pause
    )
    echo  [OK] Virtual environment created.
)

:: ============================================================
::  STEP 3 -- Upgrade pip inside venv
:: ============================================================
echo.
echo [3/7] Upgrading pip...
echo.

.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [!] Failed to upgrade pip. Check your internet connection and try again.
    goto :fatal_pause
)
echo  [OK] pip is up to date.

:: ============================================================
::  STEP 4 -- Install core dependencies
:: ============================================================
echo.
echo [4/7] Installing core dependencies (this may take a few minutes)...
echo.

.venv\Scripts\python.exe -m pip install -r requirements_windows.txt
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [!] Dependency installation failed.
    echo.
    echo  Common causes:
    echo    - No internet connection
    echo    - A package failed to build (try running as Administrator)
    echo    - Antivirus blocking pip
    echo.
    echo  You can retry by running this installer again.
    goto :fatal_pause
)
echo.
echo  [OK] Core dependencies installed.

:: ============================================================
::  STEP 5 -- Install pyvirtualcam with Windows mediafoundation
:: ============================================================
echo.
echo [5/7] Installing pyvirtualcam (Windows virtual camera support)...
echo.

.venv\Scripts\python.exe -m pip install "pyvirtualcam[mediafoundation]"
if %errorlevel% neq 0 (
    color 0E
    echo.
    echo  [!] pyvirtualcam installation failed.
    echo      The virtual camera feature will NOT work.
    echo.
    echo  To fix this manually later, run:
    echo    .venv\Scripts\pip install "pyvirtualcam[mediafoundation]"
    echo.
    echo  Continuing setup anyway...
    echo.
    color 0A
) else (
    :: Quick sanity check
    .venv\Scripts\python.exe -c "import pyvirtualcam; print('  pyvirtualcam OK')" 2>nul
    if %errorlevel% neq 0 (
        color 0E
        echo  [!] pyvirtualcam installed but import failed. Virtual camera may not work.
        color 0A
    ) else (
        echo  [OK] pyvirtualcam with mediafoundation support is ready.
    )
)

:: ============================================================
::  STEP 6 -- Create Desktop shortcut
:: ============================================================
echo.
echo [6/7] Creating Desktop shortcut...
echo.

set INSTALL_DIR=%~dp0
:: Remove trailing backslash to avoid double-backslash in paths
if "%INSTALL_DIR:~-1%" == "\" set INSTALL_DIR=%INSTALL_DIR:~0,-1%

set VENV_PYTHONW=%INSTALL_DIR%\.venv\Scripts\pythonw.exe
set MAIN_SCRIPT=%INSTALL_DIR%\main.py
set DESKTOP=%USERPROFILE%\Desktop

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; ^
     $sc = $ws.CreateShortcut('%DESKTOP%\NokiCam.lnk'); ^
     $sc.TargetPath = '%VENV_PYTHONW%'; ^
     $sc.Arguments = 'main.py'; ^
     $sc.WorkingDirectory = '%INSTALL_DIR%'; ^
     $sc.IconLocation = '%SystemRoot%\System32\shell32.dll,300'; ^
     $sc.Description = 'NokiCam - Webcam Fisheye Correction'; ^
     $sc.Save()"

if %errorlevel% neq 0 (
    color 0E
    echo  [!] Could not create Desktop shortcut (non-fatal).
    echo      You can launch NokiCam manually by running:
    echo        .venv\Scripts\pythonw.exe main.py
    echo.
    color 0A
) else (
    echo  [OK] Desktop shortcut created: %DESKTOP%\NokiCam.lnk
)

:: ============================================================
::  STEP 7 -- Create Start Menu shortcut
:: ============================================================
echo.
echo [7/7] Creating Start Menu shortcut...
echo.

set STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; ^
     $sc = $ws.CreateShortcut('%STARTMENU%\NokiCam.lnk'); ^
     $sc.TargetPath = '%VENV_PYTHONW%'; ^
     $sc.Arguments = 'main.py'; ^
     $sc.WorkingDirectory = '%INSTALL_DIR%'; ^
     $sc.IconLocation = '%SystemRoot%\System32\shell32.dll,300'; ^
     $sc.Description = 'NokiCam - Webcam Fisheye Correction'; ^
     $sc.Save()"

if %errorlevel% neq 0 (
    color 0E
    echo  [!] Could not create Start Menu shortcut (non-fatal).
    color 0A
) else (
    echo  [OK] Start Menu shortcut created.
)

:: ============================================================
::  SUCCESS
:: ============================================================
echo.
color 0A
echo  ##############################################
echo  #                                            #
echo  #   Installation complete!                   #
echo  #                                            #
echo  ##############################################
echo.
echo  What to do next:
echo.
echo  1. FIRST TIME SETUP (lens calibration):
echo       Print a 9x6 checkerboard pattern, then run:
echo         .venv\Scripts\python.exe calibrate.py
echo       This saves your camera's distortion profile to config.json.
echo.
echo       -OR- skip calibration by editing config.json manually
echo       with estimated values (see CLAUDE.md for details).
echo.
echo  2. LAUNCH NokiCam:
echo       Double-click the "NokiCam" shortcut on your Desktop.
echo.
echo  3. SELECT VIRTUAL CAMERA in Zoom / Google Meet / OBS:
echo       Choose "NokiCam Virtual Camera" as your camera source.
echo.
echo  Enjoy a natural, flattering 50mm-equivalent webcam view!
echo.
pause
exit /b 0

:: ============================================================
::  SUBROUTINE: check_version
::  Arg 1: version string like "3.11.2"
::  Sets VERSION_OK=1 if major>=3 and minor>=10
:: ============================================================
:check_version
setlocal enabledelayedexpansion
set VER_STR=%~1
:: Strip leading 'v' if present
if "%VER_STR:~0,1%" == "v" set VER_STR=%VER_STR:~1%

for /f "tokens=1,2 delims=." %%A in ("%VER_STR%") do (
    set VER_MAJOR=%%A
    set VER_MINOR=%%B
)

set /a CHECK=0
if !VER_MAJOR! GTR 3 set /a CHECK=1
if !VER_MAJOR! EQU 3 if !VER_MINOR! GEQ 10 set /a CHECK=1

endlocal & set VERSION_OK=%CHECK%
exit /b 0

:: ============================================================
::  LABEL: fatal error -- show message and wait before closing
:: ============================================================
:fatal_pause
echo.
echo  Setup did not complete successfully.
echo  Read the message above, fix the issue, then re-run setup_windows.bat.
echo.
pause
exit /b 1
