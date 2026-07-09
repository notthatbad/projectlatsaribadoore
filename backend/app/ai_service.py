"""
Modul AI service.

Integrasi Gemini asli lewat SDK resmi `google-genai`:
    from google import genai
    client = genai.Client(api_key=...)
    client.models.generate_content(model=..., contents=...)

Alur konten dipecah menjadi tiga fungsi terpisah supaya bisa dipicu oleh tombol
yang berbeda di UI (sesuai cara kerja Gemini: teks dan gambar butuh "treatment"
pemanggilan yang berbeda):

    1. generate_visual()      -> MEDIA VISUAL (gambar jadi, bukan prompt)
    2. generate_captions()    -> CAPTION
    3. generate_description() -> DESKRIPSI PENJELAS (butuh visual lebih dulu)

Semua mengacu ke HASIL ANALISIS supaya konten menyajikan data yang akurat,
bukan asal infografis/poster.

Catatan penting soal desain (jangan dihapus waktu integrasi lanjut):
1. `recommended_action` HANYA boleh salah satu dari: "amplifikasi" atau
   "klarifikasi_fakta". Kalau tindakannya klarifikasi, wajib menyertakan
   `fact_sources` (data/sumber resmi yang dipakai untuk meluruskan).
2. Jumlah caption dibatasi MAX_CAPTIONS.
"""
import base64
import json
import os
import re
import uuid
from typing import List, Optional, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request

MAX_CAPTIONS = 100
ALLOWED_ACTIONS = ("amplifikasi", "klarifikasi_fakta")
ALLOWED_ASPECT_RATIOS = ("1:1", "3:4", "9:16", "16:9")
ESCALATION_LEVELS = ("VERY LOW", "LOW", "MEDIUM", "HIGH", "VERY HIGH")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")

USE_REAL_GPT = bool(OPENAI_API_KEY)
USE_REAL_GEMINI = bool(GEMINI_API_KEY)

GENERATED_CONTENT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "generated_content")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000")

_gemini_client = None


# ---------------------------------------------------------------------------
# Kerangka TAHAP & DEFINISI ESKALASI (diambil dari SOP monitoring pemberitaan).
# Dipakai sebagai konteks prompt analisis supaya output terstruktur & seragam.
# ---------------------------------------------------------------------------
ESCALATION_FRAMEWORK = """
KERANGKA TAHAP & DEFINISI ESKALASI (5 tingkat):

VERY LOW — Pencatatan pasif ke sistem log. Tidak perlu respons komunikasi aktif.
  Pemberitaan minimal & terisolasi (1-3 artikel), sumber low-reach/non-mainstream,
  tidak ada pengulangan framing, engagement nyaris nihil, sentimen netral, tidak ada
  figur berpengaruh, isu lokal tanpa resonansi lebih besar.

LOW — Aktivasi peringatan internal, siapkan FAQ & narasi tandingan dasar, tim
  pemantau terjadwal. Volume moderat (4-10 artikel), mulai cross-platform, muncul
  kesamaan framing/terminologi, engagement rendah-sedang, sentimen bergeser negatif/
  kritis, mulai ada misinformasi ringan, belum ada amplifikasi mainstream/tokoh.

MEDIUM — Pemantauan harian, penerbitan klarifikasi resmi lewat kanal pemerintah,
  koordinasi antar unit humas. Volume tinggi & konsisten beberapa hari, masuk media
  digital menengah-atas, framing negatif mulai dominan, engagement meningkat, terbentuk
  klaster opini pro-kontra, potensi salah tafsir kebijakan, mulai dikaitkan isu sensitif.

HIGH — Respons reaktif terbatas: pernyataan resmi, konferensi pers terjadwal, siaran
  pers menjawab poin spesifik, koordinasi pimpinan. Volume tinggi di media mainstream,
  diamplifikasi tokoh berpengaruh, framing negatif/menyudutkan dominan, misinformasi
  diterima luas, engagement sangat tinggi (marah/tidak percaya), muncul liputan
  investigatif/pertanyaan legislatif. Waktu respons jadi kritis.

VERY HIGH — Krisis komunikasi. Luncurkan counter-campaign terstruktur: narasi tandingan
  komprehensif, mobilisasi juru bicara & mitra, kampanye edukasi multi-kanal, koordinasi
  lintas K/L. Volume masif & berkelanjutan multi-platform, jadi agenda setting nasional,
  indikasi coordinated inauthentic behavior, amplifikasi koalisi aktor, sentimen dominan
  negatif + seruan aksi (demo/petisi/boikot), masuk ranah politik formal (interpelasi/
  hearing DPR), kepercayaan publik turun terukur.
"""


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai

        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


def call_gpt(prompt: str) -> str:
    """Placeholder pemanggilan GPT. Isi nanti begitu OPENAI_API_KEY tersedia."""
    if not USE_REAL_GPT:
        return f"[MOCK GPT] {prompt[:120]}..."
    raise NotImplementedError("Isi integrasi OpenAI API di sini setelah OPENAI_API_KEY tersedia.")


def call_gemini_text(prompt: str) -> str:
    """Panggil Gemini untuk teks. Fallback ke mock kalau key belum ada."""
    if not USE_REAL_GEMINI:
        return f"[MOCK GEMINI] {prompt[:120]}..."

    try:
        client = _get_gemini_client()
        response = client.models.generate_content(model=GEMINI_TEXT_MODEL, contents=prompt)
        return (response.text or "").strip()
    except Exception as exc:  # noqa: BLE001 - supaya alur tetap jalan walau API error
        return f"[GEMINI ERROR — cek API key/kuota/model: {exc}]"


def _extract_json_object(text: str) -> dict:
    if not text:
        return {}
    if isinstance(text, dict):
        return text
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return {}


def _save_image_bytes(data: bytes) -> Optional[str]:
    os.makedirs(GENERATED_CONTENT_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(GENERATED_CONTENT_DIR, filename)
    with open(filepath, "wb") as handle:
        handle.write(data)
    return filename


def _normalize_captions(raw_captions, target_count: int) -> List[str]:
    if isinstance(raw_captions, str):
        captions = [line.strip("-•* ").strip() for line in raw_captions.split("\n") if line.strip()]
    elif isinstance(raw_captions, list):
        captions = [str(item).strip() for item in raw_captions if str(item).strip()]
    else:
        captions = []

    if not captions:
        return [f"Caption otomatis {idx + 1}" for idx in range(min(target_count, MAX_CAPTIONS))]

    if len(captions) >= target_count:
        return captions[:target_count]

    expanded = list(captions)
    index = 0
    while len(expanded) < target_count:
        base = captions[index % len(captions)]
        expanded.append(f"{base} ({len(expanded) + 1})")
        index += 1
    return expanded[:target_count]


def _map_aspect_ratio_to_size(aspect_ratio: str) -> str:
    ratio_map = {
        "1:1": "1024x1024",
        "3:4": "1024x1536",
        "9:16": "1024x1536",
        "16:9": "1536x1024",
    }
    return ratio_map.get(aspect_ratio, "1024x1024")


def _extract_image_bytes(response) -> Optional[bytes]:
    """Ambil byte gambar dari response Gemini, tahan beberapa bentuk struktur SDK."""
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                data = inline.data
                if isinstance(data, str):
                    data = base64.b64decode(data)
                return data
    # SDK versi lama kadang expose langsung di response.parts
    for part in getattr(response, "parts", None) or []:
        inline = getattr(part, "inline_data", None)
        if inline is not None and getattr(inline, "data", None):
            data = inline.data
            if isinstance(data, str):
                data = base64.b64decode(data)
            return data
    return None


def generate_image(prompt: str, aspect_ratio: str = "1:1") -> Tuple[Optional[str], Optional[str]]:
    """
    Generate gambar JADI dari prompt visual.
    Return (filename, error). Sukses -> (filename, None). Gagal -> (None, pesan_error).
    Prioritas: OpenAI Image API (kalau ada key) lalu Gemini image model.
    """
    openai_error = None
    if OPENAI_API_KEY:
        try:
            payload = {
                "model": OPENAI_IMAGE_MODEL,
                "prompt": prompt,
                "size": _map_aspect_ratio_to_size(aspect_ratio),
                "response_format": "b64_json",
            }
            req = urllib_request.Request(
                "https://api.openai.com/v1/images/generations",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=120) as response:
                body = json.load(response)
            image_b64 = (body.get("data") or [{}])[0].get("b64_json")
            if image_b64:
                data = base64.b64decode(image_b64)
                return _save_image_bytes(data), None
            openai_error = "OpenAI tidak mengembalikan gambar"
        except (urllib_error.URLError, urllib_error.HTTPError, ValueError, KeyError, TypeError) as exc:
            openai_error = str(exc)  # jangan berhenti, coba Gemini

    if not USE_REAL_GEMINI:
        return None, openai_error or "Tidak ada provider gambar aktif (GEMINI_API_KEY/OPENAI_API_KEY kosong)."

    last_error = openai_error
    try:
        from google.genai import types

        client = _get_gemini_client()

        # Coba beberapa konfigurasi karena tiap versi model/SDK sedikit berbeda.
        config_attempts = []
        try:
            config_attempts.append(
                types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
                )
            )
        except Exception:  # noqa: BLE001 - ImageConfig/aspect_ratio mungkin belum didukung SDK lama
            pass
        config_attempts.append(types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))
        config_attempts.append(types.GenerateContentConfig(response_modalities=["IMAGE"]))

        for config in config_attempts:
            try:
                response = client.models.generate_content(
                    model=GEMINI_IMAGE_MODEL,
                    contents=prompt,
                    config=config,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            data = _extract_image_bytes(response)
            if data:
                return _save_image_bytes(data), None
            last_error = "Model tidak mengembalikan bagian gambar (cek apakah GEMINI_IMAGE_MODEL mendukung output IMAGE)."
        return None, last_error
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Helper konteks
# ---------------------------------------------------------------------------

def _format_news_for_prompt(news_items: List[dict]) -> str:
    lines = []
    for idx, item in enumerate(news_items, start=1):
        title = item.get("title", "").strip()
        source = item.get("source", "").strip()
        snippet = item.get("snippet", "").strip()
        url = item.get("url", "").strip()
        lines.append(f"{idx}. JUDUL: {title}\n   SUMBER: {source}\n   URL: {url}\n   CUPLIKAN: {snippet}")
    return "\n".join(lines) if lines else "(tidak ada berita terkumpul)"


def _analysis_context(analysis: dict) -> str:
    """Ringkas hasil analisis jadi konteks grounding untuk visual/caption/deskripsi."""
    details = analysis.get("details") or {}
    parts = [
        f"TOPIK: {analysis.get('topic_title', '')}",
        f"RINGKASAN ANALISIS: {analysis.get('summary', '')}",
        f"NARASI DOMINAN: {analysis.get('dominant_narrative', '')}",
        f"SENTIMEN: {analysis.get('sentiment', '')}",
        f"TINGKAT RISIKO: {analysis.get('risk_level', '')}",
        f"TAHAP ESKALASI: {details.get('escalation_level', '')}",
    ]
    narrative = details.get("narrative_analysis")
    if narrative:
        parts.append(f"ANALISIS NARASI: {narrative}")
    saran = []
    for row in details.get("escalation_table", []) or []:
        if row.get("saran_informasi"):
            saran.append(f"- ({row.get('tahap')}) {row.get('saran_informasi')}")
    if saran:
        parts.append("DATA/SARAN INFORMASI PENDUKUNG:\n" + "\n".join(saran))
    return "\n".join(p for p in parts if p.strip().rstrip(":").strip())


# ---------------------------------------------------------------------------
# ANALISIS — mengacu kerangka TAHAP & DEFINISI ESKALASI (lebih dalam)
# ---------------------------------------------------------------------------

def _fallback_analysis(topic_title: str, news_items: List[dict]) -> dict:
    """Analisis rule-based (dipakai kalau Gemini tidak tersedia / gagal parse)."""
    combined_text = " ".join(
        (item.get("title", "") + " " + item.get("snippet", "")) for item in news_items
    ).lower()

    negative_signals = ["kritik", "hancur", "gagal", "korupsi", "tolak", "masalah", "protes", "keracunan", "demo", "mangkrak"]
    negatives = sum(1 for signal in negative_signals if signal in combined_text)
    is_negative = negatives > 0
    volume = len(news_items)

    if volume == 0 or (volume <= 3 and not is_negative):
        level = "VERY LOW"
    elif volume <= 10 and negatives <= 1:
        level = "LOW"
    elif negatives <= 2:
        level = "MEDIUM"
    elif negatives <= 4:
        level = "HIGH"
    else:
        level = "VERY HIGH"

    if is_negative:
        sentiment = "negatif"
        recommended_action = "klarifikasi_fakta"
        action_reasoning = (
            "Ditemukan narasi negatif/berpotensi menyesatkan terkait topik ini. "
            "Rekomendasi: susun klarifikasi berbasis data resmi, bukan sekadar membantah tanpa bukti."
        )
        dominant_narrative = "Narasi kritis/negatif terhadap program"
        risk_level = "sedang-tinggi"
    else:
        sentiment = "positif" if news_items else "netral"
        recommended_action = "amplifikasi"
        action_reasoning = (
            "Pemberitaan cenderung positif/netral, layak diperkuat agar capaian program lebih dikenal publik."
        )
        dominant_narrative = "Progres/capaian program dilaporkan positif" if news_items else "Belum ada berita signifikan"
        risk_level = "rendah"

    all_titles = [item.get("title", "") for item in news_items if item.get("title")]
    escalation_table = [
        {
            "tahap": level,
            "definisi": f"Estimasi otomatis: pemberitaan berada pada tahap {level} berdasarkan volume ({volume} artikel) dan sinyal sentimen.",
            "artikel": all_titles,
            "saran_informasi": "Kumpulkan data/rilis resmi terbaru terkait topik ini untuk memperkuat narasi tandingan.",
        }
    ]

    summary = (
        f"Ditemukan {volume} berita terkait '{topic_title}'. Sentimen dominan: {sentiment}. "
        f"Estimasi tahap eskalasi: {level}."
    )

    suggested_angles = [
        "Kesejahteraan masyarakat",
        "Kecepatan & efektivitas kerja pemerintah",
        "Dampak ekonomi/pendidikan/kesehatan bagi masyarakat",
        "Komitmen jangka panjang pemerintah",
    ]

    return {
        "sentiment": sentiment,
        "dominant_narrative": dominant_narrative,
        "risk_level": risk_level,
        "summary": summary,
        "recommended_action": recommended_action,
        "action_reasoning": action_reasoning,
        "suggested_angles": suggested_angles,
        "details": {
            "escalation_level": level,
            "escalation_reasoning": f"Estimasi rule-based dari {volume} artikel dan {negatives} sinyal negatif.",
            "escalation_table": escalation_table,
            "narrative_analysis": (
                "Analisis ringkas (mode fallback tanpa AI). Untuk analisis mendalam sesuai kerangka eskalasi, "
                "pastikan GEMINI_API_KEY & nama model valid."
            ),
            "kontra_opini": {"judul": "", "isi": ""},
            "generated_by": "rule-based-fallback",
        },
    }


def build_analysis_prompt(topic_title: str, news_items: List[dict]) -> str:
    """Prompt analisis mendalam berbasis SOP monitoring & kerangka eskalasi."""
    return f"""
ROLE: Kamu adalah pranata humas jurnalis senior ahli komunikasi publik pada kantor humas
instansi pemerintah yang bertugas memonitor pemberitaan program pemerintah. Lakukan analisis
mendalam atas kumpulan JUDUL berita berikut untuk topik: "{topic_title}".

{ESCALATION_FRAMEWORK}

DAFTAR JUDUL/BERITA YANG DIANALISIS:
{_format_news_for_prompt(news_items)}

TUGAS:
1. Golongkan judul-judul yang isi & sudut pandangnya mirip.
2. Klasifikasikan setiap judul ke TAHAP eskalasi yang paling sesuai (VERY LOW..VERY HIGH).
   Pastikan SELURUH judul masuk ke salah satu tahap, jangan ada yang terlewat.
3. Untuk tiap tahap yang terisi, tuliskan SARAN INFORMASI: data/fakta/rilis resmi yang bisa
   dipakai menyusun narasi tandingan/kontra opini yang relevan.
4. Tentukan TAHAP tertinggi yang muncul, lalu tulis satu artikel kontra opini yang tajam dan
   relevan untuk isu di tahap tertinggi tersebut. Judul artikel harus meng-kontra head-to-head,
   gaya bahasa resmi-populer, menarik untuk anak muda, elegan & sesuai etika jurnalistik,
   beberapa paragraf pendek yang kohesif TANPA numbering/bullet, sebut & bantah pendapat tokoh
   yang dikontra dengan alasan logis, sertakan optimisme bahwa program akan berhasil.

WAJIB kembalikan HANYA JSON valid (tanpa penjelasan lain) dengan struktur persis berikut:
{{
  "sentiment": "positif|netral|negatif",
  "risk_level": "rendah|sedang|sedang-tinggi|tinggi",
  "dominant_narrative": "kalimat narasi dominan yang beredar",
  "summary": "ringkasan analisis 2-4 kalimat",
  "recommended_action": "amplifikasi|klarifikasi_fakta",
  "action_reasoning": "alasan singkat pemilihan tindakan",
  "suggested_angles": ["angle 1", "angle 2", "angle 3", "angle 4"],
  "escalation_level": "VERY LOW|LOW|MEDIUM|HIGH|VERY HIGH",
  "escalation_reasoning": "alasan penetapan tahap tertinggi",
  "escalation_table": [
    {{
      "tahap": "VERY LOW|LOW|MEDIUM|HIGH|VERY HIGH",
      "definisi": "definisi/tindakan singkat tahap ini",
      "artikel": ["judul yang masuk tahap ini", "..."],
      "saran_informasi": "data/fakta/rilis resmi untuk narasi tandingan"
    }}
  ],
  "narrative_analysis": "analisis naratif mendalam 1-3 paragraf tentang pola framing, aktor, dan trajektori isu",
  "kontra_opini": {{
    "judul": "judul artikel kontra opini untuk tahap tertinggi",
    "isi": "isi artikel beberapa paragraf pendek, tanpa bullet/numbering"
  }}
}}
"""


def generate_analysis(topic_title: str, news_items: List[dict]) -> dict:
    """
    Analisis kumpulan berita untuk satu topik memakai Gemini + kerangka TAHAP & DEFINISI
    ESKALASI. Kalau Gemini tidak tersedia / gagal, jatuh ke analisis rule-based supaya
    aplikasi tetap jalan. Selalu mengembalikan field backward-compatible + `details`.
    """
    fallback = _fallback_analysis(topic_title, news_items)
    if not USE_REAL_GEMINI:
        return fallback

    prompt = build_analysis_prompt(topic_title, news_items)
    raw = call_gemini_text(prompt)
    parsed = _extract_json_object(raw)
    if not parsed:
        fallback["details"]["generated_by"] = "rule-based-fallback (AI gagal/tidak valid)"
        if isinstance(raw, str) and raw.startswith("[GEMINI ERROR"):
            fallback["details"]["ai_error"] = raw
        return fallback

    action = parsed.get("recommended_action")
    if action not in ALLOWED_ACTIONS:
        action = fallback["recommended_action"]

    level = str(parsed.get("escalation_level", "")).upper().strip()
    if level not in ESCALATION_LEVELS:
        level = fallback["details"]["escalation_level"]

    suggested_angles = parsed.get("suggested_angles")
    if not isinstance(suggested_angles, list) or not suggested_angles:
        suggested_angles = fallback["suggested_angles"]

    escalation_table = parsed.get("escalation_table")
    if not isinstance(escalation_table, list) or not escalation_table:
        escalation_table = fallback["details"]["escalation_table"]

    kontra = parsed.get("kontra_opini")
    if not isinstance(kontra, dict):
        kontra = {"judul": "", "isi": str(kontra or "")}

    return {
        "sentiment": parsed.get("sentiment") or fallback["sentiment"],
        "dominant_narrative": parsed.get("dominant_narrative") or fallback["dominant_narrative"],
        "risk_level": parsed.get("risk_level") or fallback["risk_level"],
        "summary": parsed.get("summary") or fallback["summary"],
        "recommended_action": action,
        "action_reasoning": parsed.get("action_reasoning") or fallback["action_reasoning"],
        "suggested_angles": suggested_angles,
        "details": {
            "escalation_level": level,
            "escalation_reasoning": parsed.get("escalation_reasoning", ""),
            "escalation_table": escalation_table,
            "narrative_analysis": parsed.get("narrative_analysis", ""),
            "kontra_opini": kontra,
            "generated_by": "gemini",
        },
    }


# ---------------------------------------------------------------------------
# CAPTION — build prompt (dipertahankan untuk test) + generator
# ---------------------------------------------------------------------------

def build_ai_prompt(topik: str, tindakan: str, gaya_bahasa: str, jumlah_komentar: int) -> str:
    """Bangun instruksi AI yang memuat aturan gaya bahasa, batas komentar, dan format JSON."""
    jumlah_komentar = min(100, max(1, int(jumlah_komentar)))
    maks_kata_kasar = max(1, int(jumlah_komentar * 0.10))

    prompt = f"""
    Anda adalah sistem automasi konten profesional. Berdasarkan topik \"{topik}\", hasilkan {jumlah_komentar} variasi caption/komentar dalam format JSON.

    KETENTUAN GAYA BAHASA UTAMA (UNTUK AMPLIFIKASI / UMUM):
    - Gunakan bahasa ala Gen Z, gaul, tidak kaku, natural, dan humanis (seperti diketik oleh manusia asli, bukan bot).
    - Berikan variasi gaya yang sangat acak/random dari skala 1-100 di setiap komentar agar tidak monoton.

    LOGIKA TINDAKAN & GAYA BAHASA KHUSUS:
    Tindakan saat ini: {tindakan}
    Gaya bahasa saat ini: {gaya_bahasa}
    """

    if tindakan == "kontra narasi":
        if gaya_bahasa == "Offensive":
            prompt += f"""
            - Sifat Kontra Narasi: Harus memperlihatkan emosi yang marah sekali, agresif, dan ngegas untuk mematahkan narasi lawan.
            - ATURAN KATA KASAR: Dari total {jumlah_komentar} komentar yang dibuat, HANYA BOLEH MAKSIMAL {maks_kata_kasar} komentar yang mengandung kata kasar/umpatan.
            - Sisa komentar lainnya harus tetap terasa sangat marah, sarkas, atau menyindir tajam, namun tanpa menggunakan kata kasar.
            """
        else:
            prompt += """
            - Sifat Kontra Narasi: Berikan argumen bantahan yang netral, tegas, berbasis data/fakta, namun tetap santai (gaya gaul/Gen Z) tanpa menyerang emosi personal.
            """

    prompt += """
    KETENTUAN GEOGRAFIS & VISUAL:
    - Anda harus menghasilkan satu instruksi prompt visual yang detail untuk kebutuhan AI Image Generation.
    - PENTING: Jika visual melibatkan peta atau penanda wilayah Indonesia, pastikan tata letak pin daerah (titik kota/provinsi) akurat secara geografis agar tidak salah posisi.

    WAJIB KEMBALIKAN OUTPUT DALAM FORMAT JSON SEPERTI INI:
    {
      "visual_prompt": "Tuliskan prompt visual detail untuk gambar di sini...",
      "komentar": [
        "Komentar variasi 1...",
        "Komentar variasi 2..."
      ]
    }
    """
    return prompt


def generate_captions(
    topic_title: str,
    analysis: dict,
    action_taken: str,
    angle: str,
    caption_count: int = 100,
    tindakan: Optional[str] = None,
    gaya_bahasa: Optional[str] = None,
    fact_sources: Optional[List[str]] = None,
) -> dict:
    """Generate CAPTION mengacu ke hasil analisis + permintaan user (amplifikasi/kontra)."""
    if action_taken not in ALLOWED_ACTIONS:
        raise ValueError(f"action_taken harus salah satu dari {ALLOWED_ACTIONS}")

    caption_count = max(1, min(int(caption_count or 100), MAX_CAPTIONS))
    prompt_tindakan = tindakan or ("amplifikasi" if action_taken == "amplifikasi" else "kontra narasi")
    prompt_gaya = gaya_bahasa or "Netral"

    context = _analysis_context({**analysis, "topic_title": topic_title})
    sources_line = ""
    if action_taken == "klarifikasi_fakta" and fact_sources:
        sources_line = "\nSUMBER/DATA RESMI (WAJIB dijadikan basis argumen): " + "; ".join(fact_sources)

    prompt = f"""
KONTEKS HASIL ANALISIS (jadikan basis fakta, jangan mengarang data):
{context}{sources_line}

ANGLE KOMUNIKASI: {angle}

{build_ai_prompt(topic_title, prompt_tindakan, prompt_gaya, caption_count)}

Catatan: seluruh komentar HARUS konsisten dengan konteks analisis di atas dan angle "{angle}".
"""
    raw = call_gemini_text(prompt)
    parsed = _extract_json_object(raw)
    raw_captions = parsed.get("komentar") if parsed else None
    if not raw_captions:
        raw_captions = raw if isinstance(raw, str) else ""
    captions = _normalize_captions(raw_captions, caption_count)
    return {"captions": captions}


# ---------------------------------------------------------------------------
# MEDIA VISUAL — gambar JADI, mengacu ke hasil analisis (data akurat)
# ---------------------------------------------------------------------------

def build_visual_prompt(
    topic_title: str,
    analysis: dict,
    content_form: str,
    aspect_ratio: str,
    action_taken: str,
    angle: str,
    tindakan: Optional[str] = None,
    fact_sources: Optional[List[str]] = None,
) -> str:
    """
    Susun brief visual detail berbasis hasil analisis. Kalau Gemini teks tersedia, minta model
    merancang brief infografis yang menampilkan data akurat; kalau tidak, pakai template.
    """
    context = _analysis_context({**analysis, "topic_title": topic_title})
    sifat = "amplifikasi/glorifikasi capaian positif" if action_taken == "amplifikasi" else (
        "klarifikasi fakta / kontra narasi berbasis data resmi"
    )
    sources_line = ""
    if action_taken == "klarifikasi_fakta" and fact_sources:
        sources_line = "\nSUMBER/DATA RESMI yang WAJIB ditampilkan: " + "; ".join(fact_sources)

    designer_prompt = f"""
Kamu desainer komunikasi visual instansi pemerintah. Rancang SATU brief prompt (bahasa Inggris,
untuk AI image generator) untuk membuat {content_form} rasio {aspect_ratio} tentang "{topic_title}".

Sifat konten: {sifat}. Angle: {angle}.

KONTEKS HASIL ANALISIS (WAJIB jadi isi visual — tampilkan data/angka/fakta yang akurat, JANGAN mengarang):
{context}{sources_line}

Ketentuan brief:
- Konten harus menyajikan data faktual dari konteks di atas (bukan sekadar dekorasi).
- Tentukan headline pendek berbahasa Indonesia yang tajam & relevan, plus 2-4 poin data/statistik.
- Gaya resmi-modern instansi pemerintah, bersih, mudah dibaca, tidak norak, teks Indonesia yang benar.
- Jika ada peta/penanda wilayah Indonesia, posisinya harus akurat secara geografis.
Kembalikan HANYA teks brief prompt final untuk image generator (tanpa penjelasan tambahan).
"""
    if USE_REAL_GEMINI:
        brief = call_gemini_text(designer_prompt)
        if brief and not brief.startswith("[GEMINI ERROR") and not brief.startswith("[MOCK"):
            return brief.strip()

    return (
        f"Create a finished {content_form} ({aspect_ratio}) in official, clean Indonesian government "
        f"style about '{topic_title}'. Purpose: {sifat}. Communication angle: {angle}. "
        f"Show accurate factual data from this analysis context: {context}. "
        f"Use correct Indonesian text, a sharp short headline, and 2-4 data points. Readable, elegant, not tacky."
    )


def generate_visual(
    topic_title: str,
    analysis: dict,
    content_form: str,
    action_taken: str,
    angle: str,
    aspect_ratio: str = "1:1",
    tindakan: Optional[str] = None,
    gaya_bahasa: Optional[str] = None,
    fact_sources: Optional[List[str]] = None,
) -> dict:
    """
    Buat MEDIA VISUAL (gambar jadi) lebih dulu, mengacu ke hasil analisis.
    Return: visual_concept (IMAGE::file atau teks brief), image_url, visual_prompt, image_error.
    """
    if action_taken not in ALLOWED_ACTIONS:
        raise ValueError(f"action_taken harus salah satu dari {ALLOWED_ACTIONS}")
    if action_taken == "klarifikasi_fakta" and not fact_sources:
        raise ValueError("Klarifikasi fakta wajib menyertakan minimal satu sumber/data resmi (fact_sources).")
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        raise ValueError(f"aspect_ratio harus salah satu dari {ALLOWED_ASPECT_RATIOS}")

    visual_prompt = build_visual_prompt(
        topic_title, analysis, content_form, aspect_ratio, action_taken, angle, tindakan, fact_sources
    )

    filename, error = generate_image(visual_prompt, aspect_ratio=aspect_ratio)
    if filename:
        return {
            "visual_concept": f"IMAGE::{filename}",
            "image_url": f"{PUBLIC_BASE_URL}/generated_content/{filename}",
            "visual_prompt": visual_prompt,
            "image_error": None,
        }

    return {
        "visual_concept": visual_prompt,
        "image_url": None,
        "visual_prompt": visual_prompt,
        "image_error": error or "Gambar gagal dibuat.",
    }


# ---------------------------------------------------------------------------
# DESKRIPSI PENJELAS — dibuat SETELAH media visual ada
# ---------------------------------------------------------------------------

def generate_description(
    topic_title: str,
    analysis: dict,
    content_form: str,
    action_taken: str,
    angle: str,
    visual_prompt: str = "",
    fact_sources: Optional[List[str]] = None,
) -> dict:
    """Generate DESKRIPSI PENJELAS untuk konten yang visualnya sudah dibuat."""
    context = _analysis_context({**analysis, "topic_title": topic_title})
    sifat = "amplifikasi positif" if action_taken == "amplifikasi" else "klarifikasi fakta / kontra narasi"
    sources_line = ""
    if action_taken == "klarifikasi_fakta" and fact_sources:
        sources_line = f" Sertakan referensi ke sumber: {', '.join(fact_sources)}."

    prompt = f"""
Tulis DESKRIPSI PENJELAS (penjelasan konten) untuk sebuah {content_form} yang sudah dibuat
tentang topik "{topic_title}", angle "{angle}", bersifat {sifat}.

KONTEKS HASIL ANALISIS (basis fakta, jangan mengarang):
{context}

BRIEF VISUAL YANG SUDAH DIPAKAI:
{visual_prompt}

Tulis 2-4 kalimat, gaya resmi-populer instansi pemerintah, menjelaskan isi visual & pesan utamanya,
konsisten dengan data pada konteks analisis.{sources_line}
Kembalikan hanya teks deskripsinya.
"""
    text = call_gemini_text(prompt)
    if not text or text.startswith("[MOCK") or text.startswith("[GEMINI ERROR"):
        text = (
            f"Konten {content_form} untuk topik '{topic_title}' dengan angle {angle} ({sifat}). "
            f"{analysis.get('summary', '')}"
        ).strip()
    return {"description": text}
