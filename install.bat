@echo off
rem One-time setup for AURA voice control: Python environment, the llama.cpp runtime, the models and the voice.
rem
rem   install.bat                 the default model (aura-qwen-0.5b, 0.5 GB)
rem   install.bat 1.5b            also the larger fine-tuned model (aura-qwen-1.5b, 1.6 GB)
rem   install.bat llama           also the stock Llama 3.2 3B (llama3.2-3b, 2 GB)
rem   install.bat 1.5b llama      both
rem
rem Choose a non-default model with the AURA_SLM_MODEL environment variable.
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv || python -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install -r automation\requirements.txt || goto :fail

set "DATA=%LOCALAPPDATA%\AURA"
set "MODELS=%DATA%\models"
if not exist "%MODELS%" mkdir "%MODELS%"

rem llama.cpp runs the model. The Vulkan build uses any GPU brand; AURA starts and stops it itself.
set "LLAMA=https://github.com/ggml-org/llama.cpp/releases/download/b11583/llama-b11583-bin-win-vulkan-x64.zip"
if not exist "%DATA%\llama.cpp\llama-server.exe" (
    if not exist "%DATA%\llama.cpp" mkdir "%DATA%\llama.cpp"
    curl -L --fail -o "%DATA%\llama.cpp\llama.zip" %LLAMA% || goto :fail
    tar -xf "%DATA%\llama.cpp\llama.zip" -C "%DATA%\llama.cpp" || goto :fail
    del "%DATA%\llama.cpp\llama.zip"
)

set "RELEASE=https://github.com/Somansh1/aura-models/releases/download/models-v1"
call :fetch "%MODELS%\aura-qwen-0.5B-q8_0.gguf" %RELEASE%/aura-qwen-0.5B-q8_0.gguf || goto :fail
for %%A in (%*) do (
    if /i "%%A"=="1.5b" call :fetch "%MODELS%\aura-qwen-1.5B-q8_0.gguf" %RELEASE%/aura-qwen-1.5B-q8_0.gguf || goto :fail
    if /i "%%A"=="llama" call :fetch "%MODELS%\llama3.2-3b.gguf" https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf || goto :fail
)

rem Natural voice (Kokoro). Without these files AURA falls back to the built-in Windows voice.
set "KOKORO=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
call :fetch "%MODELS%\kokoro-v1.0.onnx" %KOKORO%/kokoro-v1.0.onnx || goto :fail
call :fetch "%MODELS%\voices-v1.0.bin" %KOKORO%/voices-v1.0.bin || goto :fail

echo.
echo Done. Start AURA in the tray:   .venv\Scripts\pythonw.exe -m automation.mcp.tray
echo Start it with Windows:         .venv\Scripts\python.exe -m automation.mcp.tray --startup on
exit /b 0

:fetch
rem Downloads %2 to %1 unless it is already there; a failed download leaves no partial file behind.
if exist %1 exit /b 0
curl -L --fail -o "%~1.part" %2 || (del "%~1.part" 2>nul & exit /b 1)
move /y "%~1.part" %1 >nul
exit /b 0

:fail
echo Setup failed; see the message above.
exit /b 1
