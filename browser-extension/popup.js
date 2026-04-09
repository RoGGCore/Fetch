const FETCH_URL = "http://127.0.0.1:5000";

function setStatus(msg, cls = "") {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.className = "status " + cls;
}

async function getToken() {
  const result = await chrome.storage.local.get("fetchToken");
  return result.fetchToken || "";
}

async function dl(fmt) {
  const url = document.getElementById("urlInput").value.trim();
  if (!url) { setStatus("⚠ URL gerekli", "err"); return; }

  setStatus("⏳ Gönderiliyor...");
  try {
    const token = await getToken();
    const headers = { "Content-Type": "application/json" };
    if (token) headers["X-Access-Token"] = token;

    const endpoint = fmt === "srt" ? "/api/subtitles" : "/api/download";
    const body = fmt === "srt"
      ? { url, lang: "tr" }
      : { url, format: fmt, quality: "best" };

    const res = await fetch(FETCH_URL + endpoint, {
      method: "POST", headers,
      body: JSON.stringify(body)
    });

    if (!res.ok) {
      const e = await res.json();
      setStatus("❌ " + (e.error || "Sunucu hatası"), "err");
      return;
    }

    const data = await res.json();
    setStatus("✅ Başladı! Hazır olunca indirilecek.", "ok");
    pollAndOpen(data.job_id, token);

  } catch (e) {
    setStatus("❌ FETCH kapalı — tray.py'yi başlat", "err");
  }
}

async function pollAndOpen(jobId, token) {
  const headers = token ? { "X-Access-Token": token } : {};
  const deadline = Date.now() + 5 * 60 * 1000;

  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 2500));
    try {
      const res = await fetch(`${FETCH_URL}/api/status/${jobId}`, { headers });
      const d = await res.json();
      if (d.status === "done") {
        setStatus("✅ Hazır — indiriliyor!", "ok");
        chrome.tabs.create({ url: `${FETCH_URL}/api/file/${jobId}`, active: false });
        return;
      }
      if (d.status === "error") {
        setStatus("❌ " + (d.error || "Hata"), "err"); return;
      }
      if (d.progress > 0) setStatus(`⏳ %${d.progress} işleniyor...`);
    } catch {}
  }
}

// Butonları bağla
document.getElementById("btnMp4").addEventListener("click", () => dl("mp4"));
document.getElementById("btnMp3").addEventListener("click", () => dl("mp3"));
document.getElementById("btnSub").addEventListener("click", () => dl("srt"));

document.getElementById("btnTab").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.url) {
    document.getElementById("urlInput").value = tab.url;
    setStatus("URL alındı ✓", "ok");
  }
});

document.getElementById("btnOpen").addEventListener("click", () => {
  chrome.tabs.create({ url: FETCH_URL });
});

document.getElementById("linkOpen").addEventListener("click", () => {
  chrome.tabs.create({ url: FETCH_URL });
});

document.getElementById("btnSave").addEventListener("click", async () => {
  const token = document.getElementById("tokenInput").value.trim();
  await chrome.storage.local.set({ fetchToken: token });
  setStatus("Kaydedildi ✓", "ok");
});

// Ayarları yükle
chrome.storage.local.get("fetchToken").then(({ fetchToken }) => {
  if (fetchToken) document.getElementById("tokenInput").value = fetchToken;
});

// Mevcut sekme URL'si
chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
  if (tab?.url?.startsWith("http")) {
    document.getElementById("urlInput").value = tab.url;
  }
});

// Bağlantı testi
fetch(FETCH_URL + "/", { signal: AbortSignal.timeout(3000) })
  .then(() => setStatus("🟢 FETCH bağlı", "ok"))
  .catch(() => setStatus("🔴 FETCH kapalı — tray.py'yi başlat", "err"));
