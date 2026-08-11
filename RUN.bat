@echo off
title Markov Kai'Sa
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 markov_kaisa.py
) else (
  python markov_kaisa.py
)

echo.
pause
