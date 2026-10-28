@echo off
REM Usage: toycompiler [run|diagnose|symbols|eval|dfa-stats] <args>
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
python -m toyc %*
exit /b %ERRORLEVEL%
