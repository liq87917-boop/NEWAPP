@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title NEWAPP AI Control Plane

if "%~1"=="" (
  py -3 ".ai\controller\agent_loop.py" preflight
) else (
  py -3 ".ai\controller\agent_loop.py" %*
)

set "EXITCODE=%ERRORLEVEL%"
echo.
echo NEWAPP control plane exited with code %EXITCODE%.
exit /b %EXITCODE%

