"""
Modul automatic search berita.

Menggunakan Google News RSS (tidak butuh API key) dengan query yang sudah
disiapkan per topik (kolom `search_query`, misal: "mbg" OR "makan bergizi gratis").
Hasil difilter untuk 24 jam terakhir (`when:1d`).

Kalau nanti mau pindah ke provider berbayar (NewsAPI, GNews, dsb), cukup
ganti isi fungsi `fetch_news_for_topic` tanpa mengubah kontrak (tetap
mengembalikan list of dict dengan key: title, source, url, published_at, snippet).
"""
import urllib.parse
import xml.etree.ElementTree as ET

import requests

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
DEFAULT_TIMEOUT_SECONDS = 10


def build_query(search_query: str, window: str = "when:1d") -> str:
    """Gabungkan query topik (mis. '"mbg" OR "makan bergizi gratis"') dengan filter waktu."""
    query = search_query.strip()
    if window and window not in query:
        query = f"{query} {window}"
    return query


def fetch_news_for_topic(search_query: str, max_results: int = 10) -> list:
    """
    Ambil berita 24 jam terakhir dari Google News RSS berdasarkan query topik.
    Mengembalikan list kosong (bukan exception) kalau request gagal, supaya
    endpoint tetap bisa merespons dan user bisa input manual sebagai fallback.
    """
    query = build_query(search_query)
    params = {"q": query, "hl": "id", "gl": "ID", "ceid": "ID:id"}
    url = f"{GOOGLE_NEWS_RSS_URL}?{urllib.parse.urlencode(params)}"

    try:
        response = requests.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException:
        return []

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        return []

    items = []
    for item in root.findall(".//item")[:max_results]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        description = (item.findtext("description") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else ""

        items.append(
            {
                "title": title,
                "source": source,
                "url": link,
                "published_at": pub_date,
                "snippet": description,
            }
        )

    return items
