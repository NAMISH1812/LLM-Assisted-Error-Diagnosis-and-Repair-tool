@echo off
REM Usage: toycompiler run <file> [--tokens] [--ast] [--json]
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
python -m toyc %*
exit /b %ERRORLEVEL%
