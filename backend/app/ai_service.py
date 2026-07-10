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
# Kerangka TAHAP & DEFINISI ESKALASI (SOP monitoring pemberitaan).
# LEVEL_DEFINITIONS = teks baku (tindakan + definisi) yang diisi server-side ke
# kolom "TAHAP & DEFINISI ESKALASI" — biar isinya persis SOP dan tidak dikarang model.
# ---------------------------------------------------------------------------
LEVEL_DEFINITIONS = {
    "VERY LOW": {
        "tindakan": "Pencatatan pasif ke dalam sistem log pemantauan. Tidak diperlukan respons komunikasi aktif.",
        "definisi": (
            "Pemberitaan bersifat minimal, terisolasi, dan tidak menunjukkan potensi penyebaran yang "
            "signifikan. Isu belum membentuk narasi yang koheren atau terstruktur. Tidak ada indikasi "
            "mobilisasi opini publik maupun perhatian media arus utama."
        ),
    },
    "LOW": {
        "tindakan": "Aktivasi sistem peringatan internal, penyiapan FAQ dan narasi tandingan dasar, penugasan tim pemantauan terjadwal.",
        "definisi": (
            "Pemberitaan mulai menunjukkan pola awal yang patut diwaspadai. Isu mulai mendapat perhatian "
            "dari beberapa kanal secara bersamaan meskipun belum viral. Terdapat potensi eskalasi jika "
            "tidak dipantau secara terstruktur."
        ),
    },
    "MEDIUM": {
        "tindakan": "Pemantauan berkala terjadwal (harian), penerbitan klarifikasi resmi melalui kanal komunikasi pemerintah yang tepat, koordinasi antar unit humas.",
        "definisi": (
            "Isu telah berkembang menjadi perbincangan publik yang terukur. Narasi keliru atau disinformasi "
            "mulai mendapat traksi dan berpotensi membentuk persepsi publik secara lebih luas jika tidak "
            "segera direspons dengan klarifikasi yang tepat sasaran."
        ),
    },
    "HIGH": {
        "tindakan": "Respons reaktif terbatas melalui pernyataan resmi, konferensi pers terjadwal, atau siaran pers yang menjawab poin-poin spesifik. Koordinasi dengan pimpinan instansi.",
        "definisi": (
            "Isu telah menjadi perbincangan publik yang luas dan mendapat perhatian media arus utama. Narasi "
            "yang berkembang berpotensi merusak kepercayaan publik terhadap program atau institusi secara "
            "nyata. Diperlukan respons resmi yang terukur dan terkontrol."
        ),
    },
    "VERY HIGH": {
        "tindakan": "Peluncuran strategi counter-campaign terstruktur: narasi tandingan komprehensif, mobilisasi juru bicara dan mitra komunikasi, kampanye edukasi publik multi-kanal, serta koordinasi lintas kementerian/lembaga jika diperlukan.",
        "definisi": (
            "Situasi telah mencapai tingkat krisis komunikasi. Isu membentuk narasi dominan yang merusak "
            "reputasi institusi secara sistemik, berpotensi mengganggu implementasi program, dan/atau memicu "
            "tekanan publik, sosial, maupun politik secara terorganisir. Diperlukan intervensi komunikasi "
            "yang terstruktur, masif, dan multi-kanal."
        ),
    },
}

# Kerangka lengkap (tindakan + definisi + karakteristik) — dipakai di dalam prompt
# sebagai DATA REFERENSI untuk klasifikasi (Langkah 2).
ESCALATION_FRAMEWORK = """
<FRAMEWORK_ESKALASI>
Catatan: blok ini DATA REFERENSI untuk klasifikasi. Kolom ARTIKEL & SARAN INFORMASI wajib diisi model.

[VERY LOW] Tindakan: Pencatatan pasif ke sistem log. Tidak perlu respons aktif.
  Definisi: Pemberitaan minimal, terisolasi, tidak berpotensi menyebar. Isu belum membentuk narasi koheren; tidak ada mobilisasi opini/perhatian media arus utama.
  Karakteristik: volume 1-3 artikel; sumber low-reach/non-mainstream; tidak ada pengulangan framing; engagement nyaris nihil; sentimen netral/pertanyaan informatif; tidak ada figur berpengaruh; isu lokal tanpa resonansi.

[LOW] Tindakan: Aktivasi peringatan internal, siapkan FAQ & narasi tandingan dasar, tim pemantau terjadwal.
  Definisi: Pola awal yang patut diwaspadai. Isu mulai diperhatikan beberapa kanal bersamaan meski belum viral; ada potensi eskalasi.
  Karakteristik: volume 4-10 artikel; cross-platform seeding; kesamaan framing/terminologi mulai muncul; engagement rendah-sedang; sentimen bergeser negatif/kritis; mulai ada salah persepsi; belum ada amplifikasi mainstream/tokoh.

[MEDIUM] Tindakan: Pemantauan harian, klarifikasi resmi via kanal pemerintah, koordinasi antar unit humas.
  Definisi: Sudah jadi perbincangan publik terukur. Narasi keliru/disinformasi mulai mendapat traksi & bisa membentuk persepsi lebih luas.
  Karakteristik: volume tinggi & konsisten beberapa hari; masuk media digital menengah-atas / akun follower signifikan; framing negatif mulai dominan; engagement meningkat; terbentuk klaster pro-kontra; potensi salah tafsir kebijakan; mulai dikaitkan isu sensitif (politisasi awal).

[HIGH] Tindakan: Respons reaktif terbatas — pernyataan resmi, konferensi pers, siaran pers menjawab poin spesifik; koordinasi pimpinan.
  Definisi: Perbincangan publik luas & perhatian media arus utama. Narasi berpotensi nyata merusak kepercayaan publik; perlu respons resmi terukur.
  Karakteristik: volume tinggi di media mainstream & platform besar; diamplifikasi tokoh berpengaruh; framing negatif/menyudutkan/tuduhan dominan; misinformasi diterima luas; engagement sangat tinggi (marah/tuntutan klarifikasi); muncul liputan investigatif/pertanyaan legislatif; memengaruhi partisipasi publik; waktu respons kritis.

[VERY HIGH] Tindakan: Counter-campaign terstruktur — narasi tandingan komprehensif, mobilisasi juru bicara & mitra, edukasi multi-kanal, koordinasi lintas K/L.
  Definisi: Krisis komunikasi. Narasi dominan merusak reputasi institusi secara sistemik, mengganggu implementasi program, memicu tekanan publik/sosial/politik terorganisir.
  Karakteristik: volume masif berkelanjutan multi-platform; agenda setting nasional; indikasi coordinated inauthentic behavior; amplifikasi koalisi aktor; sentimen dominan negatif + seruan aksi (demo/petisi/boikot); masuk ranah politik formal (interpelasi/hearing DPR); kepercayaan publik turun terukur; potensi dampak nyata ke kebijakan/keselamatan publik.
</FRAMEWORK_ESKALASI>
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

def _build_table_from_classification(classification: dict) -> list:
    """
    Susun TABEL 5 baris (satu per TAHAP, urut VERY LOW..VERY HIGH). Kolom
    TAHAP & DEFINISI diisi dari LEVEL_DEFINITIONS (teks baku SOP); ARTIKEL &
    SARAN INFORMASI diambil dari hasil klasifikasi model.
    """
    classification = classification or {}
    # normalisasi kunci (VERY_LOW / very low / dst) -> bentuk baku
    norm = {}
    for key, value in classification.items():
        k = str(key).upper().replace("_", " ").strip()
        norm[k] = value

    table = []
    for level in ESCALATION_LEVELS:
        entry = norm.get(level) or {}
        artikel = entry.get("artikel") if isinstance(entry, dict) else None
        if not isinstance(artikel, list):
            artikel = []
        artikel = [str(a).strip() for a in artikel if str(a).strip()]
        saran = entry.get("saran_informasi") if isinstance(entry, dict) else ""
        table.append(
            {
                "tahap": level,
                "tindakan": LEVEL_DEFINITIONS[level]["tindakan"],
                "definisi": LEVEL_DEFINITIONS[level]["definisi"],
                "artikel": artikel,
                "saran_informasi": str(saran or "").strip(),
            }
        )
    return table


def _highest_level_with_articles(table: list) -> str:
    highest = "VERY LOW"
    for row in table:
        if row.get("artikel"):
            highest = row["tahap"]  # table sudah urut menaik, jadi ini tahap tertinggi terisi
    return highest


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
    # Semua judul dimasukkan ke tahap hasil estimasi; tahap lain kosong.
    table = _build_table_from_classification(
        {
            level: {
                "artikel": all_titles,
                "saran_informasi": "Kumpulkan data/rilis resmi terbaru terkait topik ini untuk memperkuat narasi tandingan.",
            }
        }
    )

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
            "escalation_table": table,
            "narrative_analysis": "",
            "kontra_opini": {"judul": "", "isi": ""},
            "generated_by": "rule-based-fallback",
        },
    }


def build_analysis_prompt(topic_title: str, news_items: List[dict]) -> str:
    """
    Prompt analisis = system prompt INSTRUKSI (ROLE/TUGAS/ATURAN/FRAMEWORK) yang diminta
    user, dengan "file berita" diisi dari judul+URL hasil crawling/selected di topik.
    Output diminta sebagai JSON supaya bisa dirender jadi TABEL 3 kolom + artikel kontra opini.
    """
    return f"""
<INSTRUKSI>
<ROLE> Kamu adalah seorang pranata humas jurnalis senior ahli komunikasi publik pada kantor humas
instansi pemerintah yang bertugas melakukan monitoring pemberitaan berbagai program pemerintah.
Lakukan analisis pada setiap JUDUL artikel dalam DAFTAR BERITA di bawah (topik: "{topic_title}"). </ROLE>

<TUGAS>
<langkah id="1"> Temukan dan golongkan JUDUL yang memiliki isi dan sudut pandangnya hampir sama. </langkah>
<langkah id="2"> Masukkan JUDUL yang sudah digolongkan ke dalam kolom ARTIKEL sesuai TAHAP & DEFINISI ESKALASI
  yang sesuai (pastikan SELURUH JUDUL dimasukkan — jangan sampai ada JUDUL yang tidak dimasukkan). </langkah>
<langkah id="3"> Lakukan monitoring pemberitaan 1 minggu terakhir sesuai tema/isu JUDUL terkait, temukan dan
  tabulasi informasi yang bisa dipakai menyusun artikel kontra opini, tuliskan ke kolom SARAN INFORMASI
  sesuai JUDUL yang dikontra. </langkah>
<langkah id="4"> Buat artikel kontra opini untuk isu dalam JUDUL yang masuk KOLOM ARTIKEL dengan TAHAP
  TERTINGGI, mengacu URL terkait; artikel baru harus relevan & tajam. </langkah>
</TUGAS>

<ATURAN_PENULISAN_ARTIKEL>
- Judul artikel baru WAJIB meng-kontra HEAD-to-HEAD dengan judul yang dikontra, kosakata & gaya bahasa bombastis penuh click bait.
- Sentuh & beri atensi ke setiap isu yang disebut dalam artikel tersebut, jangan ada yang terlewat.
- Bahasa & gaya isi artikel HARUS resmi-populer, menarik bagi kalangan muda, tetap elegan, sopan, sesuai etika jurnalistik.
- Format artikel pada umumnya: beberapa paragraf pendek yang kohesif & saling berhubungan, TANPA numbering/bullet/multilevel list.
- Sebut nama & kutipan pendapat tokoh yang dikontra, diikuti logika/alasan mengapa pendapat itu tidak tepat.
- Masukkan beberapa kutipan/pendapat tokoh publik relevan yang mendukung urgensi isu (WAJIB sebut nama tokoh).
- Cari alasan/hal yang mendukung program akan berhasil; tambahkan disertai ungkapan optimisme bahwa isu dalam JUDUL akan berhasil & bermanfaat sebesar-besarnya bagi bangsa Indonesia.
</ATURAN_PENULISAN_ARTIKEL>

{ESCALATION_FRAMEWORK}

<DAFTAR_BERITA> (hasil crawling/pilihan pada topik — inilah "file" yang dianalisis)
{_format_news_for_prompt(news_items)}
</DAFTAR_BERITA>

<FORMAT_OUTPUT>
Kembalikan HANYA JSON valid (tanpa teks lain). "classification" = hasil pengisian kolom ARTIKEL & SARAN
INFORMASI untuk KELIMA tahap (judul yang tidak masuk suatu tahap tetap harus muncul di tahap lain —
seluruh judul wajib terklasifikasi). "kontra_opini" = artikel Langkah 4 untuk tahap tertinggi yang terisi.
{{
  "classification": {{
    "VERY LOW":  {{ "artikel": ["judul...", "..."], "saran_informasi": "data/fakta/rilis resmi untuk kontra opini" }},
    "LOW":       {{ "artikel": [], "saran_informasi": "" }},
    "MEDIUM":    {{ "artikel": [], "saran_informasi": "" }},
    "HIGH":      {{ "artikel": [], "saran_informasi": "" }},
    "VERY HIGH": {{ "artikel": [], "saran_informasi": "" }}
  }},
  "highest_level": "VERY LOW|LOW|MEDIUM|HIGH|VERY HIGH",
  "sentiment": "positif|netral|negatif",
  "risk_level": "rendah|sedang|sedang-tinggi|tinggi",
  "dominant_narrative": "kalimat narasi dominan yang beredar",
  "summary": "ringkasan analisis 2-4 kalimat",
  "recommended_action": "amplifikasi|klarifikasi_fakta",
  "action_reasoning": "alasan singkat pemilihan tindakan",
  "suggested_angles": ["angle 1", "angle 2", "angle 3", "angle 4"],
  "kontra_opini": {{
    "judul": "judul artikel kontra opini (bombastis, head-to-head)",
    "isi": "isi artikel beberapa paragraf pendek, tanpa bullet/numbering, sesuai ATURAN_PENULISAN_ARTIKEL"
  }}
}}
</FORMAT_OUTPUT>
</INSTRUKSI>
"""


def generate_analysis(topic_title: str, news_items: List[dict]) -> dict:
    """
    Analisis kumpulan berita untuk satu topik memakai Gemini + system prompt INSTRUKSI
    (kerangka TAHAP & DEFINISI ESKALASI). Kalau Gemini tidak tersedia / gagal, jatuh ke
    analisis rule-based. Selalu mengembalikan field backward-compatible + `details`.
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

    suggested_angles = parsed.get("suggested_angles")
    if not isinstance(suggested_angles, list) or not suggested_angles:
        suggested_angles = fallback["suggested_angles"]

    table = _build_table_from_classification(parsed.get("classification"))
    # kalau model tidak mengklasifikasi apa pun, pakai tabel fallback biar tidak kosong
    if not any(row["artikel"] for row in table):
        table = fallback["details"]["escalation_table"]

    level = str(parsed.get("highest_level", "")).upper().replace("_", " ").strip()
    if level not in ESCALATION_LEVELS:
        level = _highest_level_with_articles(table)

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
            "escalation_table": table,
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
