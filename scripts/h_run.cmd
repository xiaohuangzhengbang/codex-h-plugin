@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 "%~dp0h_run.py" %*
  exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel% equ 0 (
  python "%~dp0h_run.py" %*
  exit /b %errorlevel%
)

echo H requires Python 3.10 or newer. Install Python, then run this command again. 1>&2
exit /b 1
