@echo off
REM ============================================================
REM  Friday AI Assistant – Windows Setup Script
REM  Run this once to set up the environment
REM ============================================================

echo.
echo  ◈  Friday AI Assistant – Setup
echo  ===============================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ from python.org
    pause
    exit /b 1
)

echo [OK] Python found
python --version

echo.
echo [1/3] Upgrading pip...
python -m pip install --upgrade pip

echo.
echo [2/3] Installing core dependencies...
pip install SpeechRecognition psutil Pillow

echo.
echo [3/3] Installing PyAudio...
pip install pyaudio
if errorlevel 1 (
    echo.
    echo [WARN] PyAudio install failed. Try manually:
    echo        pip install pipwin
    echo        pipwin install pyaudio
    echo.
    echo  OR download the wheel from:
    echo  https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
)

echo.
echo ============================================================
echo  Setup complete!
echo.
echo  To run Friday:
echo    python main.py
echo.
echo  Optional: Install wake word support
echo    1. Get a free API key at: https://console.picovoice.ai/
echo    2. Add it to friday_config.json as "porcupine_access_key"
echo    3. pip install pvporcupine
echo ============================================================
echo.
pause
