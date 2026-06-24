@echo off
REM ============================================================
REM  Duck House Cafe - order till launcher
REM  Double-click this file to start. A browser-ready URL will
REM  appear in the window. Close the window (or press Ctrl+C)
REM  to stop the till.
REM ============================================================
cd /d "%~dp0"
title Duck House Cafe - Order Till

echo Checking requirements...
py -m pip install -q flask 1>nul 2>nul

echo Starting the till...
echo (Leave this window open while you take orders.)
echo.
py app.py

echo.
echo The till has stopped.
pause
