@echo off
setlocal EnableExtensions
title Markov Kai'Sa
cd /d "%~dp0"

mode con: cols=88 lines=36 >nul 2>nul
color 0B
chcp 65001 >nul

for /f %%A in ('echo prompt $E^| cmd') do set "ESC=%%A"

set "C0=%ESC%[0m"
set "DIM=%ESC%[38;5;245m"
set "GOLD=%ESC%[38;5;220m"
set "CYAN=%ESC%[38;5;51m"
set "PINK=%ESC%[38;5;213m"
set "GREEN=%ESC%[38;5;82m"
set "RED=%ESC%[38;5;203m"
set "WHITE=%ESC%[97m"

cls
echo.
echo %GOLD%  ╔══════════════════════════════════════════════════════════════════════════╗%C0%
echo %GOLD%  ║%C0%                                                                          %GOLD%║%C0%
echo %GOLD%  ║%C0%     %PINK%███╗   ███╗ █████╗ ██████╗ ██╗  ██╗ ██████╗ ██╗   ██╗%C0%              %GOLD%║%C0%
echo %GOLD%  ║%C0%     %PINK%████╗ ████║██╔══██╗██╔══██╗██║ ██╔╝██╔═══██╗██║   ██║%C0%              %GOLD%║%C0%
echo %GOLD%  ║%C0%     %CYAN%██╔████╔██║███████║██████╔╝█████╔╝ ██║   ██║██║   ██║%C0%              %GOLD%║%C0%
echo %GOLD%  ║%C0%     %CYAN%██║╚██╔╝██║██╔══██║██╔══██╗██╔═██╗ ██║   ██║╚██╗ ██╔╝%C0%              %GOLD%║%C0%
echo %GOLD%  ║%C0%     %CYAN%██║ ╚═╝ ██║██║  ██║██║  ██║██║  ██╗╚██████╔╝ ╚████╔╝%C0%               %GOLD%║%C0%
echo %GOLD%  ║%C0%     %DIM%╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝   ╚═══╝%C0%                %GOLD%║%C0%
echo %GOLD%  ║%C0%                                                                          %GOLD%║%C0%
echo %GOLD%  ║%C0%              %WHITE%K A I ' S A%C0%   %DIM%·%C0%   %GOLD%S I L V E R   E U W%C0%                    %GOLD%║%C0%
echo %GOLD%  ║%C0%              %DIM%live patch  ·  actually-built  ·  U-max%C0%                   %GOLD%║%C0%
echo %GOLD%  ║%C0%                                                                          %GOLD%║%C0%
echo %GOLD%  ╚══════════════════════════════════════════════════════════════════════════╝%C0%
echo.
echo %DIM%  ────────────────────────────────────────────────────────────────────────────%C0%
echo   %CYAN%▸%C0%  %WHITE%Reading live Lolalytics data%C0%
echo   %CYAN%▸%C0%  %WHITE%Scoring builds with the Markov protocol%C0%
echo   %CYAN%▸%C0%  %WHITE%Installing the item set into League%C0%
echo %DIM%  ────────────────────────────────────────────────────────────────────────────%C0%
echo.

set "PY="
where py >nul 2>nul
if %errorlevel%==0 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if %errorlevel%==0 set "PY=python"
)

if not defined PY (
  echo   %RED%✖  Python was not found.%C0%
  echo   %DIM%   Install Python 3 and run this file again.%C0%
  echo.
  echo   %GOLD%Press any key to close...%C0%
  pause >nul
  exit /b 1
)

%PY% markov_kaisa.py
set "ERR=%errorlevel%"
echo.

if not "%ERR%"=="0" (
  echo %RED%  ╔══════════════════════════════════════════════════════════════════════════╗%C0%
  echo %RED%  ║  ✖  Build failed. Check the message above.                               ║%C0%
  echo %RED%  ╚══════════════════════════════════════════════════════════════════════════╝%C0%
) else (
  echo %GREEN%  ╔══════════════════════════════════════════════════════════════════════════╗%C0%
  echo %GREEN%  ║  ✔  Markov Kai'Sa is ready in the League client.                         ║%C0%
  echo %GREEN%  ╚══════════════════════════════════════════════════════════════════════════╝%C0%
  echo   %DIM%Open League and select Kai'Sa to use the item set.%C0%
)

echo.
echo   %GOLD%Press any key to close...%C0%
pause >nul
endlocal
exit /b %ERR%
