@echo off
setlocal EnableExtensions
title Markov KaiSa
cd /d "%~dp0"

rem ============================================================
rem  RANK: silver  (default)    or    gold
rem  Change the value below when you promote to Gold.
rem ============================================================
set "RANK=silver"

mode con: cols=88 lines=32 >nul 2>nul
color 0B

for /f %%A in ('echo prompt $E^| cmd') do set "ESC=%%A"
set "RST=%ESC%[0m"
set "DIM=%ESC%[38;5;245m"
set "GOLD=%ESC%[38;5;220m"
set "CYAN=%ESC%[38;5;51m"
set "PINK=%ESC%[38;5;213m"
set "GREEN=%ESC%[38;5;82m"
set "RED=%ESC%[38;5;203m"
set "WHITE=%ESC%[97m"

if /i "%RANK%"=="gold" goto :rank_gold
set "RANK=silver"
set "RANK_LABEL=SILVER"
goto :banner

:rank_gold
set "RANK=gold"
set "RANK_LABEL=GOLD"

:banner
cls
echo.
echo %GOLD%  ========================================================================%RST%
echo %GOLD%                                                                          %RST%
echo %PINK%      M A R K O V      K A I ' S A%RST%
echo %WHITE%              %RANK_LABEL%   EUW%RST%
echo %DIM%         live patch  -  actually-built  -  U-max%RST%
echo %GOLD%                                                                          %RST%
echo %GOLD%  ========================================================================%RST%
echo.
echo %DIM%  ------------------------------------------------------------------------%RST%
echo   %CYAN%-%RST%  %WHITE%Rank filter:%RST% %GOLD%%RANK%%RST%  %DIM%(edit RANK= at the top of this file)%RST%
echo   %CYAN%-%RST%  %WHITE%Reading live Lolalytics data%RST%
echo   %CYAN%-%RST%  %WHITE%Scoring builds with the Markov protocol%RST%
echo   %CYAN%-%RST%  %WHITE%Validating yesterday's pick on today's data%RST%
echo   %CYAN%-%RST%  %WHITE%Installing the item set into League%RST%
echo %DIM%  ------------------------------------------------------------------------%RST%
echo.

set "PY="
where py >nul 2>nul
if %errorlevel%==0 set "PY=py -3"
if defined PY goto :have_py
where python >nul 2>nul
if %errorlevel%==0 set "PY=python"
if defined PY goto :have_py

echo   %RED%[X]  Python was not found.%RST%
echo   %DIM%     Install Python 3 and run this file again.%RST%
echo.
echo   %GOLD%Press any key to close...%RST%
pause >nul
exit /b 1

:have_py
%PY% markov_kaisa.py --tier %RANK%
set "ERR=%errorlevel%"
echo.

if not "%ERR%"=="0" goto :fail
echo %GREEN%  ========================================================================%RST%
echo %GREEN%   [OK]  Markov KaiSa is ready in the League client.%RST%
echo %GREEN%  ========================================================================%RST%
echo   %DIM%Open League and select KaiSa to use the item set.%RST%
goto :done

:fail
echo %RED%  ========================================================================%RST%
echo %RED%   [X]  Build failed. Check the message above.%RST%
echo %RED%  ========================================================================%RST%

:done
echo.
echo   %GOLD%Press any key to close...%RST%
pause >nul
endlocal
exit /b %ERR%
