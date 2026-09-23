@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title NEWAPP AI Control Plane

echo ============================================================
echo NEWAPP AI CONTROL PLANE
echo ============================================================
echo Project : %CD%
echo.

set "PYTHON="

if exist "%~dp0.venv\Scripts\python.exe" (
  set "PYTHON=%~dp0.venv\Scripts\python.exe"
  echo [OK] Python: .venv\Scripts\python.exe
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON=py -3"
    echo [OK] Python: Windows py launcher
  ) else (
    where python >nul 2>nul
    if not errorlevel 1 (
      set "PYTHON=python"
      echo [OK] Python: system python
    )
  )
)

if not defined PYTHON (
  echo.
  echo [ERROR] Python was not found.
  echo Create the agent environment with:
  echo   py -3 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements-agent.txt
  set "EXITCODE=9009"
  goto :FINISH
)

if not exist "%~dp0.ai\controller\agent_loop.py" (
  echo.
  echo [ERROR] Agent controller was not found:
  echo   %~dp0.ai\controller\agent_loop.py
  set "EXITCODE=2"
  goto :FINISH
)

echo [OK] Controller: .ai\controller\agent_loop.py
echo.

if "%~1"=="" (
  echo No command supplied. Starting unattended rolling development.
  echo For a read-only environment check use:
  echo   start_agent.bat preflight
  echo.
  %PYTHON% ".ai\controller\agent_loop.py" run
) else (
  echo Command: %*
  echo.
  %PYTHON% ".ai\controller\agent_loop.py" %*
)

set "EXITCODE=%ERRORLEVEL%"

:FINISH
echo.
echo ------------------------------------------------------------
echo NEWAPP control plane exited with code %EXITCODE%.
echo ------------------------------------------------------------

rem When launched by double-click with no arguments, the rolling agent normally
rem stays alive. If it exits because of a real blocker, keep the window open so
rem the failure remains visible. Explicit command calls stay non-interactive.
if "%~1"=="" (
  echo.
  echo Press any key to close this window.
  pause >nul
)

exit /b %EXITCODE%
