@echo off
REM ============================================================
REM  Sekali klik: nyalakan Backend (FastAPI) + Frontend (Vite)
REM  Buka dua jendela terpisah. Tutup jendela = matikan servis.
REM ============================================================
cd /d "%~dp0"

REM --- Pastikan backend\.env ada (kalau belum, salin dari contoh) ---
if not exist "backend\.env" (
  copy "backend\.env.example" "backend\.env" >nul
  echo [PENTING] backend\.env baru dibuat dari contoh.
  echo           Isi GEMINI_API_KEY dulu di backend\.env sebelum lanjut!
  echo.
  pause
)

echo Menyalakan BACKEND di http://127.0.0.1:8000 ...
start "Backend - FastAPI" cmd /k "cd /d "%~dp0backend" && python -m pip install -r requirements.txt && python -m uvicorn main:app --reload"

echo Menyalakan FRONTEND di http://127.0.0.1:3000 ...
start "Frontend - Vite" cmd /k "cd /d "%~dp0frontend" && npm install && npm run dev"

echo.
echo Dua jendela sudah dibuka. Tunggu sampai keduanya siap, lalu buka:
echo    http://127.0.0.1:3000
echo.
pause
