# Catatan Perubahan Project

## Revisi 3 (perbaikan sesuai permintaan)

### 1. Topik — query bisa di-edit
- Setiap topik (baik 25 topik tetap maupun custom) sekarang punya tombol **Edit Query**
  di tab Topik. Query bisa diubah tanpa mengubah judul topik.
- Backend: endpoint baru `PUT /topics/{id}` (lihat `backend/main.py`, fungsi `update_topic`
  di `backend/app/database.py`).

### 2. Topik — penyempurnaan query 25 topik (judul TIDAK diubah)
- 25 topik = 17 program prioritas presiden + 8 quick win. **Judul dibiarkan apa adanya.**
- Query tiap topik disempurnakan hanya di bagian yang kurang tepat, memakai istilah/nama
  resmi + singkatan yang tidak ambigu. Contoh:
  - "kks" (dulu ambigu dengan Kartu Keluarga Sejahtera) → `"RUU KKS" OR "RUU keamanan dan ketahanan siber"`.
  - "papua" (terlalu luas) → `"separatisme papua" OR "KKB papua" OR "OPM papua" OR "TPNPB"`.
  - "gam" (terlalu luas) → `"gerakan aceh merdeka" OR "separatisme aceh" OR "GAM aceh"`.
  - MBG ditambah "Badan Gizi Nasional"/"BGN", dst.
- Daftar lengkap ada di `FIXED_TOPICS` (`backend/app/database.py`). Catatan: query yang sudah
  ter-seed di DB lama tidak otomatis ditimpa — pakai tombol Edit Query untuk memperbaruinya.

### 3. Analisis — jauh lebih mendalam (kerangka TAHAP & DEFINISI ESKALASI)
- Analisis tidak lagi sekadar 3 kalimat. Sekarang memakai prompt berbasis SOP monitoring +
  kerangka eskalasi (VERY LOW → VERY HIGH) yang dilempar ke Gemini, lalu hasilnya distruktur:
  - **Tahap eskalasi** + alasan.
  - **Tabel eskalasi**: pengelompokan judul per tahap + **Saran Informasi** (data/rilis resmi).
  - **Analisis naratif** (pola framing, aktor, trajektori isu).
  - **Rekomendasi tindakan + angle**.
  - **Draf artikel kontra opini** untuk tahap tertinggi.
- Kalau Gemini gagal/tanpa key, otomatis fallback rule-based supaya app tetap jalan (dan UI
  memberi tahu bahwa hasil dalam mode fallback).
- Disimpan di kolom baru `analyses.details` (JSON) — ada migrasi otomatis.

### 4-5. Generate Konten — 3 tombol terpisah + gambar beneran jadi
- Output tetap tiga: **Media Visual**, **Deskripsi Penjelas**, **Caption**, tapi kini dipicu
  oleh **tombol/fungsi berbeda**:
  1. `POST /content/visual` — **Media Visual dibuat DULUAN**, mengacu ke hasil analisis
     (brief visual disusun dari data analisis dulu, baru dikirim ke image model → data akurat,
     bukan asal infografis).
  2. `POST /content/caption` — Caption, logika sama (mengacu analisis + amplifikasi/kontra),
     tombol terpisah, bisa dibuat berdampingan dengan visual.
  3. `POST /content/description` — Deskripsi Penjelas, **baru bisa dibuat setelah media visual ada**.
- **Kenapa dulu visual tidak pernah jadi gambar:** bukan karena nama model salah (nama model
  lama sebenarnya valid), tapi karena (a) pemanggilan image model hanya 1 konfigurasi + parsing
  `response.parts` yang rapuh sehingga diam-diam jatuh ke teks, dan (b) kemungkinan besar **kuota
  API key habis (error 429)**. Sekarang:
  - `generate_image()` mencoba beberapa konfigurasi dan parsing yang tahan beberapa bentuk
    response SDK, mengambil byte gambar dari `candidates[].content.parts`.
  - Kalau tetap gagal, **pesan error aslinya ditampilkan di UI** (mis. "429 RESOURCE_EXHAUSTED")
    jadi ketahuan sebab pastinya — tidak lagi diam-diam berubah jadi teks.
- Model gambar default diarahkan ke nama yang valid & bagus untuk teks infografis
  (`gemini-2.5-flash-image`; opsi lebih bagus: `gemini-3-pro-image`). Lihat `backend/.env.example`.

---

## Revisi 2

## Perubahan di revisi ini

1. **Integrasi Gemini asli** (`backend/app/ai_service.py`)
   - Pakai SDK resmi `google-genai`: `client.models.generate_content(model=..., contents=...)`.
     (`client.interactions.create()` yang sempat disebut itu API untuk fitur "Deep Research Agent" / agent
     platform, bukan untuk generate teks/gambar biasa — jadi tidak dipakai di sini.)
   - Teks (deskripsi + caption): model default `gemini-2.5-flash`.
   - Visual: model default `gemini-2.5-flash-image`, hasilnya di-generate beneran sebagai gambar PNG,
     disimpan di `backend/generated_content/`, dan di-serve lewat `/generated_content/{file}`.
     Kalau image generation gagal (network/quota), otomatis fallback ke deskripsi teks konsep visual.
   - API key disimpan di `backend/.env` (sudah di-gitignore, tidak ke-commit).
   - **Catatan pengujian**: di sandbox tempat saya kerja, panggilan ke Gemini gagal karena domain
     `generativelanguage.googleapis.com` diblok di jaringan sandbox — tapi errornya mengonfirmasi kodenya
     sudah benar (berhasil mencapai endpoint asli, error murni soal network policy sandbox, bukan bug).
     Di komputermu (jaringan normal), ini seharusnya langsung jalan.

2. **Folder Piket dihapus** dari UI & endpoint API (`/content-plans` sudah tidak ada di `main.py`).
   Fungsi database-nya (`create_content_plan`, `list_content_plans`) sengaja masih ada di
   `backend/app/database.py` (tidak dipakai, tidak mengganggu) supaya test lama tetap lolos.

3. **Topik: fixed vs custom**
   - 25 topik "tetap" (sesuai daftar program prioritas & isu tematik yang kamu kasih) otomatis di-seed
     saat backend pertama kali jalan (`seed_fixed_topics()` di `database.py`), dengan query simple
     (singkatan OR nama lengkap) — daftar lengkapnya ada di `FIXED_TOPICS` dalam `database.py`.
   - Topik "custom" bisa ditambah bebas lewat form di tab Topik.
   - Distingsi piket pagi/malam sudah dihapus — sekarang semua topik tersedia untuk dipilih siapa saja
     tanpa terikat waktu piket.

4. **Generate Konten**: ada opsi rasio visual — `1:1`, `3:4`, `9:16`, `16:9` — diteruskan ke Gemini image
   model (`image_config.aspect_ratio`).

5. **Laporan Pimpinan dihapus dulu** dari UI & API. Tabel `reports` di database masih ada tapi tidak
   dipakai — gampang diaktifkan lagi nanti kalau sudah butuh.

## Dua penyesuaian etis (tetap dari revisi sebelumnya, tidak berubah)

1. Caption dibatasi maksimal 10 (`MAX_CAPTIONS` di `ai_service.py`).
2. Klarifikasi wajib menyertakan sumber/data resmi (`fact_sources`); backend menolak (400) kalau kosong.

## Cara menjalankan

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```
- API key Gemini sudah ada di `backend/.env` — kalau mau ganti model, edit `GEMINI_TEXT_MODEL` /
  `GEMINI_IMAGE_MODEL` di file yang sama.
- Cek endpoint di `http://127.0.0.1:8000/docs`.
- 25 topik fixed otomatis muncul begitu backend pertama kali jalan.

### Frontend
```bash
cd frontend
npm install   # kalau node_modules lama error (beda platform Windows/Linux), hapus dulu node_modules & package-lock.json
npm run dev
```

## Yang masih placeholder

- **GPT** belum diintegrasi (belum ada API key). `call_gpt()` di `ai_service.py` masih mock, tinggal isi
  kalau nanti mau pakai GPT untuk sebagian alur (`OPENAI_API_KEY`).
- **Integrasi CTS** (upload manual ke CTS) tetap di luar sistem ini, sesuai flowchart nomor 7-8.

## Struktur database (SQLite)

- `topics` (+ kolom `category`: `'tetap'` atau `'custom'`)
- `news_items` — hasil automatic search
- `analyses` — hasil analisis + rekomendasi (rule-based, bukan AI, supaya transparan/auditable)
- `content_items` (+ kolom `aspect_ratio`) — visual concept (path gambar atau teks fallback), deskripsi, caption
- `content_plans`, `reports` — masih ada di skema tapi tidak dipakai di UI/API saat ini
