@echo off
rem One-time setup for AURA voice control: Python environment, Ollama, and the local model.
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv || python -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install -r automation\requirements.txt || goto :fail

where ollama >nul 2>nul || if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    winget install -e --id Ollama.Ollama || goto :fail
)
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
where ollama >nul 2>nul && set "OLLAMA=ollama"
"%OLLAMA%" pull llama3.2:3b || goto :fail

rem Natural voice (Kokoro). Without these files AURA falls back to the built-in Windows voice.
set "MODELS=%LOCALAPPDATA%\AURA\models"
set "KOKORO=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
if not exist "%MODELS%" mkdir "%MODELS%"
if not exist "%MODELS%\kokoro-v1.0.onnx" curl -L -o "%MODELS%\kokoro-v1.0.onnx" %KOKORO%/kokoro-v1.0.onnx || goto :fail
if not exist "%MODELS%\voices-v1.0.bin" curl -L -o "%MODELS%\voices-v1.0.bin" %KOKORO%/voices-v1.0.bin || goto :fail

echo.
echo Done. Start AURA in the tray:   .venv\Scripts\pythonw.exe -m automation.mcp.tray
echo Start it with Windows:         .venv\Scripts\python.exe -m automation.mcp.tray --startup on
exit /b 0

:fail
echo Setup failed; see the message above.
exit /b 1
