import os

from dotenv import load_dotenv

load_dotenv()  # baca backend/.env (GEMINI_API_KEY, dll) sebelum modul lain diimpor

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional

from app.database import (
    create_analysis,
    create_content_item,
    create_topic,
    get_analysis,
    get_content_item,
    get_news_items_by_ids,
    get_topic,
    init_db,
    list_analyses,
    list_content_items,
    list_news_items,
    list_topics,
    save_news_items,
    seed_fixed_topics,
    update_content_item,
    update_topic,
)
from app.ai_service import (
    ALLOWED_ASPECT_RATIOS,
    generate_analysis,
    generate_captions,
    generate_description,
    generate_visual,
)
from app.news_search import fetch_news_for_topic

app = FastAPI(title="Content Automation API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
seed_fixed_topics()

GENERATED_CONTENT_DIR = os.path.join(os.path.dirname(__file__), "generated_content")
os.makedirs(GENERATED_CONTENT_DIR, exist_ok=True)
app.mount("/generated_content", StaticFiles(directory=GENERATED_CONTENT_DIR), name="generated_content")


class TopicPayload(BaseModel):
    title: str
    search_query: str
    category: str = "custom"  # 'tetap' (25 topik baku) atau 'custom' (topik bebas)


class TopicUpdatePayload(BaseModel):
    title: Optional[str] = None
    search_query: Optional[str] = None


class AnalysisPayload(BaseModel):
    topic_id: int
    news_item_ids: List[int]


class VisualPayload(BaseModel):
    analysis_id: int
    action_taken: str  # 'amplifikasi' atau 'klarifikasi_fakta'
    angle: str
    content_form: str  # poster / infografis / komik / postingan
    aspect_ratio: str = "1:1"  # 1:1 / 3:4 / 9:16 / 16:9
    fact_sources: Optional[List[str]] = None
    tindakan: Optional[str] = None
    gaya_bahasa: Optional[str] = None


class CaptionPayload(BaseModel):
    analysis_id: int
    action_taken: str
    angle: str
    caption_count: int = 100
    fact_sources: Optional[List[str]] = None
    tindakan: Optional[str] = None
    gaya_bahasa: Optional[str] = None
    content_id: Optional[int] = None  # kalau diisi, caption disimpan ke content_item ini


class DescriptionPayload(BaseModel):
    content_id: int  # deskripsi hanya bisa dibuat setelah media visual ada


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 1. Topik — 25 topik fixed (category='tetap') + topik custom (category='custom')
# ---------------------------------------------------------------------------

@app.get("/topics")
def get_topics(category: Optional[str] = None):
    return list_topics(category=category)


@app.post("/topics")
def add_topic(payload: TopicPayload):
    topic_id = create_topic(title=payload.title, search_query=payload.search_query, category=payload.category)
    return {"id": topic_id, "title": payload.title, "search_query": payload.search_query, "category": payload.category}


@app.put("/topics/{topic_id}")
def edit_topic(topic_id: int, payload: TopicUpdatePayload):
    updated = update_topic(topic_id=topic_id, title=payload.title, search_query=payload.search_query)
    if not updated:
        raise HTTPException(status_code=404, detail="Topik tidak ditemukan")
    return updated


# ---------------------------------------------------------------------------
# 2. Automatic search berita (per topik, 24 jam terakhir)
# ---------------------------------------------------------------------------

@app.post("/topics/{topic_id}/search-news")
def search_news_for_topic(topic_id: int):
    topic = get_topic(topic_id=topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topik tidak ditemukan")

    news_items = fetch_news_for_topic(topic["search_query"])
    saved_ids = save_news_items(topic_id=topic_id, items=news_items)
    return {"topic_id": topic_id, "found": len(news_items), "saved_ids": saved_ids}


@app.get("/topics/{topic_id}/news")
def get_news_for_topic(topic_id: int):
    return list_news_items(topic_id=topic_id)


# ---------------------------------------------------------------------------
# 4-5. Analisis berita + rekomendasi tindakan & angle
# ---------------------------------------------------------------------------

@app.post("/analysis")
def run_analysis(payload: AnalysisPayload):
    topic = get_topic(topic_id=payload.topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topik tidak ditemukan")

    news_items = get_news_items_by_ids(news_item_ids=payload.news_item_ids)
    if not news_items:
        raise HTTPException(status_code=400, detail="Pilih minimal satu berita untuk dianalisis")

    result = generate_analysis(topic_title=topic["title"], news_items=news_items)

    analysis_id = create_analysis(
        topic_id=payload.topic_id,
        news_item_ids=payload.news_item_ids,
        **result,
    )
    return {"id": analysis_id, **result}


@app.get("/analysis")
def get_analyses(topic_id: Optional[int] = None):
    return list_analyses(topic_id=topic_id)


# ---------------------------------------------------------------------------
# 6. Generasi konten — DIPISAH per tombol:
#    a. /content/visual      -> Media Visual (gambar jadi) DIBUAT DULUAN
#    b. /content/caption     -> Caption (bisa bareng visual, tombol berbeda)
#    c. /content/description -> Deskripsi Penjelas (hanya setelah visual ada)
# ---------------------------------------------------------------------------

@app.get("/content-options")
def get_content_options():
    return {"aspect_ratios": ALLOWED_ASPECT_RATIOS}


def _load_analysis_or_404(analysis_id: int):
    analysis = get_analysis(analysis_id=analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analisis tidak ditemukan")
    topic = get_topic(topic_id=analysis["topic_id"])
    return analysis, (topic["title"] if topic else "")


@app.post("/content/visual")
def create_visual(payload: VisualPayload):
    analysis, topic_title = _load_analysis_or_404(payload.analysis_id)

    if payload.aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        raise HTTPException(status_code=400, detail=f"aspect_ratio harus salah satu dari {ALLOWED_ASPECT_RATIOS}")

    try:
        result = generate_visual(
            topic_title=topic_title,
            analysis=analysis,
            content_form=payload.content_form,
            action_taken=payload.action_taken,
            angle=payload.angle,
            aspect_ratio=payload.aspect_ratio,
            tindakan=payload.tindakan,
            gaya_bahasa=payload.gaya_bahasa,
            fact_sources=payload.fact_sources,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    content_id = create_content_item(
        analysis_id=payload.analysis_id,
        action_taken=payload.action_taken,
        angle=payload.angle,
        content_form=payload.content_form,
        aspect_ratio=payload.aspect_ratio,
        fact_sources=payload.fact_sources or [],
        visual_concept=result["visual_concept"],
        description="",
        captions=[],
        status="visual",
    )
    return {"id": content_id, "content_id": content_id, "aspect_ratio": payload.aspect_ratio, **result}


@app.post("/content/caption")
def create_caption(payload: CaptionPayload):
    analysis, topic_title = _load_analysis_or_404(payload.analysis_id)

    try:
        result = generate_captions(
            topic_title=topic_title,
            analysis=analysis,
            action_taken=payload.action_taken,
            angle=payload.angle,
            caption_count=payload.caption_count,
            tindakan=payload.tindakan,
            gaya_bahasa=payload.gaya_bahasa,
            fact_sources=payload.fact_sources,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if payload.content_id:
        if not get_content_item(content_item_id=payload.content_id):
            raise HTTPException(status_code=404, detail="Konten (visual) tidak ditemukan")
        update_content_item(content_item_id=payload.content_id, captions=result["captions"])

    return {"content_id": payload.content_id, **result}


@app.post("/content/description")
def create_description(payload: DescriptionPayload):
    content = get_content_item(content_item_id=payload.content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Konten tidak ditemukan. Buat Media Visual dulu.")

    visual_concept = content.get("visual_concept") or ""
    if not visual_concept:
        raise HTTPException(status_code=400, detail="Media Visual harus dibuat lebih dulu sebelum deskripsi.")

    analysis, topic_title = _load_analysis_or_404(content["analysis_id"])

    result = generate_description(
        topic_title=topic_title,
        analysis=analysis,
        content_form=content["content_form"],
        action_taken=content["action_taken"],
        angle=content["angle"],
        visual_prompt=visual_concept,
        fact_sources=content.get("fact_sources") or [],
    )
    update_content_item(content_item_id=payload.content_id, description=result["description"], status="complete")
    return {"content_id": payload.content_id, **result}


@app.get("/content")
def get_content_items():
    return list_content_items()
