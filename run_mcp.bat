@echo off
set PYTHONPATH=E:\mycodes\AURA
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
E:\mycodes\AURA\automation\venv\Scripts\python.exe -m automation.mcp %* 2> mcp_error.log
