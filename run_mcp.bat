@echo off
set PYTHONPATH=%~dp0
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
"%~dp0automation\venv\Scripts\python.exe" mcp_server.py %* 2> mcp_error.log
