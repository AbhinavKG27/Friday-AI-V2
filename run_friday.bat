@echo off
REM ============================================================
REM  Friday AI Assistant – Launch Script
REM ============================================================
call friday_env\Scripts\activate
python main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Friday failed to start. Check the logs folder.
    pause
)
