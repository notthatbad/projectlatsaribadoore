import json
import os
import sqlite3
from typing import List, Optional


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or os.path.join(os.path.dirname(__file__), "..", "data", "content_app.sqlite3")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            search_query TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'custom',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS content_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_value TEXT NOT NULL,
            slot TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS content_plan_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            FOREIGN KEY(plan_id) REFERENCES content_plans(id) ON DELETE CASCADE,
            FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE,
            UNIQUE(plan_id, topic_id)
        );

        CREATE TABLE IF NOT EXISTS news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            source TEXT,
            url TEXT,
            published_at TEXT,
            snippet TEXT,
            fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            news_item_ids TEXT NOT NULL,
            sentiment TEXT NOT NULL,
            dominant_narrative TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            summary TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            action_reasoning TEXT NOT NULL,
            suggested_angles TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS content_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL,
            action_taken TEXT NOT NULL,
            angle TEXT NOT NULL,
            content_form TEXT NOT NULL,
            aspect_ratio TEXT NOT NULL DEFAULT '1:1',
            visual_concept TEXT NOT NULL,
            description TEXT NOT NULL,
            captions TEXT NOT NULL,
            fact_sources TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_item_id INTEGER NOT NULL,
            production_date TEXT NOT NULL,
            posting_link TEXT,
            status TEXT NOT NULL DEFAULT 'menunggu_posting',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(content_item_id) REFERENCES content_items(id) ON DELETE CASCADE
        );
        """
    )

    # Migrasi ringan untuk database lama yang dibuat sebelum kolom-kolom ini ada
    existing_topic_cols = [row["name"] for row in cursor.execute("PRAGMA table_info(topics)").fetchall()]
    if "category" not in existing_topic_cols:
        cursor.execute("ALTER TABLE topics ADD COLUMN category TEXT NOT NULL DEFAULT 'custom'")

    existing_content_cols = [row["name"] for row in cursor.execute("PRAGMA table_info(content_items)").fetchall()]
    if "aspect_ratio" not in existing_content_cols:
        cursor.execute("ALTER TABLE content_items ADD COLUMN aspect_ratio TEXT NOT NULL DEFAULT '1:1'")

    existing_analysis_cols = [row["name"] for row in cursor.execute("PRAGMA table_info(analyses)").fetchall()]
    if "details" not in existing_analysis_cols:
        cursor.execute("ALTER TABLE analyses ADD COLUMN details TEXT NOT NULL DEFAULT '{}'")

    conn.commit()
    conn.close()


# 25 topik fixed = 17 program prioritas presiden + 8 quick win.
# JUDUL topik TIDAK diubah. Query disempurnakan agar automatic search lebih akurat
# (memakai istilah/nama resmi + singkatan yang tidak ambigu). Query per topik tetap
# bisa di-edit sendiri lewat UI (endpoint PUT /topics/{id}).
FIXED_TOPICS = [
    ("Makan Bergizi Gratis", '"makan bergizi gratis" OR "MBG" OR "Badan Gizi Nasional" OR "BGN"'),
    ("Sekolah Rakyat", '"sekolah rakyat"'),
    ("Koperasi Desa Merah Putih", '"koperasi desa merah putih" OR "koperasi merah putih" OR "kopdes merah putih" OR "KDMP"'),
    ("Papua/ Separatisme", '"separatisme papua" OR "KKB papua" OR "OPM papua" OR "TPNPB"'),
    ("GAM/ Separatisme", '"gerakan aceh merdeka" OR "separatisme aceh" OR "GAM aceh"'),
    ("Terorisme/ Radikalisme", '"terorisme" OR "radikalisme" OR "densus 88" OR "BNPT"'),
    ("Swasembada Pangan, Energi, dan Air", '"swasembada pangan" OR "swasembada energi" OR "swasembada air" OR "ketahanan pangan"'),
    ("Layanan Kesehatan/ CKG", '"cek kesehatan gratis" OR "CKG" OR "pemeriksaan kesehatan gratis"'),
    ("Pencegahan/ Pemberantasan Korupsi", '"pemberantasan korupsi" OR "KPK" OR "antikorupsi" OR "pencegahan korupsi"'),
    ("Pemerataan Sosial/ BLT/ Kartu Sejahtera dll", '"BLT" OR "kartu sejahtera" OR "bantuan sosial" OR "bansos" OR "pengentasan kemiskinan"'),
    ("Reformasi Politik, Hukum, dan Birokrasi", '"reformasi hukum" OR "reformasi birokrasi" OR "reformasi politik"'),
    ("Pencegahan/ Pemberantasan Narkoba", '"pemberantasan narkoba" OR "BNN" OR "peredaran narkoba"'),
    ("Peningkatan ekonomi kreatif, seni budaya, dan prestasi olahraga", '"ekonomi kreatif" OR "seni budaya" OR "prestasi olahraga"'),
    ("Pemerataan ekonomi dan penguatan UMKM serta pembangunan IKN", '"UMKM" OR "IKN" OR "ibu kota nusantara" OR "pemerataan ekonomi"'),
    ("Hunian Layak dan Terjangkau", '"rumah subsidi" OR "hunian layak" OR "rumah terjangkau" OR "3 juta rumah"'),
    ("Hilirisasi dan Industrialisasi", '"hilirisasi" OR "industrialisasi" OR "hilirisasi nikel" OR "hilirisasi tambang"'),
    ("Penguatan Pendidikan, Sains, dan Teknologi", '"penguatan pendidikan" OR "riset dan teknologi" OR "sains dan teknologi" OR "pendidikan tinggi"'),
    ("Penguatan Pertahanan dan Keamanan Negara serta Hubungan Internasional", '"pertahanan negara" OR "keamanan negara" OR "hubungan internasional" OR "politik luar negeri"'),
    ("Penguatan Hak Perempuan, Anak, dan Penyandang Disabilitas", '"hak perempuan" OR "perlindungan anak" OR "penyandang disabilitas"'),
    ("Peningkatan Kesejahteraan Guru dan Dosen", '"kesejahteraan guru" OR "kesejahteraan dosen" OR "tunjangan guru" OR "gaji guru"'),
    ("Penguatan Narasi RUU KKS", '"RUU KKS" OR "RUU keamanan dan ketahanan siber"'),
    ("Pelestarian Lingkungan Hidup", '"lingkungan hidup" OR "pelestarian lingkungan" OR "perubahan iklim"'),
    ("Peningkatan Kesejahteraan Petani, Nelayan, dan Masyarakat Desa", '"kesejahteraan petani" OR "kesejahteraan nelayan" OR "masyarakat desa" OR "dana desa"'),
    ("Penguatan Narasi Keamanan Siber dan Sandi", '"keamanan siber" OR "BSSN" OR "sandi negara" OR "serangan siber"'),
    ("Konflik Iran dan Amerika Serikat", '"konflik Iran Amerika" OR "Iran Amerika Serikat" OR "ketegangan Iran AS"'),
]


def seed_fixed_topics(db_path: Optional[str] = None) -> None:
    """Isi 25 topik fixed kalau belum ada (dicek berdasarkan title, category='tetap')."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    existing_titles = {
        row["title"] for row in cursor.execute("SELECT title FROM topics WHERE category = 'tetap'").fetchall()
    }
    for title, search_query in FIXED_TOPICS:
        if title not in existing_titles:
            cursor.execute(
                "INSERT INTO topics (title, search_query, category) VALUES (?, ?, 'tetap')",
                (title, search_query),
            )
    conn.commit()
    conn.close()


def create_topic(db_path: Optional[str] = None, title: str = "", search_query: str = "", category: str = "custom") -> int:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO topics (title, search_query, category) VALUES (?, ?, ?)",
        (title.strip(), search_query.strip(), category.strip()),
    )
    topic_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return topic_id


def update_topic(
    db_path: Optional[str] = None,
    topic_id: int = 0,
    title: Optional[str] = None,
    search_query: Optional[str] = None,
) -> Optional[dict]:
    """Update judul dan/atau query sebuah topik. Field yang None tidak diubah."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    row = cursor.execute("SELECT id, title, search_query, category FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if not row:
        conn.close()
        return None

    new_title = title.strip() if title is not None and title.strip() else row["title"]
    new_query = search_query.strip() if search_query is not None and search_query.strip() else row["search_query"]
    cursor.execute(
        "UPDATE topics SET title = ?, search_query = ? WHERE id = ?",
        (new_title, new_query, topic_id),
    )
    conn.commit()
    updated = cursor.execute(
        "SELECT id, title, search_query, category FROM topics WHERE id = ?", (topic_id,)
    ).fetchone()
    conn.close()
    return dict(updated) if updated else None


def list_topics(db_path: Optional[str] = None, category: Optional[str] = None) -> List[dict]:
    conn = get_connection(db_path)
    if category:
        rows = conn.execute(
            "SELECT id, title, search_query, category FROM topics WHERE category = ? ORDER BY id DESC",
            (category,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, title, search_query, category FROM topics ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_topic(db_path: Optional[str] = None, topic_id: int = 0) -> Optional[dict]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT id, title, search_query, category FROM topics WHERE id = ?", (topic_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_content_plan(db_path: Optional[str] = None, date_value: str = "", slot: str = "", selected_topic_ids: Optional[list] = None) -> int:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO content_plans (date_value, slot) VALUES (?, ?)",
        (date_value.strip(), slot.strip()),
    )
    plan_id = cursor.lastrowid

    for topic_id in selected_topic_ids or []:
        cursor.execute(
            "INSERT INTO content_plan_topics (plan_id, topic_id) VALUES (?, ?)",
            (plan_id, int(topic_id)),
        )

    conn.commit()
    conn.close()
    return plan_id


def list_content_plans(db_path: Optional[str] = None) -> List[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT cp.id, cp.date_value, cp.slot, cp.created_at,
               json_group_array(json_object('id', t.id, 'title', t.title, 'search_query', t.search_query)) AS topics_json
        FROM content_plans cp
        LEFT JOIN content_plan_topics cpt ON cpt.plan_id = cp.id
        LEFT JOIN topics t ON t.id = cpt.topic_id
        GROUP BY cp.id
        ORDER BY cp.date_value DESC, cp.slot ASC
        """
    ).fetchall()
    conn.close()

    plans = []
    for row in rows:
        topics = []
        raw_topics = row["topics_json"]
        if raw_topics:
            topics = json.loads(raw_topics)
        plans.append(
            {
                "id": row["id"],
                "date_value": row["date_value"],
                "slot": row["slot"],
                "created_at": row["created_at"],
                "topics": topics if isinstance(topics, list) else [],
            }
        )
    return plans


# ---------------------------------------------------------------------------
# News items (hasil automatic search)
# ---------------------------------------------------------------------------

def save_news_items(db_path: Optional[str] = None, topic_id: int = 0, items: Optional[list] = None) -> List[int]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    saved_ids = []
    for item in items or []:
        cursor.execute(
            """
            INSERT INTO news_items (topic_id, title, source, url, published_at, snippet)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                topic_id,
                item.get("title", ""),
                item.get("source", ""),
                item.get("url", ""),
                item.get("published_at", ""),
                item.get("snippet", ""),
            ),
        )
        saved_ids.append(cursor.lastrowid)
    conn.commit()
    conn.close()
    return saved_ids


def list_news_items(db_path: Optional[str] = None, topic_id: Optional[int] = None) -> List[dict]:
    conn = get_connection(db_path)
    if topic_id:
        rows = conn.execute(
            "SELECT * FROM news_items WHERE topic_id = ? ORDER BY fetched_at DESC", (topic_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM news_items ORDER BY fetched_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_news_items_by_ids(db_path: Optional[str] = None, news_item_ids: Optional[list] = None) -> List[dict]:
    if not news_item_ids:
        return []
    conn = get_connection(db_path)
    placeholders = ",".join("?" for _ in news_item_ids)
    rows = conn.execute(
        f"SELECT * FROM news_items WHERE id IN ({placeholders})", news_item_ids
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Analyses (hasil analisis + rekomendasi tindakan & angle)
# ---------------------------------------------------------------------------

def create_analysis(db_path: Optional[str] = None, **fields) -> int:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO analyses (
            topic_id, news_item_ids, sentiment, dominant_narrative, risk_level,
            summary, recommended_action, action_reasoning, suggested_angles, details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields["topic_id"],
            json.dumps(fields.get("news_item_ids", [])),
            fields["sentiment"],
            fields["dominant_narrative"],
            fields["risk_level"],
            fields["summary"],
            fields["recommended_action"],
            fields["action_reasoning"],
            json.dumps(fields.get("suggested_angles", [])),
            json.dumps(fields.get("details", {}), ensure_ascii=False),
        ),
    )
    analysis_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return analysis_id


def get_analysis(db_path: Optional[str] = None, analysis_id: int = 0) -> Optional[dict]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    data["news_item_ids"] = json.loads(data["news_item_ids"] or "[]")
    data["suggested_angles"] = json.loads(data["suggested_angles"] or "[]")
    data["details"] = json.loads(data.get("details") or "{}")
    return data


def list_analyses(db_path: Optional[str] = None, topic_id: Optional[int] = None) -> List[dict]:
    conn = get_connection(db_path)
    if topic_id:
        rows = conn.execute(
            "SELECT * FROM analyses WHERE topic_id = ? ORDER BY created_at DESC", (topic_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM analyses ORDER BY created_at DESC").fetchall()
    conn.close()
    results = []
    for row in rows:
        data = dict(row)
        data["news_item_ids"] = json.loads(data["news_item_ids"] or "[]")
        data["suggested_angles"] = json.loads(data["suggested_angles"] or "[]")
        data["details"] = json.loads(data.get("details") or "{}")
        results.append(data)
    return results


# ---------------------------------------------------------------------------
# Content items (visual concept, deskripsi, caption)
# ---------------------------------------------------------------------------

def create_content_item(db_path: Optional[str] = None, **fields) -> int:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO content_items (
            analysis_id, action_taken, angle, content_form, aspect_ratio, visual_concept,
            description, captions, fact_sources, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields["analysis_id"],
            fields["action_taken"],
            fields["angle"],
            fields["content_form"],
            fields.get("aspect_ratio", "1:1"),
            fields.get("visual_concept", ""),
            fields.get("description", ""),
            json.dumps(fields.get("captions", [])),
            json.dumps(fields.get("fact_sources", [])),
            fields.get("status", "draft"),
        ),
    )
    content_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return content_id


def update_content_item(db_path: Optional[str] = None, content_item_id: int = 0, **fields) -> Optional[dict]:
    """Update sebagian kolom content_item (visual_concept, description, captions, status)."""
    allowed = {"visual_concept", "description", "captions", "status", "action_taken", "angle"}
    sets = []
    values = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "captions":
            value = json.dumps(value or [])
        sets.append(f"{key} = ?")
        values.append(value)
    if not sets:
        return get_content_item(db_path=db_path, content_item_id=content_item_id)

    conn = get_connection(db_path)
    cursor = conn.cursor()
    values.append(content_item_id)
    cursor.execute(f"UPDATE content_items SET {', '.join(sets)} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return get_content_item(db_path=db_path, content_item_id=content_item_id)


def list_content_items(db_path: Optional[str] = None) -> List[dict]:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM content_items ORDER BY created_at DESC").fetchall()
    conn.close()
    results = []
    for row in rows:
        data = dict(row)
        data["captions"] = json.loads(data["captions"] or "[]")
        data["fact_sources"] = json.loads(data["fact_sources"] or "[]")
        results.append(data)
    return results


def get_content_item(db_path: Optional[str] = None, content_item_id: int = 0) -> Optional[dict]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM content_items WHERE id = ?", (content_item_id,)).fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    data["captions"] = json.loads(data["captions"] or "[]")
    data["fact_sources"] = json.loads(data["fact_sources"] or "[]")
    return data


# ---------------------------------------------------------------------------
# Reports (laporan ke pimpinan)
# ---------------------------------------------------------------------------

def create_report(db_path: Optional[str] = None, content_item_id: int = 0, production_date: str = "", posting_link: str = "") -> int:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO reports (content_item_id, production_date, posting_link) VALUES (?, ?, ?)",
        (content_item_id, production_date, posting_link),
    )
    report_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return report_id


def list_reports(db_path: Optional[str] = None) -> List[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT r.id, r.production_date, r.posting_link, r.status, r.created_at,
               ci.content_form, ci.action_taken, ci.angle, ci.description, ci.visual_concept,
               a.topic_id
        FROM reports r
        JOIN content_items ci ON ci.id = r.content_item_id
        JOIN analyses a ON a.id = ci.analysis_id
        ORDER BY r.production_date DESC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
