const FETCH_URL = "http://localhost:5000";

// Sağ tık menüleri oluştur
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "fetch-mp4",
    title: "🎬 FETCH ile MP4 İndir",
    contexts: ["page", "link", "selection"]
  });
  chrome.contextMenus.create({
    id: "fetch-mp3",
    title: "🎵 FETCH ile MP3 İndir",
    contexts: ["page", "link", "selection"]
  });
  chrome.contextMenus.create({
    id: "fetch-sub",
    title: "📝 FETCH ile Altyazı İndir",
    contexts: ["page", "link", "selection"]
  });
});

// Sağ tık tıklaması
chrome.contextMenus.onClicked.addListener((info, tab) => {
  const url = info.linkUrl || info.selectionText || info.pageUrl;
  if (!url) return;

  const fmt = info.menuItemId === "fetch-mp3" ? "mp3"
            : info.menuItemId === "fetch-sub" ? "srt"
            : "mp4";

  sendToFetch(url, fmt);
});

async function sendToFetch(url, fmt) {
  try {
    // Ayarlardan token al
    const { fetchToken } = await chrome.storage.local.get("fetchToken");
    const headers = {
      "Content-Type": "application/json",
      ...(fetchToken ? { "X-Access-Token": fetchToken } : {})
    };

    const endpoint = fmt === "srt" ? "/api/subtitles" : "/api/download";
    const body = fmt === "srt"
      ? { url, lang: "tr" }
      : { url, format: fmt, quality: "best" };

    const res = await fetch(FETCH_URL + endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(body)
    });

    if (!res.ok) {
      const err = await res.json();
      notify("Hata", err.error || "Sunucuya bağlanılamadı");
      return;
    }

    const { job_id } = await res.json();
    notify("İndirme Başladı", `${fmt.toUpperCase()} hazırlanıyor...`);

    // İlerlemeyi takip et
    pollJob(job_id, fmt, fetchToken);

  } catch (e) {
    notify("Hata", "FETCH çalışıyor mu? localhost:5000 kontrol et.");
  }
}

async function pollJob(jobId, fmt, token) {
  const headers = token ? { "X-Access-Token": token } : {};
  const deadline = Date.now() + 5 * 60 * 1000; // 5 dakika

  while (Date.now() < deadline) {
    await sleep(2000);
    try {
      const res = await fetch(`${FETCH_URL}/api/status/${jobId}`, { headers });
      const d   = await res.json();

      if (d.status === "done") {
        notify("✅ Hazır!", `${d.title || "Dosya"} indirildi. Kaydet butonuna bas.`);
        // Otomatik indirme için yeni sekme aç
        chrome.tabs.create({ url: `${FETCH_URL}/api/file/${jobId}`, active: false });
        return;
      }
      if (d.status === "error") {
        notify("❌ Hata", d.error || "İndirme başarısız");
        return;
      }
    } catch { /* devam et */ }
  }
  notify("Zaman Aşımı", "İndirme çok uzun sürdü.");
}

function notify(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icon48.png",
    title: `FETCH — ${title}`,
    message
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
