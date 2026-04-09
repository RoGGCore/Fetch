// ── FETCH v2.0 — Main Application JS ────────────────────────
let selectedFmt = 'mp4';
let selectedQuality = 'best';
let pollInterval = null;
let deferredPrompt = null;
let accessToken = localStorage.getItem('fetchToken') || '';
let isPlaylist = false;
let activeJobIds = new Set();
let historySearchTimeout = null;

// ── Toast Notification Sistemi ──────────────────────────────
function initToastContainer() {
  if (!document.querySelector('.toast-container')) {
    const c = document.createElement('div');
    c.className = 'toast-container';
    document.body.appendChild(c);
  }
}

function showToast(title, msg, type = 'success', duration = 4000) {
  initToastContainer();
  const container = document.querySelector('.toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<div class="toast-title">${esc(title)}</div><div class="toast-msg">${esc(msg)}</div>`;
  container.appendChild(toast);
  toast.addEventListener('click', () => { toast.classList.add('hiding'); setTimeout(() => toast.remove(), 300); });
  setTimeout(() => { toast.classList.add('hiding'); setTimeout(() => toast.remove(), 300); }, duration);
}

// ── Push Notification ───────────────────────────────────────
function requestNotificationPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

function sendNotification(title, body) {
  if ('Notification' in window && Notification.permission === 'granted') {
    try {
      new Notification(title, { body, icon: '/static/icon-192.png', badge: '/static/icon-192.png' });
    } catch (e) {}
  }
  showToast(title, body, 'success');
}

// ── Tema ──────────────────────────────────────────────────
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('fetchTheme', theme);
}
document.getElementById('themeToggle').addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme');
  applyTheme(cur === 'dark' ? 'light' : 'dark');
  saveSettings(true);
});
applyTheme(localStorage.getItem('fetchTheme') || 'dark');

// ── PWA ───────────────────────────────────────────────────
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault(); deferredPrompt = e;
  document.getElementById('installBanner').classList.add('visible');
});
document.getElementById('installBtn').addEventListener('click', async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  if (outcome === 'accepted') document.getElementById('installBanner').classList.remove('visible');
  deferredPrompt = null;
});
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/static/sw.js').catch(() => {});

// ── Share Target ──────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const shared = params.get('shared');
  if (shared) {
    document.getElementById('urlInput').value = shared;
    history.replaceState({}, '', '/');
    setTimeout(loadPreview, 400);
  }
  requestNotificationPermission();
});

// ── API helper ────────────────────────────────────────────
function apiFetch(url, opts = {}) {
  opts.headers = opts.headers || {};
  if (accessToken) opts.headers['X-Access-Token'] = accessToken;
  return fetch(url, opts);
}

// ── Tab ───────────────────────────────────────────────────
const tabs = { download: 'tabDownload', history: 'tabHistory', settings: 'tabSettings', updates: 'tabUpdates' };
const navs = { download: 'navDownload', history: 'navHistory', settings: 'navSettings', updates: 'navUpdates' };

function showTab(tab) {
  Object.entries(tabs).forEach(([key, id]) => {
    const el = document.getElementById(id);
    el.style.display = key === tab ? 'block' : 'none';
    if (key === tab) el.classList.add('tab-enter');
    else el.classList.remove('tab-enter');
  });
  Object.entries(navs).forEach(([key, id]) => {
    document.getElementById(id).classList.toggle('active', key === tab);
  });
  if (tab === 'history') loadHistory();
  if (tab === 'settings') loadSettingsPage();
  if (tab === 'updates') loadUpdates();
}

document.getElementById('navDownload').addEventListener('click', () => showTab('download'));
document.getElementById('navHistory').addEventListener('click', () => showTab('history'));
document.getElementById('navSettings').addEventListener('click', () => showTab('settings'));
document.getElementById('navUpdates').addEventListener('click', () => showTab('updates'));

// ── Drag & Drop ──────────────────────────────────────────
function initDragDrop() {
  const card = document.getElementById('tabDownload');
  card.classList.add('drop-zone');

  card.addEventListener('dragover', (e) => {
    e.preventDefault();
    card.classList.add('drag-over');
  });
  card.addEventListener('dragleave', () => {
    card.classList.remove('drag-over');
  });
  card.addEventListener('drop', (e) => {
    e.preventDefault();
    card.classList.remove('drag-over');
    const text = e.dataTransfer.getData('text/plain') || e.dataTransfer.getData('text/uri-list');
    if (text) {
      document.getElementById('urlInput').value = text.trim();
      setTimeout(loadPreview, 200);
    }
  });
}
document.addEventListener('DOMContentLoaded', initDragDrop);

// ── Önizleme ──────────────────────────────────────────────
async function loadPreview() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url) return;
  const box = document.getElementById('previewBox');
  box.classList.add('visible');
  document.getElementById('previewTitle').textContent = 'Yükleniyor...';
  document.getElementById('previewMeta').textContent = '';
  document.getElementById('previewFormats').innerHTML = '';
  document.getElementById('previewThumb').src = '';
  const playlistInfo = document.getElementById('previewPlaylist');
  if (playlistInfo) playlistInfo.textContent = '';
  try {
    const res = await apiFetch('/api/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const d = await res.json();
    if (d.error) { document.getElementById('previewTitle').textContent = 'Hata: ' + d.error; return; }
    document.getElementById('previewThumb').src = d.thumbnail;
    document.getElementById('previewTitle').textContent = d.title;
    const dur = d.duration ? fmtDuration(d.duration) : '';
    document.getElementById('previewMeta').textContent = [d.uploader, dur].filter(Boolean).join(' · ');

    // Playlist detection
    isPlaylist = d.is_playlist || false;
    if (isPlaylist && playlistInfo) {
      playlistInfo.textContent = `📋 Playlist · ${d.entry_count} video`;
    }

    const fmts = document.getElementById('previewFormats');
    if (d.formats?.length) {
      fmts.innerHTML = d.formats.slice(0,6).map(f =>
        `<span class="fmt-chip" data-q="${f.label}">${f.label}</span>`
      ).join('');
      fmts.querySelectorAll('.fmt-chip').forEach(c => {
        c.addEventListener('click', () => {
          selectedQuality = c.dataset.q;
          fmts.querySelectorAll('.fmt-chip').forEach(x => x.classList.remove('active'));
          c.classList.add('active');
          document.querySelectorAll('.quality-btn').forEach(b => b.classList.toggle('active', b.dataset.q === selectedQuality));
          document.getElementById('fmtMp4').classList.add('active');
          document.getElementById('fmtMp3').classList.remove('active');
          document.querySelectorAll('.format-btn').forEach(b => { if (b.dataset.fmt !== 'mp4') b.classList.remove('active'); });
          selectedFmt = 'mp4';
          document.getElementById('qualityGroup').classList.add('visible');
        });
      });
    }
  } catch { document.getElementById('previewTitle').textContent = 'Bağlantı hatası'; }
}

document.getElementById('btnPreview').addEventListener('click', loadPreview);
document.getElementById('urlInput').addEventListener('paste', () => setTimeout(loadPreview, 150));

function fmtDuration(sec) {
  const h = Math.floor(sec/3600);
  const m = Math.floor((sec%3600)/60);
  const s = Math.floor(sec%60);
  if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  return `${m}:${String(s).padStart(2,'0')}`;
}

// ── Format & Kalite ───────────────────────────────────────
document.querySelectorAll('.format-btn').forEach(btn => {
  btn.addEventListener('click', function() {
    document.querySelectorAll('.format-btn').forEach(b => b.classList.remove('active'));
    this.classList.add('active');
    selectedFmt = this.dataset.fmt;
    const showQuality = ['mp4', 'webm', 'gif'].includes(selectedFmt);
    document.getElementById('qualityGroup').classList.toggle('visible', showQuality);
  });
});

document.querySelectorAll('.quality-btn').forEach(btn => {
  btn.addEventListener('click', function() {
    document.querySelectorAll('.quality-btn').forEach(b => b.classList.remove('active'));
    this.classList.add('active'); selectedQuality = this.dataset.q;
  });
});

const trimmerToggle = document.getElementById('trimmerToggle');
if (trimmerToggle) {
  trimmerToggle.addEventListener('click', function() {
    const inputs = document.getElementById('trimmerInputs');
    const chevron = this.querySelector('.trimmer-chevron');
    if (inputs.style.display === 'none') {
      inputs.style.display = 'flex';
      chevron.textContent = '▲';
    } else {
      inputs.style.display = 'none';
      chevron.textContent = '▼';
    }
  });
}

// ── İndirme ───────────────────────────────────────────────
function setLoading(on) {
  document.getElementById('spinner').classList.toggle('visible', on);
  document.getElementById('dlBtn').disabled = on;
  document.getElementById('btnText').textContent = on ? 'Başlatılıyor...' : 'İndir';
}
function showProgress(v) {
  document.getElementById('progressArea').classList.toggle('visible', v);
  document.getElementById('progressDots').style.display = v ? 'flex' : 'none';
}
function updateProgress(pct, label, msg, cls, speed, eta) {
  document.getElementById('progressBar').style.width = pct + '%';
  document.getElementById('progressPct').textContent = pct + '%';
  if (label) document.getElementById('progressLabel').textContent = label;
  const st = document.getElementById('statusText');
  st.textContent = msg || '';
  st.className = 'status-text' + (cls ? ' ' + cls : '');
  if (pct >= 100) document.getElementById('progressDots').style.display = 'none';

  // Speed & ETA
  const speedEl = document.getElementById('progressSpeed');
  if (speedEl) {
    if (speed > 0 && pct < 100) {
      speedEl.style.display = 'flex';
      const speedStr = speed > 1048576 ? (speed/1048576).toFixed(1) + ' MB/s' : (speed/1024).toFixed(0) + ' KB/s';
      const etaStr = eta > 0 ? fmtDuration(eta) : '—';
      speedEl.innerHTML = `<span>⚡ ${speedStr}</span><span>⏱ ${etaStr}</span>`;
    } else {
      speedEl.style.display = 'none';
    }
  }

  if (cls === 'success') setTimeout(() => playSfx('success', 0.8), 50);
  if (cls === 'error')   setTimeout(() => playSfx('error',   0.8), 50);
}

document.getElementById('dlBtn').addEventListener('click', startDownload);

async function startDownload() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url) { updateProgress(0,'Hata','⚠ Lütfen bir URL girin.','error'); showProgress(true); return; }
  document.getElementById('resultBox').classList.remove('visible');
  clearInterval(pollInterval);
  setLoading(true); showProgress(true);
  updateProgress(0, 'Bağlanıyor...', '');

  const trimStart = document.getElementById('trimStart') ? document.getElementById('trimStart').value.trim() : "";
  const trimEnd = document.getElementById('trimEnd') ? document.getElementById('trimEnd').value.trim() : "";

  try {
    const res = await apiFetch('/api/download', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, format: selectedFmt, quality: selectedQuality, playlist: isPlaylist, start_time: trimStart, end_time: trimEnd })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Sunucu hatası');

    const jobId = data.job_id;
    activeJobIds.add(jobId);
    setLoading(false); document.getElementById('btnText').textContent = 'İndir';

    // SSE ile gerçek zamanlı takip dene, hata olursa polling'e düş
    try {
      startSSE(jobId);
    } catch {
      startPolling(jobId);
    }

  } catch (e) {
    setLoading(false); document.getElementById('btnText').textContent = 'İndir';
    updateProgress(0, 'Hata', e.message, 'error');
  }
}

// ── SSE Stream ──────────────────────────────────────────────
function startSSE(jobId) {
  const evtSource = new EventSource(`/api/stream/${jobId}`);
  evtSource.onmessage = (event) => {
    try {
      const sd = JSON.parse(event.data);
      handleJobUpdate(jobId, sd);
      if (sd.status === 'done' || sd.status === 'error') {
        evtSource.close();
      }
    } catch {}
  };
  evtSource.onerror = () => {
    evtSource.close();
    startPolling(jobId);
  };
}

function startPolling(jobId) {
  pollInterval = setInterval(async () => {
    try {
      const sd = await (await apiFetch(`/api/status/${jobId}`)).json();
      handleJobUpdate(jobId, sd);
      if (sd.status === 'done' || sd.status === 'error') {
        clearInterval(pollInterval);
      }
    } catch { clearInterval(pollInterval); updateProgress(0,'Hata','Bağlantı kesildi.','error'); }
  }, 900);
}

function handleJobUpdate(jobId, sd) {
  if (sd.status === 'downloading' || sd.status === 'queued') {
    const pct = sd.progress || 0;
    let label = pct < 50 ? 'İndiriliyor...' : 'İşleniyor...';
    if (sd.playlist_total) {
      label = `Playlist: ${sd.playlist_done || 0}/${sd.playlist_total}`;
    }
    updateProgress(pct, label, `%${pct} tamamlandı`, '', sd.speed || 0, sd.eta || 0);
  } else if (sd.status === 'done') {
    activeJobIds.delete(jobId);
    updateProgress(100, 'Tamamlandı!', 'Dosya hazır ✓', 'success');
    const box = document.getElementById('resultBox');
    box.style.display = 'flex';
    setTimeout(() => { box.classList.add('visible'); }, 10);

    const fmtIcon = {'mp3':'🎵','wav':'🎵','flac':'🎵','webm':'🎥', 'gif':'🖼️'};
    document.getElementById('resultIcon').textContent = fmtIcon[selectedFmt] || '🎬';
    document.getElementById('resultTitle').textContent = sd.title || 'İndirildi';
    document.getElementById('resultSub').textContent = selectedFmt.toUpperCase() + (selectedQuality !== 'best' ? ' · ' + selectedQuality : '') + ' — Hazır';
    document.getElementById('resultLink').href = `/api/file/${jobId}`;

    // Push notification
    sendNotification('İndirme Tamamlandı', sd.title || 'Dosya hazır!');
  } else if (sd.status === 'error') {
    activeJobIds.delete(jobId);
    updateProgress(0, 'Hata', sd.error || 'Bilinmeyen hata', 'error');
    document.getElementById('progressDots').style.display = 'none';
    sendNotification('İndirme Hatası', sd.error || 'Bilinmeyen hata');
  }
  updateActiveDownloads();
}

// ── Aktif İndirmeler (çoklu kuyruk) ─────────────────────────
async function updateActiveDownloads() {
  const container = document.getElementById('activeDownloads');
  if (!container) return;
  try {
    const data = await (await apiFetch('/api/jobs')).json();
    const entries = Object.entries(data);
    if (entries.length === 0) {
      container.classList.remove('visible');
      container.innerHTML = '';
      return;
    }
    container.classList.add('visible');
    container.innerHTML = entries.map(([jid, j]) => {
      const pct = j.progress || 0;
      const speed = j.speed || 0;
      const speedStr = speed > 1048576 ? (speed/1048576).toFixed(1)+' MB/s' : speed > 0 ? (speed/1024).toFixed(0)+' KB/s' : '';
      return `
        <div class="active-dl-item">
          <div class="active-dl-header">
            <span class="active-dl-title">${esc(j.title || jid)}</span>
            <span class="active-dl-pct">${pct}%</span>
          </div>
          <div class="active-dl-bar"><div class="active-dl-bar-fill" style="width:${pct}%"></div></div>
          <div class="active-dl-meta">${j.status} ${speedStr ? '· '+speedStr : ''}</div>
        </div>`;
    }).join('');
  } catch {}
}

// Periyodik aktif indirme takibi
setInterval(updateActiveDownloads, 3000);

document.getElementById('urlInput').addEventListener('keydown', e => { if (e.key === 'Enter') startDownload(); });

// ── Geçmiş ────────────────────────────────────────────────
let historyFilterFmt = '';

async function loadHistory() {
  const list = document.getElementById('historyList');
  list.innerHTML = '<div class="history-empty"><span class="history-empty-icon">⏳</span>Yükleniyor...</div>';
  const searchInput = document.getElementById('historySearch');
  const searchQ = searchInput ? searchInput.value.trim() : '';
  try {
    let apiUrl = '/api/history';
    const params = [];
    if (searchQ) params.push(`q=${encodeURIComponent(searchQ)}`);
    if (historyFilterFmt) params.push(`format=${encodeURIComponent(historyFilterFmt)}`);
    if (params.length) apiUrl += '?' + params.join('&');

    const data = await (await apiFetch(apiUrl)).json();
    if (!data.length) { list.innerHTML = '<div class="history-empty"><span class="history-empty-icon">📭</span>Henüz indirme yapılmadı.</div>'; return; }
    list.innerHTML = data.map(h => `
      <div class="hist-item" id="hi-${h.job_id}">
        ${h.thumbnail ? `<img class="hist-thumb" src="${esc(h.thumbnail)}" onerror="this.style.display='none'" loading="lazy">` : `<div class="hist-thumb-placeholder">${h.format==='mp3'?'🎵':h.format==='gif'?'🖼️':'🎬'}</div>`}
        <div class="hist-info">
          <div class="hist-title">${esc(h.title)}</div>
          <div class="hist-meta">
            <span class="hist-tag fmt">${h.format.toUpperCase()}</span>
            ${h.quality&&h.quality!=='best'?`<span class="hist-tag fmt">${h.quality}</span>`:''}
            <span class="hist-tag">${h.date}</span>
            ${h.filesize?`<span class="hist-tag">${fmtSize(h.filesize)}</span>`:''}
          </div>
        </div>
        <div class="hist-actions">
          <a class="hist-btn ${h.file_exists?'':'disabled'}" href="/api/file/${h.job_id}">↓</a>
          <button class="hist-btn del" onclick="delHist('${h.job_id}')">✕</button>
        </div>
      </div>`).join('');
  } catch { list.innerHTML = '<div class="history-empty">Geçmiş yüklenemedi.</div>'; }
}

// Arama
function initHistorySearch() {
  const searchInput = document.getElementById('historySearch');
  if (!searchInput) return;
  searchInput.addEventListener('input', () => {
    clearTimeout(historySearchTimeout);
    historySearchTimeout = setTimeout(loadHistory, 400);
  });
}
document.addEventListener('DOMContentLoaded', initHistorySearch);

// Format filtresi
function setHistoryFilter(fmt) {
  historyFilterFmt = historyFilterFmt === fmt ? '' : fmt;
  document.querySelectorAll('.filter-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.fmt === historyFilterFmt);
  });
  loadHistory();
}

async function delHist(id) {
  const el = document.getElementById(`hi-${id}`);
  if (el) { el.style.opacity='0'; el.style.transform='translateX(20px)'; el.style.transition='all 0.3s'; setTimeout(()=>el.remove(),300); }
  await apiFetch(`/api/history/${id}`, { method: 'DELETE' });
}

document.getElementById('btnClearHistory').addEventListener('click', async () => {
  if (!confirm('Tüm geçmiş silinsin mi?')) return;
  await apiFetch('/api/history', { method: 'DELETE' });
  loadHistory();
});

// ── Toplu İndirme (Geçmiş) ──────────────────────────────────
async function downloadAllHistory() {
  try {
    const data = await (await apiFetch('/api/history')).json();
    const available = data.filter(h => h.file_exists);
    if (!available.length) { showToast('Bilgi', 'İndirilebilir dosya yok.', 'error'); return; }
    for (const h of available) {
      const a = document.createElement('a');
      a.href = `/api/file/${h.job_id}`;
      a.download = '';
      a.click();
      await new Promise(r => setTimeout(r, 500));
    }
    showToast('Tamamlandı', `${available.length} dosya indirme başlatıldı.`);
  } catch { showToast('Hata', 'Toplu indirme başarısız.', 'error'); }
}

// ── Ayarlar ───────────────────────────────────────────────
async function loadSettingsPage() {
  try {
    const s = await (await apiFetch('/api/settings')).json();
    document.getElementById('saveDirInput').value = s.save_dir || '';
    document.getElementById('passwordInput').value = s.access_password || '';
    const tog = document.getElementById('autoDeleteToggle');
    if (tog) tog.className = 'toggle-switch ' + (s.auto_delete_after_send !== false ? 'on' : '');
  } catch {}
  loadDiskInfo();
}

async function loadDiskInfo() {
  try {
    const d = await (await apiFetch('/api/disk')).json();
    const pct = (d.used/d.total*100).toFixed(1);
    document.getElementById('diskInfo').textContent = `Disk: ${fmtSize(d.used)} kullanılıyor`;
    const bar = document.getElementById('diskBar');
    bar.style.width = pct + '%';
    bar.className = 'disk-bar-fill' + (pct>90?' danger':pct>70?' warn':'');
    document.getElementById('diskUsed').textContent = fmtSize(d.used) + ' kullanıldı';
    document.getElementById('diskTotal').textContent = fmtSize(d.free) + ' boş';
    document.getElementById('dlFolderInfo').textContent = `İndirme klasörü: ${d.dl_count} dosya · ${fmtSize(d.dl_size)}`;
  } catch {}
}

document.getElementById('autoDeleteToggle').addEventListener('click', function() { this.classList.toggle('on'); });
document.getElementById('sfxToggle').addEventListener('click', function() {
  this.classList.toggle('on');
  const enabled = this.classList.contains('on');
  localStorage.setItem('fetchSfx', enabled ? 'on' : 'off');
  playSfx('click', 0.7);
});
document.addEventListener('DOMContentLoaded', () => {
  const tog = document.getElementById('sfxToggle');
  if (tog) tog.className = 'toggle-switch ' + (SFX_ENABLED() ? 'on' : '');
});

document.getElementById('btnSaveSettings').addEventListener('click', () => saveSettings(false));

async function saveSettings(silent=false) {
  const theme    = document.documentElement.getAttribute('data-theme');
  const saveDir  = document.getElementById('saveDirInput')?.value || '';
  const password = document.getElementById('passwordInput')?.value || '';
  const autoDel  = document.getElementById('autoDeleteToggle')?.classList.contains('on') ?? true;
  try {
    await apiFetch('/api/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ save_dir: saveDir, theme, access_password: password, auto_delete_after_send: autoDel })
    });
    if (password && password !== '••••••') { accessToken = password; localStorage.setItem('fetchToken', password); }
    if (!silent) { const btn = document.getElementById('btnSaveSettings'); btn.textContent='Kaydedildi ✓'; setTimeout(()=>btn.textContent='Kaydet',2000); }
  } catch (e) { if (!silent) showToast('Hata', e.message, 'error'); }
}

document.getElementById('btnClean').addEventListener('click', async () => {
  if (!confirm('İndirme klasöründeki tüm dosyalar silinsin mi?')) return;
  const d = await (await apiFetch('/api/clean', { method: 'DELETE' })).json();
  showToast('Temizlendi', `${d.deleted} dosya silindi.`);
  loadDiskInfo();
});

// ── yt-dlp Güncelleme ───────────────────────────────────────
document.getElementById('btnUpdateYtdlp')?.addEventListener('click', async function() {
  this.disabled = true;
  this.textContent = 'Güncelleniyor...';
  try {
    const res = await apiFetch('/api/update-ytdlp', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      showToast('Güncellendi', 'yt-dlp başarıyla güncellendi!');
      this.textContent = 'Güncellendi ✓';
    } else {
      showToast('Hata', data.error || 'Güncelleme başarısız', 'error');
      this.textContent = 'yt-dlp Güncelle';
    }
  } catch (e) {
    showToast('Hata', e.message, 'error');
    this.textContent = 'yt-dlp Güncelle';
  }
  this.disabled = false;
});

// ── Güncellemeler ─────────────────────────────────────────
async function loadUpdates() {
  const list = document.getElementById('updatesList');
  list.innerHTML = '<div class="history-empty"><span class="history-empty-icon">⏳</span>Yükleniyor...</div>';
  try {
    const d = await (await apiFetch('/api/version')).json();
    let html = `
      <div class="version-header">
        <div class="version-badge">
          <span class="version-num">v${d.app_version}</span>
          <span class="version-tag">Güncel</span>
        </div>
        <div class="version-meta">
          <span><strong>yt-dlp</strong>${d.ytdlp_version}</span>
          <span><strong>Python</strong>${d.python_version}</span>
        </div>
      </div>`;
    d.changelog.forEach((c, i) => {
      const isLatest = i === 0;
      html += `
        <div class="changelog-item ${isLatest?'latest':''}">
          <div class="changelog-header">
            <span class="changelog-ver">v${c.version}</span>
            <span class="changelog-tag ${isLatest?'latest-tag':''}">${c.tag}</span>
            <span class="changelog-date">${c.date}</span>
          </div>
          <ul class="changelog-notes">${c.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>
        </div>`;
    });
    list.innerHTML = html;
  } catch { list.innerHTML = '<div class="history-empty">Yüklenemedi.</div>'; }
}


// ── Ses Efektleri (Opera GX stili) ───────────────────────
const SFX = {};
const SFX_ENABLED = () => localStorage.getItem('fetchSfx') !== 'off';

function loadSfx() {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  ['click','hover','success','error','nav'].forEach(name => {
    fetch(`/static/sfx_${name}.wav`)
      .then(r => r.arrayBuffer())
      .then(buf => ctx.decodeAudioData(buf))
      .then(decoded => { SFX[name] = { ctx, buf: decoded }; })
      .catch(() => {});
  });
}

function playSfx(name, volume=1.0) {
  if (!SFX_ENABLED()) return;
  const s = SFX[name];
  if (!s) return;
  try {
    const src = s.ctx.createBufferSource();
    const gain = s.ctx.createGain();
    src.buffer = s.buf;
    gain.gain.value = volume;
    src.connect(gain);
    gain.connect(s.ctx.destination);
    src.start();
  } catch {}
}

document.addEventListener('click', function init() {
  loadSfx();
  document.removeEventListener('click', init);
}, { once: true });

function bindSounds() {
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => playSfx('nav', 0.7));
  });
  document.querySelectorAll('.format-btn').forEach(btn => {
    btn.addEventListener('click', () => playSfx('click', 0.8));
    btn.addEventListener('mouseenter', () => playSfx('hover', 0.5));
  });
  document.querySelectorAll('.quality-btn').forEach(btn => {
    btn.addEventListener('click', () => playSfx('click', 0.6));
  });
  document.getElementById('dlBtn').addEventListener('mouseenter', () => playSfx('hover', 0.4));
  document.getElementById('btnPreview').addEventListener('click', () => playSfx('click', 0.7));
  document.getElementById('btnPreview').addEventListener('mouseenter', () => playSfx('hover', 0.3));
  document.getElementById('btnSaveSettings').addEventListener('mouseenter', () => playSfx('hover', 0.3));
  document.getElementById('btnSaveSettings').addEventListener('click', () => playSfx('click', 0.8));
  document.getElementById('autoDeleteToggle').addEventListener('click', () => playSfx('click', 0.6));
  document.getElementById('themeToggle').addEventListener('click', () => playSfx('click', 0.5));
  document.getElementById('btnClean').addEventListener('click', () => playSfx('click', 0.9));
}

document.addEventListener('DOMContentLoaded', bindSounds);

// ── Yardımcılar ───────────────────────────────────────────
function fmtSize(b) {
  if (b>1073741824) return (b/1073741824).toFixed(1)+' GB';
  if (b>1048576) return (b/1048576).toFixed(1)+' MB';
  return (b/1024).toFixed(0)+' KB';
}
function esc(t) { return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
