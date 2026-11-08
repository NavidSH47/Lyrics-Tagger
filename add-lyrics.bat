@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

REM ---- Optional Genius credentials: copy genius.env.example to genius.env
REM ---- and fill in your Client ID / Secret (or GENIUS_ACCESS_TOKEN).
if exist "genius.env" call "genius.env"

REM ---- venv: auto-create + auto-install deps (all single-line ifs, no blocks)
if exist "venv\Scripts\python.exe" goto have_venv
echo [SETUP] Creating virtual environment...
python -m venv venv
if errorlevel 1 goto python_err
:have_venv
set "PY=%~dp0venv\Scripts\python.exe"
"%PY%" -c "import requests, mutagen, bs4" >nul 2>&1
if errorlevel 1 goto install_deps
goto after_setup
:install_deps
echo [SETUP] Installing dependencies on first run...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto setup_err
:after_setup

REM ---- parse args: /auto skips menu and runs directly using environment settings
if "%~1"=="/auto" (
    set "AUTO_MODE=1"
    shift
)

REM ---- initial folder: from command line (%1) or keep existing TARGET if already set
if not "%~1"=="" set "TARGET=%~1"

REM ---- filter defaults (keep if already defined by environment)
if not defined F_ALBUM set "F_ALBUM="
if not defined F_ARTIST set "F_ARTIST="
if not defined F_TITLE set "F_TITLE="
if not defined F_YEAR set "F_YEAR="
if not defined F_GENRE set "F_GENRE="
if not defined F_PROVIDER set "F_PROVIDER=auto"
if not defined F_EXT set "F_EXT="
if not defined F_LRC set "F_LRC="
if not defined F_WORKERS set "F_WORKERS="

if defined AUTO_MODE goto run

REM ---- simple loop using choice.exe (works with real console)
:top
echo ================================================
echo    lyrify - batch lyrics for your music
echo ================================================
echo.
echo    Folder   : !TARGET!
echo    Album    : !F_ALBUM!       Artist : !F_ARTIST!
echo    Title    : !F_TITLE!       Year   : !F_YEAR!
echo    Genre    : !F_GENRE!
echo    Provider : !F_PROVIDER!    Ext    : !F_EXT!
echo    Save .LRC: !F_LRC!         Workers: !F_WORKERS!
echo.
echo    [1] Album      [2] Artist     [3] Title
echo    [4] Year       [5] Genre      [6] Provider
echo    [7] Extensions [8] Folder     [9] Save .LRC
echo    [R] Run now    [Q] Quit
echo.
choice /C 123456789RQ /N /M "Choice: "
set "CHOICE=%ERRORLEVEL%"
if %CHOICE%==1  set "F_ALBUM=" & set /p "F_ALBUM=Album filter, Enter for none: " & goto top
if %CHOICE%==2  set "F_ARTIST=" & set /p "F_ARTIST=Artist filter, Enter for none: " & goto top
if %CHOICE%==3  set "F_TITLE=" & set /p "F_TITLE=Title filter, Enter for none: " & goto top
if %CHOICE%==4  set "F_YEAR=" & set /p "F_YEAR=Year filter, Enter for none: " & goto top
if %CHOICE%==5  set "F_GENRE=" & set /p "F_GENRE=Genre filter, Enter for none: " & goto top
if %CHOICE%==6  echo    Provider: auto / lrclib / genius / lyricsovh / search & set "F_PROVIDER=auto" & set /p "F_PROVIDER=Provider: " & goto top
if %CHOICE%==7  set "F_EXT=" & set /p "F_EXT=Extensions like .mp3 .flac, Enter for all: " & goto top
if %CHOICE%==8  set "TARGET=" & set /p "TARGET=Music folder path, Enter for none: " & goto top
if %CHOICE%==9  if "!F_LRC!"=="" (set "F_LRC=yes") else (set "F_LRC=") & goto top
if %CHOICE%==10 goto run
if %CHOICE%==11 goto bye
goto top

:run
if defined TARGET goto target_ok
if defined AUTO_MODE goto bye
set "TARGET=" & set /p "TARGET=Music folder path: "
:target_ok
if exist "!TARGET!" goto target_exists
echo [ERROR] Folder not found: !TARGET!
if defined AUTO_MODE goto bye
pause
goto top
:target_exists

if not defined AUTO_MODE (
    set "FORCE="
    set /p "ANS=Rewrite lyrics already in files? [y/N]: "
    if /i "!ANS!"=="y" set "FORCE=--force"
    if "!F_LRC!"=="" (
        set /p "ANS_LRC=Also save companion .lrc files (for mobile players)? [y/N]: "
        if /i "!ANS_LRC!"=="y" set "F_LRC=yes"
    )
)

set "EXTRA="
if defined F_ALBUM set "EXTRA=!EXTRA! --album="!F_ALBUM!""
if defined F_ARTIST set "EXTRA=!EXTRA! --artist="!F_ARTIST!""
if defined F_TITLE set "EXTRA=!EXTRA! --title="!F_TITLE!""
if defined F_YEAR set "EXTRA=!EXTRA! --year="!F_YEAR!""
if defined F_GENRE set "EXTRA=!EXTRA! --genre="!F_GENRE!""
if not "!F_PROVIDER!"=="auto" set "EXTRA=!EXTRA! --provider=!F_PROVIDER!"
if defined F_EXT set "EXTRA=!EXTRA! --ext=!F_EXT!"
if defined F_LRC set "EXTRA=!EXTRA! --save-lrc"
if defined F_WORKERS set "EXTRA=!EXTRA! --workers=!F_WORKERS!"

echo.
echo Running: lyrify.py "!TARGET!" !EXTRA! !FORCE!
echo.
"%PY%" lyrify.py "!TARGET!" !EXTRA! !FORCE!
echo.
if not defined AUTO_MODE (
    echo Finished. Back to the menu in a moment...
    pause
    goto top
)
goto bye

:python_err
echo [ERROR] Could not create the Python virtual environment.
echo         Install Python from https://python.org (check "Add to PATH"), then retry.
pause
exit /b 1

:setup_err
echo [ERROR] Could not install dependencies.
pause
exit /b 1

:bye
echo.
echo Bye!
endlocal
exit /b 0