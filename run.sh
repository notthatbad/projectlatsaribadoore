#!/usr/bin/env bash
# ============================================================
#  Sekali jalan: nyalakan Backend (FastAPI) + Frontend (Vite)
#  Ctrl+C untuk menghentikan keduanya.
# ============================================================
set -e
cd "$(dirname "$0")"

# --- Pastikan backend/.env ada ---
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "[PENTING] backend/.env baru dibuat dari contoh."
  echo "          Isi GEMINI_API_KEY dulu di backend/.env, lalu jalankan lagi."
  exit 1
fi

PY=python3
command -v $PY >/dev/null 2>&1 || PY=python

echo "==> Menyiapkan backend..."
( cd backend && $PY -m pip install -r requirements.txt )

# Matikan kedua proses saat skrip dihentikan
cleanup() { echo; echo "Menghentikan..."; kill 0; }
trap cleanup INT TERM

echo "==> Menyalakan BACKEND  -> http://127.0.0.1:8000"
( cd backend && $PY -m uvicorn main:app --reload ) &

echo "==> Menyalakan FRONTEND -> http://127.0.0.1:3000"
( cd frontend && npm install && npm run dev ) &

echo
echo "Buka http://127.0.0.1:3000 di browser. Ctrl+C untuk berhenti."
wait
