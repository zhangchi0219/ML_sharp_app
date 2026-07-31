@echo off
rem ---------------------------------------------------------------------------
rem  Launch the SHARP desktop app (with pre-flight frontend build check).
rem    "Qi Dong SHARP.bat" -Rebuild   forces a frontend rebuild.
rem
rem  KEEP THIS FILE PURE ASCII.
rem  cmd.exe parses a .bat by byte offset using the current code page. A non-ASCII
rem  character (or a `chcp` switch) shifts that offset and cmd starts executing the
rem  middle of later lines -- comments get run as commands and the file breaks.
rem  All human-readable Chinese output belongs in desktop.ps1, not here.
rem ---------------------------------------------------------------------------
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\desktop.ps1" %*

rem Pause on failure so the error stays readable when this file is double-clicked
rem (otherwise the console window closes instantly and the message is lost).
if errorlevel 1 (
    echo.
    echo [FAILED] See the error above.
    pause
)
