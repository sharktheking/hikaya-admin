@echo off
cd /d "%~dp0"

set PYTHON_CMD=C:\Users\SHARK\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PYTHON_CMD%" set PYTHON_CMD=python

echo Killing old processes on port 8080...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080 " ^| findstr LISTENING') do (
  taskkill /f /pid %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo Installing requirements...
"%PYTHON_CMD%" -m pip install -q flask requests gunicorn 2>nul

echo Starting admin server...
start /MIN "hikaya-admin" "%PYTHON_CMD%" server.py
timeout /t 3 /nobreak >nul

echo.
echo ============================================
echo   Admin Panel: http://localhost:8080
echo ============================================
echo   Press Ctrl+C in the terminal or close
echo   this window to stop the server.
echo ============================================
echo.
timeout /t 2 /nobreak >nul
start http://localhost:8080
