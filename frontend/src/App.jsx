import { useEffect, useRef, useState } from 'react';
import './App.css';

const API_URL = 'http://127.0.0.1:8000';
const ASPECT_RATIOS = ['1:1', '3:4', '9:16', '16:9'];

const ESCALATION_META = {
  'VERY LOW': { label: 'Very Low', className: 'esc-verylow' },
  LOW: { label: 'Low', className: 'esc-low' },
  MEDIUM: { label: 'Medium', className: 'esc-medium' },
  HIGH: { label: 'High', className: 'esc-high' },
  'VERY HIGH': { label: 'Very High', className: 'esc-veryhigh' },
};

function App() {
  const [topics, setTopics] = useState([]);
  const [title, setTitle] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [message, setMessage] = useState('');
  const [activeTab, setActiveTab] = useState('overview');

  // --- edit query topik ---
  const [editingTopicId, setEditingTopicId] = useState(null);
  const [editingQuery, setEditingQuery] = useState('');

  // --- state alur berita -> analisis -> konten ---
  const [newsTopicId, setNewsTopicId] = useState('');
  const [newsItems, setNewsItems] = useState([]);
  const [selectedNewsIds, setSelectedNewsIds] = useState([]);
  const [searching, setSearching] = useState(false);

  const [analyses, setAnalyses] = useState([]);
  const [latestAnalysis, setLatestAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);

  const [contentForm, setContentForm] = useState('poster');
  const [chosenAngle, setChosenAngle] = useState('');
  const [aspectRatio, setAspectRatio] = useState('1:1');
  const [factSourcesText, setFactSourcesText] = useState('');
  const [contentItems, setContentItems] = useState([]);
  const [tindakan, setTindakan] = useState('kontra narasi');
  const [gayaBahasa, setGayaBahasa] = useState('Netral');
  const [jumlahKomentar, setJumlahKomentar] = useState(100);

  // --- output konten (3 tombol terpisah) ---
  const [currentVisual, setCurrentVisual] = useState(null); // { content_id, visual_concept, image_url, image_error }
  const [currentCaptions, setCurrentCaptions] = useState(null);
  const [currentDescription, setCurrentDescription] = useState(null);
  const [generatingVisual, setGeneratingVisual] = useState(false);
  const [generatingCaption, setGeneratingCaption] = useState(false);
  const [generatingDescription, setGeneratingDescription] = useState(false);

  // --- progress bar per proses generate ---
  const [progress, setProgress] = useState({ visual: 0, caption: 0, description: 0 });
  const [progressStage, setProgressStage] = useState({ visual: '', caption: '', description: '' });
  const progressTimers = useRef({});

  const PROGRESS_STAGES = {
    visual: [
      [0, 'Menyusun brief visual dari hasil analisis...'],
      [40, 'Mengirim ke model gambar & merender...'],
      [75, 'Menyelesaikan gambar...'],
    ],
    caption: [
      [0, 'Menyiapkan konteks analisis...'],
      [45, 'Menulis variasi caption...'],
    ],
    description: [
      [0, 'Membaca visual & analisis...'],
      [50, 'Menulis deskripsi penjelas...'],
    ],
  };

  const stageFor = (key, value) => {
    const stages = PROGRESS_STAGES[key] || [];
    let label = '';
    for (const [threshold, text] of stages) {
      if (value >= threshold) label = text;
    }
    return label;
  };

  const startProgress = (key) => {
    clearInterval(progressTimers.current[key]);
    setProgress((p) => ({ ...p, [key]: 5 }));
    setProgressStage((s) => ({ ...s, [key]: stageFor(key, 5) }));
    progressTimers.current[key] = setInterval(() => {
      setProgress((p) => {
        const cur = p[key];
        if (cur >= 92) return p;
        const inc = cur < 40 ? 3.5 : cur < 70 ? 1.6 : 0.7; // melambat saat mendekati akhir
        const next = Math.min(92, cur + inc);
        setProgressStage((s) => ({ ...s, [key]: stageFor(key, next) }));
        return { ...p, [key]: next };
      });
    }, 280);
  };

  const finishProgress = (key, ok = true) => {
    clearInterval(progressTimers.current[key]);
    setProgress((p) => ({ ...p, [key]: 100 }));
    setProgressStage((s) => ({ ...s, [key]: ok ? 'Selesai ✔' : 'Gagal' }));
    setTimeout(() => {
      setProgress((p) => ({ ...p, [key]: 0 }));
      setProgressStage((s) => ({ ...s, [key]: '' }));
    }, 900);
  };

  useEffect(() => () => {
    Object.values(progressTimers.current).forEach(clearInterval);
  }, []);

  const loadData = async () => {
    const [topicsRes, contentRes] = await Promise.all([
      fetch(`${API_URL}/topics`),
      fetch(`${API_URL}/content`),
    ]);
    setTopics(await topicsRes.json());
    setContentItems(await contentRes.json());
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleTopicSubmit = async (e) => {
    e.preventDefault();
    const res = await fetch(`${API_URL}/topics`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, search_query: searchQuery, category: 'custom' }),
    });
    const data = await res.json();
    setMessage(`Topik disimpan: ${data.title}`);
    setTitle('');
    setSearchQuery('');
    loadData();
  };

  // --- 1. Edit query topik ---
  const startEditQuery = (topic) => {
    setEditingTopicId(topic.id);
    setEditingQuery(topic.search_query);
  };

  const cancelEditQuery = () => {
    setEditingTopicId(null);
    setEditingQuery('');
  };

  const saveEditQuery = async (topicId) => {
    const res = await fetch(`${API_URL}/topics/${topicId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ search_query: editingQuery }),
    });
    if (!res.ok) {
      setMessage('Gagal menyimpan query topik');
      return;
    }
    setMessage('Query topik diperbarui.');
    cancelEditQuery();
    loadData();
  };

  // --- 2. Automatic search berita ---
  const handleSearchNews = async () => {
    if (!newsTopicId) {
      setMessage('Pilih topik dulu sebelum mencari berita');
      return;
    }
    setSearching(true);
    setMessage('');
    try {
      await fetch(`${API_URL}/topics/${newsTopicId}/search-news`, { method: 'POST' });
      const res = await fetch(`${API_URL}/topics/${newsTopicId}/news`);
      const data = await res.json();
      setNewsItems(data);
      setSelectedNewsIds([]);
      if (data.length === 0) {
        setMessage('Tidak ada berita ditemukan dalam 24 jam terakhir. Kamu bisa cek manual dulu, atau coba lagi nanti.');
      }
    } finally {
      setSearching(false);
    }
  };

  const toggleNewsItem = (id) => {
    setSelectedNewsIds((prev) => (prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id]));
  };

  const handleSelectAllNews = () => {
    if (newsItems.length === 0) return;
    if (selectedNewsIds.length === newsItems.length) {
      setSelectedNewsIds([]);
    } else {
      setSelectedNewsIds(newsItems.map((item) => item.id));
    }
  };

  // --- 4-5. Analisis + rekomendasi tindakan & angle ---
  const handleRunAnalysis = async () => {
    if (selectedNewsIds.length === 0) {
      setMessage('Pilih minimal satu berita untuk dianalisis');
      return;
    }
    setAnalyzing(true);
    setMessage('');
    try {
      const res = await fetch(`${API_URL}/analysis`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic_id: Number(newsTopicId), news_item_ids: selectedNewsIds }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || 'Gagal menjalankan analisis');
        return;
      }
      setLatestAnalysis(data);
      setChosenAngle(data.suggested_angles[0] || '');
      // reset output konten karena analisis berganti
      setCurrentVisual(null);
      setCurrentCaptions(null);
      setCurrentDescription(null);
      const analysesRes = await fetch(`${API_URL}/analysis?topic_id=${newsTopicId}`);
      setAnalyses(await analysesRes.json());
    } finally {
      setAnalyzing(false);
    }
  };

  const currentActionTaken = tindakan === 'kontra narasi' ? 'klarifikasi_fakta' : 'amplifikasi';

  const buildContentPayloadBase = () => {
    const fact_sources = factSourcesText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    return {
      action_taken: currentActionTaken,
      angle: chosenAngle,
      fact_sources,
      tindakan,
      gaya_bahasa: gayaBahasa,
    };
  };

  // --- 6a. Generate MEDIA VISUAL (dibuat duluan, mengacu hasil analisis) ---
  const handleGenerateVisual = async () => {
    if (!latestAnalysis) {
      setMessage('Jalankan analisis dulu sebelum generate konten');
      return;
    }
    if (currentActionTaken === 'klarifikasi_fakta' && !factSourcesText.trim()) {
      setMessage('Klarifikasi fakta wajib diisi sumber/data resmi dulu');
      return;
    }
    setGeneratingVisual(true);
    setMessage('');
    startProgress('visual');
    let visualOk = false;
    try {
      const res = await fetch(`${API_URL}/content/visual`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          analysis_id: latestAnalysis.id,
          content_form: contentForm,
          aspect_ratio: aspectRatio,
          ...buildContentPayloadBase(),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || 'Gagal generate media visual');
        return;
      }
      setCurrentVisual(data);
      // caption & deskripsi lama tidak berlaku untuk visual baru
      setCurrentCaptions(null);
      setCurrentDescription(null);
      if (data.image_error) {
        setMessage(`Media visual dibuat, tapi GAMBAR gagal: ${data.image_error}`);
      } else {
        setMessage('Media visual (gambar) berhasil dibuat.');
      }
      visualOk = !data.image_error;
      loadData();
    } finally {
      finishProgress('visual', visualOk);
      setGeneratingVisual(false);
    }
  };

  // --- 6b. Generate CAPTION (tombol berbeda, logika sama: mengacu analisis) ---
  const handleGenerateCaption = async () => {
    if (!latestAnalysis) {
      setMessage('Jalankan analisis dulu sebelum generate caption');
      return;
    }
    if (currentActionTaken === 'klarifikasi_fakta' && !factSourcesText.trim()) {
      setMessage('Klarifikasi fakta wajib diisi sumber/data resmi dulu');
      return;
    }
    setGeneratingCaption(true);
    setMessage('');
    startProgress('caption');
    let captionOk = false;
    try {
      const normalizedCommentCount = Math.min(100, Math.max(1, Number(jumlahKomentar) || 1));
      const res = await fetch(`${API_URL}/content/caption`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          analysis_id: latestAnalysis.id,
          caption_count: normalizedCommentCount,
          content_id: currentVisual?.content_id || null,
          ...buildContentPayloadBase(),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || 'Gagal generate caption');
        return;
      }
      setCurrentCaptions(data.captions);
      setMessage('Caption berhasil dibuat.');
      captionOk = true;
      loadData();
    } finally {
      finishProgress('caption', captionOk);
      setGeneratingCaption(false);
    }
  };

  // --- 6c. Generate DESKRIPSI (hanya setelah media visual ada) ---
  const handleGenerateDescription = async () => {
    if (!currentVisual?.content_id) {
      setMessage('Buat Media Visual dulu sebelum deskripsi konten');
      return;
    }
    setGeneratingDescription(true);
    setMessage('');
    startProgress('description');
    let descOk = false;
    try {
      const res = await fetch(`${API_URL}/content/description`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content_id: currentVisual.content_id }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || 'Gagal generate deskripsi');
        return;
      }
      setCurrentDescription(data.description);
      setMessage('Deskripsi penjelas berhasil dibuat.');
      descOk = true;
      loadData();
    } finally {
      finishProgress('description', descOk);
      setGeneratingDescription(false);
    }
  };

  const fixedTopics = topics.filter((t) => t.category === 'tetap');
  const customTopics = topics.filter((t) => t.category !== 'tetap');

  const getImageUrl = (visualConcept, imageUrl) => {
    if (imageUrl) {
      return { url: imageUrl, filename: imageUrl.split('/').pop() };
    }
    if (visualConcept && visualConcept.startsWith('IMAGE::')) {
      const filename = visualConcept.replace('IMAGE::', '');
      return { url: `${API_URL}/generated_content/${filename}`, filename };
    }
    return null;
  };

  const handleDownloadImage = async (url, filename) => {
    try {
      const res = await fetch(url);
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
    } catch {
      setMessage('Gagal download gambar, coba klik kanan pada gambar lalu "Save Image As"');
    }
  };

  const renderVisual = (visualConcept, imageUrl) => {
    const image = getImageUrl(visualConcept, imageUrl);
    if (image) {
      return (
        <div className="visual-preview">
          <img className="generated-image" src={image.url} alt="Konsep visual" />
          <button type="button" className="download-btn" onClick={() => handleDownloadImage(image.url, image.filename)}>
            ⬇ Download Gambar
          </button>
        </div>
      );
    }
    return <p className="muted-text">{visualConcept}</p>;
  };

  const renderTopicItem = (topic) => {
    const isEditing = editingTopicId === topic.id;
    return (
      <div key={topic.id} className="topic-item">
        <strong>
          {topic.title}{' '}
          <span className="badge">{topic.category === 'tetap' ? 'Tetap' : 'Custom'}</span>
        </strong>
        {isEditing ? (
          <div className="query-edit">
            <textarea rows="2" value={editingQuery} onChange={(e) => setEditingQuery(e.target.value)} />
            <div className="query-edit-actions">
              <button type="button" className="mini-btn primary" onClick={() => saveEditQuery(topic.id)}>Simpan</button>
              <button type="button" className="mini-btn" onClick={cancelEditQuery}>Batal</button>
            </div>
          </div>
        ) : (
          <div className="query-row">
            <code className="query-text">{topic.search_query}</code>
            <button type="button" className="mini-btn" onClick={() => startEditQuery(topic)}>✎ Edit Query</button>
          </div>
        )}
      </div>
    );
  };

  const details = latestAnalysis?.details || {};
  const escalationLevel = details.escalation_level;
  const escalationMeta = ESCALATION_META[escalationLevel] || { label: escalationLevel || '-', className: '' };

  return (
    <div className="app-shell">
      <div className="app-content">
        <section className="hero-card">
          <div>
            <p className="eyebrow">Content Ops Dashboard</p>
            <h1>Automasi riset & konten komunikasi publik.</h1>
            <p>Cari berita 24 jam terakhir, jalankan analisis eskalasi, dan generate draf konten resmi (visual, deskripsi, caption) — didukung Gemini.</p>
          </div>
          <div className="hero-badge">
            <div>Realtime</div>
            <strong>Neon Ready</strong>
          </div>
        </section>

        <div className="tabs">
          <button className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Overview</button>
          <button className={`tab-btn ${activeTab === 'topics' ? 'active' : ''}`} onClick={() => setActiveTab('topics')}>Topik</button>
          <button className={`tab-btn ${activeTab === 'news' ? 'active' : ''}`} onClick={() => setActiveTab('news')}>Cari Berita</button>
          <button className={`tab-btn ${activeTab === 'analysis' ? 'active' : ''}`} onClick={() => setActiveTab('analysis')}>Analisis</button>
          <button className={`tab-btn ${activeTab === 'content' ? 'active' : ''}`} onClick={() => setActiveTab('content')}>Generate Konten</button>
        </div>

        {message && <div className={`status ${message.toLowerCase().includes('gagal') ? 'error' : 'success'}`}>{message}</div>}

        {activeTab === 'overview' && (
          <div className="dashboard-grid">
            <div className="panel">
              <h2>Ringkasan sistem</h2>
              <div className="metric-list">
                <div className="metric-card"><span>Topik tetap</span><span className="metric-value">{fixedTopics.length}</span></div>
                <div className="metric-card"><span>Topik custom</span><span className="metric-value">{customTopics.length}</span></div>
                <div className="metric-card"><span>Konten dibuat</span><span className="metric-value">{contentItems.length}</span></div>
              </div>
            </div>
            <div className="panel">
              <h3>Konten terbaru</h3>
              {contentItems.length === 0 ? <p>Belum ada konten.</p> : (
                <div className="topic-list">
                  {contentItems.slice(0, 5).map((c) => (
                    <div key={c.id} className="topic-item">
                      <strong>#{c.id} · {c.content_form} ({c.aspect_ratio})</strong>
                      <span>{c.angle}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'topics' && (
          <div className="form-grid">
            <div className="panel">
              <h3>Tambah topik custom</h3>
              <p className="hint">25 topik baku (17 program prioritas + 8 quick win) sudah otomatis tersedia. Judulnya tetap, tapi <strong>query tiap topik bisa kamu edit</strong> di daftar sebelah. Form ini untuk topik tambahan di luar 25 itu.</p>
              <form onSubmit={handleTopicSubmit}>
                <div className="field">
                  <label>Judul topik</label>
                  <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Contoh: Isu Kenaikan Harga Beras" required />
                </div>
                <div className="field">
                  <label>Query pencarian (boolean)</label>
                  <input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder='Contoh: "harga beras" OR "beras mahal"' required />
                </div>
                <button className="primary-btn" type="submit">Simpan Topik</button>
              </form>
            </div>
            <div className="panel">
              <h3>Daftar topik</h3>
              <p className="hint">Klik <strong>Edit Query</strong> untuk menyesuaikan kata kunci pencarian tanpa mengubah judul topik.</p>
              <h4>Tetap (25 topik baku)</h4>
              <div className="topic-list">
                {fixedTopics.map(renderTopicItem)}
              </div>
              <h4>Custom</h4>
              {customTopics.length === 0 ? <p>Belum ada topik custom.</p> : (
                <div className="topic-list">
                  {customTopics.map(renderTopicItem)}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'news' && (
          <div className="form-grid">
            <div className="panel">
              <h3>2. Automatic Search Berita (24 jam terakhir)</h3>
              <div className="field">
                <label>Topik</label>
                <select value={newsTopicId} onChange={(e) => setNewsTopicId(e.target.value)}>
                  <option value="">-- pilih topik --</option>
                  {topics.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
                </select>
              </div>
              <button className="primary-btn" onClick={handleSearchNews} disabled={searching}>
                {searching ? 'Mencari...' : 'Cari Berita 24 Jam Terakhir'}
              </button>
              <p className="hint">Sumber: Google News RSS, otomatis pakai query yang sudah kamu simpan di topik ini. Kalau hasilnya kosong, boleh dicek manual dulu.</p>
            </div>
            <div className="panel">
              <h3>Hasil pencarian — pilih yang relevan untuk dianalisis</h3>
              {newsItems.length > 0 && (
                <button type="button" className="primary-btn" onClick={handleSelectAllNews}>
                  {selectedNewsIds.length === newsItems.length ? '❌ Batalkan Semua Pilihan' : '✅ Pilih Semua Berita'}
                </button>
              )}
              {newsItems.length === 0 ? <p>Belum ada hasil. Cari berita dulu di panel kiri.</p> : (
                <div className="topic-list">
                  {newsItems.map((item) => (
                    <label key={item.id} className="checkbox-row news-item">
                      <input type="checkbox" checked={selectedNewsIds.includes(item.id)} onChange={() => toggleNewsItem(item.id)} />
                      <span>
                        <strong>{item.title}</strong>
                        <br /><span className="muted-text">{item.source} · {item.published_at}</span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'analysis' && (
          <div className="analysis-tab">
            <div className="panel">
              <div className="analysis-head">
                <div>
                  <h3>4-5. Analisis & Eskalasi Pemberitaan</h3>
                  <p className="hint">Berdasarkan {selectedNewsIds.length} berita terpilih di tab "Cari Berita". Mengacu kerangka TAHAP &amp; DEFINISI ESKALASI (VERY LOW → VERY HIGH).</p>
                </div>
                <button className="primary-btn" onClick={handleRunAnalysis} disabled={analyzing}>
                  {analyzing ? 'Menganalisis...' : 'Jalankan Analisis'}
                </button>
              </div>

              {latestAnalysis && (
                <div className="analysis-grid">
                  <div className={`escalation-banner ${escalationMeta.className}`}>
                    <span className="escalation-label">Tahap Eskalasi</span>
                    <strong className="escalation-level">{escalationMeta.label}</strong>
                    {details.escalation_reasoning && <p>{details.escalation_reasoning}</p>}
                  </div>

                  <div className="analysis-card analysis-card-issue">
                    <h3>🔥 Ringkasan Isu</h3>
                    <p>{latestAnalysis.summary}</p>
                    <p className="muted-text"><strong>Narasi dominan:</strong> {latestAnalysis.dominant_narrative} · <strong>Sentimen:</strong> {latestAnalysis.sentiment} · <strong>Risiko:</strong> {latestAnalysis.risk_level}</p>
                  </div>

                  <div className="analysis-card analysis-card-action">
                    <h3>🎯 Rekomendasi Tindakan</h3>
                    <p><strong>{latestAnalysis.recommended_action === 'amplifikasi' ? 'Amplifikasi (Glorifikasi)' : 'Klarifikasi Fakta'}</strong></p>
                    <p>{latestAnalysis.action_reasoning}</p>
                  </div>

                  <div className="analysis-card analysis-card-angle">
                    <h3>📐 Angle yang Disarankan</h3>
                    <ul className="tight-list">
                      {(latestAnalysis.suggested_angles || []).map((a, i) => <li key={i}>{a}</li>)}
                    </ul>
                  </div>

                  {details.narrative_analysis && (
                    <div className="analysis-card grid-full">
                      <h3>🧭 Analisis Naratif</h3>
                      <p className="prewrap">{details.narrative_analysis}</p>
                    </div>
                  )}

                  {Array.isArray(details.escalation_table) && details.escalation_table.length > 0 && (
                    <div className="analysis-card grid-full">
                      <h3>🗂️ Tabel Eskalasi &amp; Saran Informasi</h3>
                      <div className="table-scroll">
                        <table className="escalation-table">
                          <thead>
                            <tr><th>TAHAP &amp; DEFINISI ESKALASI</th><th>ARTIKEL</th><th>SARAN INFORMASI</th></tr>
                          </thead>
                          <tbody>
                            {details.escalation_table.map((row, i) => {
                              const meta = ESCALATION_META[String(row.tahap).toUpperCase()] || { label: row.tahap, className: '' };
                              const artikel = row.artikel || [];
                              return (
                                <tr key={i}>
                                  <td className="esc-def-cell">
                                    <span className={`esc-chip ${meta.className}`}>{meta.label}</span>
                                    {row.tindakan && <p className="esc-tindakan"><strong>Tindakan:</strong> {row.tindakan}</p>}
                                    {row.definisi && <p className="esc-definisi">{row.definisi}</p>}
                                  </td>
                                  <td>
                                    {artikel.length > 0 ? (
                                      <ul className="tight-list">
                                        {artikel.map((a, j) => <li key={j}>{a}</li>)}
                                      </ul>
                                    ) : <span className="muted-text">—</span>}
                                  </td>
                                  <td className="prewrap">{row.saran_informasi || <span className="muted-text">—</span>}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {details.kontra_opini && (details.kontra_opini.judul || details.kontra_opini.isi) && (
                    <div className="analysis-card analysis-card-kontra grid-full">
                      <h3>📰 Draf Artikel Kontra Opini (tahap tertinggi)</h3>
                      {details.kontra_opini.judul && <h4>{details.kontra_opini.judul}</h4>}
                      <p className="prewrap">{details.kontra_opini.isi}</p>
                    </div>
                  )}

                  {details.generated_by && details.generated_by !== 'gemini' && (
                    <p className="muted-text grid-full">⚠️ Analisis dibuat mode fallback ({details.generated_by}). {details.ai_error || 'Pastikan GEMINI_API_KEY & nama model valid untuk analisis mendalam.'}</p>
                  )}
                </div>
              )}
            </div>

            <div className="panel">
              <h3>Riwayat analisis topik ini</h3>
              {analyses.length === 0 ? <p>Belum ada riwayat.</p> : (
                <div className="history-grid">
                  {analyses.map((a) => (
                    <div key={a.id} className="topic-item">
                      <strong>{(a.details?.escalation_level) || '-'} · {a.recommended_action === 'amplifikasi' ? 'Amplifikasi' : 'Klarifikasi Fakta'} · {a.sentiment}</strong>
                      <span>{a.summary}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'content' && (
          <div className="form-grid">
            <div className="panel">
              <h3>6. Generate Konten Otomatis</h3>
              {!latestAnalysis ? <p>Jalankan analisis dulu di tab "Analisis".</p> : (
                <>
                  <p className="hint">Alur: <strong>1) Media Visual dulu</strong> (gambar dibuat mengacu hasil analisis), lalu <strong>2) Caption</strong> &amp; <strong>3) Deskripsi</strong>. Deskripsi baru bisa dibuat setelah media visual ada.</p>
                  <div className="field">
                    <label>Pilihan Tindakan</label>
                    <select value={tindakan} onChange={(e) => setTindakan(e.target.value)}>
                      <option value="kontra narasi">Kontra Narasi</option>
                      <option value="amplifikasi">Amplifikasi Positif</option>
                    </select>
                  </div>
                  {tindakan === 'kontra narasi' && (
                    <div className="field">
                      <label>Gaya Bahasa Kontra Narasi</label>
                      <select value={gayaBahasa} onChange={(e) => setGayaBahasa(e.target.value)}>
                        <option value="Netral">Netral</option>
                        <option value="Offensive">Offensive</option>
                      </select>
                    </div>
                  )}
                  <div className="field">
                    <label>Angle</label>
                    <select value={chosenAngle} onChange={(e) => setChosenAngle(e.target.value)}>
                      {latestAnalysis.suggested_angles.map((a) => <option key={a} value={a}>{a}</option>)}
                    </select>
                  </div>
                  <div className="field">
                    <label>Bentuk konten</label>
                    <select value={contentForm} onChange={(e) => setContentForm(e.target.value)}>
                      <option value="poster">Poster</option>
                      <option value="infografis">Infografis</option>
                      <option value="komik">Komik</option>
                      <option value="postingan">Postingan (screenshot berita)</option>
                    </select>
                  </div>
                  <div className="field">
                    <label>Rasio visual</label>
                    <select value={aspectRatio} onChange={(e) => setAspectRatio(e.target.value)}>
                      {ASPECT_RATIOS.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </div>
                  {tindakan === 'kontra narasi' && (
                    <div className="field">
                      <label>Sumber/data resmi untuk klarifikasi (satu per baris, wajib diisi)</label>
                      <textarea rows="3" value={factSourcesText} onChange={(e) => setFactSourcesText(e.target.value)} placeholder="Contoh: Rilis resmi Kemenko, Data BPS 2026" />
                    </div>
                  )}
                  <div className="field">
                    <label>Jumlah Caption/Komentar (1-100)</label>
                    <input
                      type="number"
                      min="1"
                      max="100"
                      value={jumlahKomentar}
                      onChange={(e) => setJumlahKomentar(Math.min(100, Math.max(1, Number(e.target.value) || 1)))}
                    />
                  </div>

                  <div className="button-stack">
                    <button className="primary-btn step-btn" onClick={handleGenerateVisual} disabled={generatingVisual}>
                      {generatingVisual ? 'Membuat gambar...' : '1) 🖼️ Generate Media Visual'}
                    </button>
                    <button className="primary-btn step-btn secondary" onClick={handleGenerateCaption} disabled={generatingCaption}>
                      {generatingCaption ? 'Membuat caption...' : '2) 💬 Generate Caption'}
                    </button>
                    <button
                      className="primary-btn step-btn secondary"
                      onClick={handleGenerateDescription}
                      disabled={generatingDescription || !currentVisual?.content_id}
                      title={!currentVisual?.content_id ? 'Buat Media Visual dulu' : ''}
                    >
                      {generatingDescription ? 'Membuat deskripsi...' : '3) 📝 Generate Deskripsi Penjelas'}
                    </button>
                  </div>

                  {['visual', 'caption', 'description'].map((key) =>
                    progress[key] > 0 ? (
                      <div key={key} className="progress-wrap">
                        <div className="progress-head">
                          <span className="progress-name">
                            {key === 'visual' ? '🖼️ Media Visual' : key === 'caption' ? '💬 Caption' : '📝 Deskripsi'}
                            {progressStage[key] ? ` — ${progressStage[key]}` : ''}
                          </span>
                          <span className="progress-pct">{Math.round(progress[key])}%</span>
                        </div>
                        <div className="progress-track">
                          <div
                            className={`progress-fill ${progress[key] >= 100 ? 'done' : ''}`}
                            style={{ width: `${progress[key]}%` }}
                          />
                        </div>
                      </div>
                    ) : null
                  )}

                  {(currentVisual || currentCaptions || currentDescription) && (
                    <div className="generated-preview">
                      <h4>🖼️ Media Visual Konten</h4>
                      {currentVisual ? (
                        <>
                          <div className="visual-output-card">
                            {renderVisual(currentVisual.visual_concept, currentVisual.image_url)}
                          </div>
                          {currentVisual.image_error && (
                            <p className="status error">Gambar gagal dibuat: {currentVisual.image_error}</p>
                          )}
                        </>
                      ) : <p className="muted-text">Belum dibuat.</p>}

                      <h4>📝 Deskripsi Penjelas</h4>
                      {currentDescription ? <p className="prewrap">{currentDescription}</p> : <p className="muted-text">Belum dibuat (butuh media visual dulu).</p>}

                      <h4>💬 Caption</h4>
                      {currentCaptions ? (
                        <details open>
                          <summary>{currentCaptions.length} caption</summary>
                          <ul>{currentCaptions.map((cap, i) => <li key={i}>{cap}</li>)}</ul>
                        </details>
                      ) : <p className="muted-text">Belum dibuat.</p>}
                    </div>
                  )}
                </>
              )}
            </div>
            <div className="panel">
              <h3>Konten tersimpan</h3>
              {contentItems.length === 0 ? <p>Belum ada konten.</p> : (
                <div className="topic-list">
                  {contentItems.map((c) => (
                    <div key={c.id} className="topic-item">
                      <strong>#{c.id} · {c.content_form} ({c.aspect_ratio}) · {c.action_taken === 'amplifikasi' ? 'Amplifikasi' : 'Klarifikasi Fakta'}</strong>
                      <span>{c.angle}</span>
                      {renderVisual(c.visual_concept, c.image_url)}
                      {c.description && <p className="muted-text">{c.description}</p>}
                      {c.captions && c.captions.length > 0 && (
                        <details>
                          <summary>{c.captions.length} caption</summary>
                          <ul>{c.captions.map((cap, i) => <li key={i}>{cap}</li>)}</ul>
                        </details>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
