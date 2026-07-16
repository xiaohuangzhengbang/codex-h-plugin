@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if exist "%~dp0..\runtime\h_launcher.exe" (
  "%~dp0..\runtime\h_launcher.exe" %*
  exit /b %errorlevel%
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0h_bootstrap.ps1" %*
exit /b %errorlevel%
