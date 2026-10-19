@echo off
chcp 65001 >nul
title WF-Auto
cd /d "%~dp0"

if not exist "MFAAvalonia.exe" (
  echo.
  echo  [ERROR] MFAAvalonia.exe not found in this folder.
  echo.
  echo  Please unzip the WHOLE archive first, then double-click this file
  echo  from inside the extracted folder.
  echo.
  pause
  exit /b 1
)

rem ---- MFAAvalonia is a framework-dependent .NET 10 app. A clean Windows
rem ---- has no .NET 10 Desktop Runtime, so the GUI will not start until it
rem ---- is installed. Detect it and offer the bundled installer.
set "HAS_DOTNET10="
for /d %%i in ("%ProgramFiles%\dotnet\shared\Microsoft.WindowsDesktop.App\10.*") do set "HAS_DOTNET10=1"

if not defined HAS_DOTNET10 (
  echo.
  echo  [FIRST RUN] Microsoft .NET 10 Desktop Runtime was not found.
  echo  The GUI cannot start without it.
  echo.
  if exist "DependencySetup_依赖库安装_win.bat" (
    echo  Running the bundled dependency installer now...
    echo.
    call "DependencySetup_依赖库安装_win.bat"
    echo.
    echo  If the installer finished, run this file again.
    pause
    exit /b 1
  ) else (
    echo  Please install ".NET Desktop Runtime 10" from:
    echo    https://dotnet.microsoft.com/download/dotnet/10.0
    echo  then run this file again.
    echo.
    pause
    exit /b 1
  )
)

start "" "MFAAvalonia.exe"
exit /b 0
