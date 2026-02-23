@echo off
setlocal

set "_PAUSE="
if "%~1"=="" set "_PAUSE=1"

pushd "%~dp0" >nul

powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\release-desktop.ps1" %*
set "_RC=%ERRORLEVEL%"

popd >nul

if not "%_RC%"=="0" (
  echo.
  echo Release script failed with exit code %_RC%.
) else (
  echo.
  echo Release script finished successfully.
)

if defined _PAUSE (
  echo.
  pause
)

exit /b %_RC%
