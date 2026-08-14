@echo off
setlocal EnableExtensions
title Markov KaiSa
cd /d "%~dp0"

mode con: cols=88 lines=42 >nul 2>nul
color 0F

for /f %%A in ('echo prompt $E^| cmd') do set "ESC=%%A"
set "RST=%ESC%[0m"
set "CB=%ESC%[48;2;232;90;60m"
set "IB=%ESC%[48;2;26;26;26m"
set "TB=%ESC%[48;2;44;74;74m"
set "SB=%ESC%[48;2;217;211;199m"
set "CT=%ESC%[38;2;232;90;60m"
set "WT=%ESC%[38;2;246;241;231m"
set "DT=%ESC%[38;2;120;112;100m"
set "OK=%ESC%[38;2;44;74;74m"
set "ER=%ESC%[38;2;176;58;38m"

cls
echo.
echo   %CB%  %RST% %IB%  %RST% %CB%  %RST% %CB%  %RST% %TB%  %RST% %TB%  %RST% %IB%  %RST%
echo.
echo   %CT%MARKOV KAISA%RST%
echo   %WT%live data   U-max   any rank%RST%
echo   %DT%# # #     # #%RST%
echo.

set "PY="
where py >nul 2>nul
if %errorlevel%==0 set "PY=py -3"
if defined PY goto :have_py
where python >nul 2>nul
if %errorlevel%==0 set "PY=python"
if defined PY goto :have_py

echo   %ER%[X]  Python was not found.%RST%
echo   %DT%     Install Python 3 and run this file again.%RST%
echo.
echo   %CT%Press any key to close...%RST%
pause >nul
exit /b 1

:have_py
set "RANKFILE=%~dp0output\selected_rank.txt"
if exist "%RANKFILE%" del "%RANKFILE%" >nul 2>nul
%PY% markov_kaisa.py --pick-tier
if errorlevel 1 goto :cancelled
if not exist "%RANKFILE%" goto :no_rank
set /p RANK=<"%RANKFILE%"
if not defined RANK goto :no_rank
goto :run_build

:cancelled
echo   %DT%Cancelled.%RST%
echo.
echo   %CT%Press any key to close...%RST%
pause >nul
exit /b 1

:no_rank
echo   %ER%[X]  Rank was not selected.%RST%
echo.
echo   %CT%Press any key to close...%RST%
pause >nul
exit /b 1

:run_build
echo.
echo   %DT%# # #     # #%RST%
echo   %CB% %RST%  %WT%RANK%RST%        %CT%%RANK%%RST%
echo   %IB% %RST%  %WT%FETCH%RST%       live Lolalytics
echo   %CB% %RST%  %WT%SCORE%RST%       Markov U protocol
echo   %TB% %RST%  %WT%GEM%RST%         two hunter item sets
echo   %IB% %RST%  %WT%CHECK%RST%       yesterday on today
echo   %CB% %RST%  %WT%INSTALL%RST%     three League item sets
echo   %DT%#     # # #%RST%
echo.

%PY% markov_kaisa.py --tier %RANK%
set "ERR=%errorlevel%"
echo.

if not "%ERR%"=="0" goto :fail
echo   %CB%  %RST% %CB%  %RST% %CB%  %RST%
echo   %OK%[OK]%RST%  %WT%Markov KaiSa plus two Gem Hunter sets are in the client.%RST%
echo   %DT%Close League fully, reopen, select KaiSa, open Item Sets.%RST%
goto :done

:fail
echo   %IB%  %RST% %ER%[X]%RST%  Build failed. Check the message above.

:done
echo.
echo   %CT%Press any key to close...%RST%
pause >nul
endlocal
exit /b %ERR%
