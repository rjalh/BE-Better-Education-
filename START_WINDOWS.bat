@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if errorlevel 1 pause & exit /b 1
echo Open http://localhost:8000
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
