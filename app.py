import os
import re
import json
import time
import shutil
import threading
import uuid
import logging
import hashlib
import subprocess
import sys
from datetime import datetime
from collections import defaultdict
from flask import Flask, request, jsonify, send_file, render_template, abort, Response
import yt_dlp

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "fetch.log"),
                            encoding="utf-8"),
    ],
)
log = logging.getLogger("FETCH")

app = Flask(__name__)

APP_VERSION = "2.0.0"
CHANGELOG = [
    {
        "version": "2.0.0",
        "date": "2026-03-20",
        "tag": "Büyük Güncelleme",
        "notes": [
            "Güvenlik: Path traversal koruması",
            "Güvenlik: Job ve rate-limit bellek temizliği (TTL)",
            "Loglama sistemi (fetch.log)",
            "SSE ile gerçek zamanlı progress (WebSocket yerine)",
            "İndirme hızı (MB/s) ve ETA göstergesi",
            "Çoklu indirme kuyruğu & UI",
            "Playlist desteği (YouTube, vb.)",
            "Ek format desteği: WAV, FLAC, WebM",
            "Geçmişte arama/filtreleme",
            "Drag & Drop URL desteği",
            "Push notification (indirme bitince)",
            "yt-dlp güncelleme butonu",
            "Gelişmiş Service Worker (stale-while-revalidate)",
            ".env ortam değişkenleri desteği",
            "Frontend dosya ayrımı (CSS + JS)",
            "Docker desteği",
        ]
    },
    {
        "version": "1.4.0",
        "date": "2026-03-15",
        "tag": "Yeni",
        "notes": [
            "Güncellemeler sekmesi eklendi",
            "Sürüm geçmişi ve changelog görünümü",
        ]
    },
    {
        "version": "1.3.0",
        "date": "2026-03-15",
        "tag": "Yeni",
        "notes": [
            "Karanlık / Aydınlık tema desteği",
            "Thumbnail önizleme",
            "Video kalite seçimi: 4K, 1080p, 720p, 480p",
            "Otomatik kayıt klasörü ayarı",
            "Disk kullanımı göstergesi ve temizle butonu",
            "Erişim şifresi ile DDoS koruması",
        ]
    },
    {
        "version": "1.2.0",
        "date": "2026-03-15",
        "tag": "Yeni",
        "notes": [
            "Kalıcı indirme geçmişi (history.json)",
            "Geçmişten tekrar indirme",
            "Dosya boyutu, kanal adı ve tarih bilgisi",
        ]
    },
    {
        "version": "1.1.0",
        "date": "2026-03-15",
        "tag": "Yeni",
        "notes": [
            "Sistem tepsisi ikonu (tray.py)",
            "Ngrok ile telefon erişimi",
            "PWA desteği - Ana ekrana ekle",
            "Mobil uyumlu arayüz",
        ]
    },
    {
        "version": "1.0.0",
        "date": "2026-03-15",
        "tag": "İlk Sürüm",
        "notes": [
            "YouTube, Instagram ve genel URL desteği",
            "MP4 video ve MP3 ses indirme",
            "Flask backend + yt-dlp",
            "Canlı indirme progress bar",
        ]
    },
]

BASE_DIR      = os.path.dirname(__file__)
DOWNLOAD_DIR  = os.path.join(BASE_DIR, "downloads")
HISTORY_FILE  = os.path.join(BASE_DIR, "history.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()
history_lock = threading.Lock()

# ── .env desteği ───────────────────────────────────────────────
def load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

load_env()

# ── Ayarlar ──────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "save_dir": DOWNLOAD_DIR,
    "theme": "dark",
    "access_password": "",
    "auto_delete_after_send": True,
}

def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                for k, v in DEFAULT_SETTINGS.items():
                    s.setdefault(k, v)
                return s
    except Exception as e:
        log.warning("Ayarlar yüklenemedi: %s", e)
    return dict(DEFAULT_SETTINGS)

def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

# ── Güvenlik: Rate limiting ───────────────────────────────────
rate_data = defaultdict(list)
rate_lock  = threading.Lock()
RATE_LIMIT  = 200
RATE_WINDOW = 60

def is_rate_limited(ip):
    now = time.time()
    with rate_lock:
        rate_data[ip] = [t for t in rate_data[ip] if now - t < RATE_WINDOW]
        if len(rate_data[ip]) >= RATE_LIMIT:
            log.warning("Rate limit aşıldı: %s", ip)
            return True
        rate_data[ip].append(now)
        return False

# ── Rate data bellek temizliği (periyodik) ────────────────────
def cleanup_rate_data():
    while True:
        time.sleep(120)
        now = time.time()
        with rate_lock:
            stale_ips = [ip for ip, times in rate_data.items()
                         if all(now - t >= RATE_WINDOW for t in times)]
            for ip in stale_ips:
                del rate_data[ip]
            if stale_ips:
                log.info("Rate data temizlendi: %d IP silindi", len(stale_ips))

threading.Thread(target=cleanup_rate_data, daemon=True).start()

# ── Job TTL temizliği (periyodik) ─────────────────────────────
JOB_TTL = 3600  # 1 saat

def cleanup_jobs():
    while True:
        time.sleep(300)
        now = time.time()
        with jobs_lock:
            stale = [jid for jid, job in jobs.items()
                     if job.get("status") in ("done", "error")
                     and now - job.get("created_at", now) > JOB_TTL]
            for jid in stale:
                del jobs[jid]
            if stale:
                log.info("Eski job'lar temizlendi: %d job silindi", len(stale))

threading.Thread(target=cleanup_jobs, daemon=True).start()

# ── Güvenlik: Şifre hash ─────────────────────────────────────
def hash_password(pwd):
    return hashlib.sha256(pwd.encode("utf-8")).hexdigest()

def check_password():
    s = load_settings()
    pwd = s.get("access_password", "").strip()
    if not pwd:
        return True
    token = request.headers.get("X-Access-Token", "") or request.args.get("token", "")
    # Düz metin veya hash olarak karşılaştır
    if token == pwd or hash_password(token) == pwd:
        return True
    return False

# ── Güvenlik: Path traversal koruması ─────────────────────────
def safe_job_id(job_id):
    """job_id'nin güvenli olduğunu doğrula (sadece alnum ve tire)"""
    if not re.match(r'^[a-f0-9\-]{1,36}$', job_id):
        return False
    return True

def safe_filepath(base_dir, filename):
    """Dosya yolunun base_dir içinde kaldığını doğrula"""
    real_base = os.path.realpath(base_dir)
    real_path = os.path.realpath(os.path.join(base_dir, filename))
    return real_path.startswith(real_base)

@app.before_request
def security_check():
    if request.path.startswith("/static") or request.path == "/":
        return
    exempt = ["/api/status", "/api/file", "/api/history", "/api/disk",
              "/api/version", "/api/stream"]
    is_exempt = any(request.path.startswith(e) for e in exempt)
    ip = request.remote_addr
    if not is_exempt and is_rate_limited(ip):
        return jsonify({"error": "Çok fazla istek. Lütfen bekleyin."}), 429
    if request.path.startswith("/api/") and request.path != "/api/settings":
        if not check_password():
            return jsonify({"error": "Yetkisiz erişim"}), 401

# ── Geçmiş ───────────────────────────────────────────────────
def load_history():
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.warning("Geçmiş yüklenemedi: %s", e)
    return []

def save_history_entry(entry):
    with history_lock:
        history = load_history()
        history.insert(0, entry)
        history = history[:200]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def parse_time_to_sec(time_str):
    if not time_str:
        return 0
    parts = str(time_str).strip().split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1:
            return int(parts[0])
    except ValueError:
        pass
    return 0

# ── İndirme ───────────────────────────────────────────────────
def download_task(job_id, url, fmt, quality, start_time=None, end_time=None):
    try:
        with jobs_lock:
            jobs[job_id]["status"] = "downloading"
        s = load_settings()
        out_dir = s.get("save_dir") or DOWNLOAD_DIR
        os.makedirs(out_dir, exist_ok=True)
        log.info("İndirme başladı: job=%s url=%s fmt=%s quality=%s", job_id, url, fmt, quality)

        last_speed_update = [time.time()]

        def progress_hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                speed = d.get("speed", 0) or 0
                eta = d.get("eta", 0) or 0
                pct = 0
                if total:
                    pct = int(downloaded / total * 90)
                with jobs_lock:
                    jobs[job_id]["progress"] = pct
                    jobs[job_id]["speed"] = speed
                    jobs[job_id]["eta"] = eta
                    jobs[job_id]["downloaded"] = downloaded
                    jobs[job_id]["total_bytes"] = total
            elif d["status"] == "finished":
                with jobs_lock:
                    jobs[job_id]["progress"] = 95
                    jobs[job_id]["speed"] = 0

        output_template = os.path.join(out_dir, f"{job_id}_%(title)s.%(ext)s")

        ydl_opts = {}
        start_sec = parse_time_to_sec(start_time)
        end_sec = parse_time_to_sec(end_time)

        if fmt == "mp3":
            ydl_opts = {
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                "outtmpl": output_template,
                "progress_hooks": [progress_hook],
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
                "quiet": True, "no_warnings": True,
                "concurrent_fragment_downloads": 4,
            }
        elif fmt == "wav":
            ydl_opts = {
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                "outtmpl": output_template,
                "progress_hooks": [progress_hook],
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav", "preferredquality": "0"}],
                "quiet": True, "no_warnings": True,
            }
        elif fmt == "flac":
            ydl_opts = {
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                "outtmpl": output_template,
                "progress_hooks": [progress_hook],
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "flac", "preferredquality": "0"}],
                "quiet": True, "no_warnings": True,
            }
        elif fmt == "webm":
            ydl_opts = {
                "format": "bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best",
                "outtmpl": output_template,
                "progress_hooks": [progress_hook],
                "quiet": True, "no_warnings": True,
            }
        elif fmt == "gif":
            if quality == "4k":
                fmt_str = "bestvideo[height<=2160][ext=mp4]/best[height<=2160]"
            elif quality == "1080p":
                fmt_str = "bestvideo[height<=1080][ext=mp4]/best[height<=1080]"
            elif quality == "720p":
                fmt_str = "bestvideo[height<=720][ext=mp4]/best[height<=720]"
            elif quality == "480p":
                fmt_str = "bestvideo[height<=480][ext=mp4]/best[height<=480]"
            else:
                fmt_str = "bestvideo[ext=mp4]/best"
            ydl_opts = {
                "format": fmt_str,
                "outtmpl": output_template,
                "progress_hooks": [progress_hook],
                "quiet": True, "no_warnings": True,
            }
        else:
            # MP4 — Kalite seçimi
            if quality == "4k":
                fmt_str = "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]"
            elif quality == "1080p":
                fmt_str = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"
            elif quality == "720p":
                fmt_str = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"
            elif quality == "480p":
                fmt_str = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]"
            else:
                fmt_str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
            ydl_opts.update({
                "format": fmt_str,
                "outtmpl": output_template,
                "progress_hooks": [progress_hook],
                "merge_output_format": "mp4",
                "quiet": True, "no_warnings": True,
            })

        if start_sec > 0 or end_sec > 0:
            if end_sec <= 0:
                end_sec = 999999
            ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(start_sec, end_sec)])
            ydl_opts['force_keyframes_at_cuts'] = True

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title     = sanitize_filename(info.get("title", "download"))
            thumbnail = info.get("thumbnail", "")
            duration  = info.get("duration", 0)
            uploader  = info.get("uploader", "")

        for f in os.listdir(out_dir):
            if f.startswith(job_id):
                filepath = os.path.join(out_dir, f)
                
                if fmt == "gif":
                    with jobs_lock:
                        jobs[job_id]["status"] = "downloading"
                        jobs[job_id]["progress"] = 98
                    
                    gif_filename = os.path.splitext(f)[0] + ".gif"
                    gif_path = os.path.join(out_dir, gif_filename)
                    ffmpeg_cmd = [
                        "ffmpeg", "-y", "-i", filepath,
                        "-vf", "fps=15,scale=640:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                        "-loop", "0",
                        gif_path
                    ]
                    try:
                        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        os.remove(filepath)
                        filepath = gif_path
                        f = gif_filename
                    except Exception as e:
                        log.error("GIF hatası: %s", e)
                        raise Exception("GIF dönüşümü başarısız oldu.")

                filesize = os.path.getsize(filepath)
                with jobs_lock:
                    jobs[job_id].update({"status": "done", "progress": 100, "filename": f,
                                         "title": title, "save_dir": out_dir, "speed": 0, "eta": 0})
                save_history_entry({
                    "job_id": job_id, "title": title, "url": url,
                    "format": fmt, "quality": quality,
                    "thumbnail": thumbnail, "duration": duration,
                    "uploader": uploader, "filesize": filesize,
                    "filename": f, "save_dir": out_dir,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
                log.info("İndirme tamamlandı: job=%s title=%s size=%s", job_id, title, filesize)
                break
        else:
            with jobs_lock:
                jobs[job_id].update({"status": "error", "error": "Dosya bulunamadı."})
            log.error("İndirme hatası: job=%s dosya bulunamadı", job_id)

    except Exception as e:
        with jobs_lock:
            jobs[job_id].update({"status": "error", "error": str(e)})
        log.error("İndirme hatası: job=%s error=%s", job_id, e)

# ── Playlist İndirme ──────────────────────────────────────────
def playlist_download_task(job_id, url, fmt, quality):
    try:
        with jobs_lock:
            jobs[job_id]["status"] = "downloading"
        s = load_settings()
        out_dir = s.get("save_dir") or DOWNLOAD_DIR
        os.makedirs(out_dir, exist_ok=True)
        log.info("Playlist indirme başladı: job=%s url=%s", job_id, url)

        # Önce playlist bilgilerini al
        ydl_opts_info = {"quiet": True, "no_warnings": True, "extract_flat": True}
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries", [])
        total = len(entries)
        if total == 0:
            with jobs_lock:
                jobs[job_id].update({"status": "error", "error": "Playlist boş veya bulunamadı."})
            return

        results = []
        with jobs_lock:
            jobs[job_id]["playlist_total"] = total
            jobs[job_id]["playlist_done"] = 0

        for i, entry in enumerate(entries):
            entry_url = entry.get("url") or entry.get("webpage_url", "")
            if not entry_url:
                continue
            sub_id = str(uuid.uuid4())[:8]
            output_template = os.path.join(out_dir, f"{sub_id}_%(title)s.%(ext)s")

            if fmt == "mp3":
                sub_opts = {
                    "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                    "outtmpl": output_template,
                    "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
                    "quiet": True, "no_warnings": True,
                }
            else:
                sub_opts = {
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "outtmpl": output_template,
                    "merge_output_format": "mp4",
                    "quiet": True, "no_warnings": True,
                }

            try:
                with yt_dlp.YoutubeDL(sub_opts) as ydl:
                    sub_info = ydl.extract_info(entry_url, download=True)
                    sub_title = sanitize_filename(sub_info.get("title", f"video_{i+1}"))
                    results.append({"title": sub_title, "sub_id": sub_id})
            except Exception as e:
                log.warning("Playlist öğesi atlandı: %s — %s", entry_url, e)

            with jobs_lock:
                jobs[job_id]["playlist_done"] = i + 1
                jobs[job_id]["progress"] = int((i + 1) / total * 100)

        with jobs_lock:
            jobs[job_id].update({
                "status": "done", "progress": 100,
                "title": info.get("title", "Playlist"),
                "playlist_results": results,
                "save_dir": out_dir,
            })
        log.info("Playlist tamamlandı: job=%s %d/%d", job_id, len(results), total)

    except Exception as e:
        with jobs_lock:
            jobs[job_id].update({"status": "error", "error": str(e)})
        log.error("Playlist hatası: job=%s error=%s", job_id, e)

# ── Önizleme ─────────────────────────────────────────────────
@app.route("/api/preview", methods=["POST"])
def preview():
    data = request.get_json()
    url  = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL gerekli"}), 400
    try:
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # Playlist detection
        is_playlist = info.get("_type") == "playlist" or "entries" in info
        entry_count = len(info.get("entries", [])) if is_playlist else 0

        formats = []
        seen = set()
        for f in info.get("formats", []):
            h = f.get("height")
            if h and f.get("vcodec") != "none":
                label = f"{h}p"
                if label not in seen:
                    seen.add(label)
                    formats.append({"label": label, "height": h})
        formats.sort(key=lambda x: -x["height"])
        return jsonify({
            "title":       info.get("title", ""),
            "thumbnail":   info.get("thumbnail", ""),
            "duration":    info.get("duration", 0),
            "uploader":    info.get("uploader", ""),
            "formats":     formats,
            "is_playlist": is_playlist,
            "entry_count": entry_count,
        })
    except Exception as e:
        log.warning("Önizleme hatası: %s", e)
        return jsonify({"error": str(e)}), 400

# ── Routes ───────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/download", methods=["POST"])
def start_download():
    data    = request.get_json()
    url     = data.get("url", "").strip()
    fmt     = data.get("format", "mp4")
    quality = data.get("quality", "best")
    playlist = data.get("playlist", False)
    start_time = data.get("start_time", "").strip()
    end_time = data.get("end_time", "").strip()
    if not url:
        return jsonify({"error": "URL gerekli"}), 400
    if fmt not in ("mp4", "mp3", "wav", "flac", "webm", "gif"):
        return jsonify({"error": "Geçersiz format"}), 400

    job_id = str(uuid.uuid4())[:8]
    with jobs_lock:
        jobs[job_id] = {"status": "queued", "progress": 0, "speed": 0, "eta": 0,
                        "created_at": time.time()}

    if playlist:
        t = threading.Thread(target=playlist_download_task, args=(job_id, url, fmt, quality))
    else:
        t = threading.Thread(target=download_task, args=(job_id, url, fmt, quality, start_time, end_time))
    t.daemon = True
    t.start()
    log.info("İndirme başlatıldı: job=%s url=%s fmt=%s", job_id, url, fmt)
    return jsonify({"job_id": job_id})

@app.route("/api/status/<job_id>")
def job_status(job_id):
    if not safe_job_id(job_id):
        return jsonify({"error": "Geçersiz job ID"}), 400
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "İş bulunamadı"}), 404
    return jsonify(job)

# ── SSE Stream (gerçek zamanlı progress) ─────────────────────
@app.route("/api/stream/<job_id>")
def stream_status(job_id):
    if not safe_job_id(job_id):
        return jsonify({"error": "Geçersiz job ID"}), 400

    def generate():
        while True:
            with jobs_lock:
                job = jobs.get(job_id)
            if not job:
                yield f"data: {json.dumps({'error': 'İş bulunamadı'})}\n\n"
                break
            yield f"data: {json.dumps(job, default=str)}\n\n"
            if job.get("status") in ("done", "error"):
                break
            time.sleep(0.8)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/api/file/<job_id>")
def get_file(job_id):
    if not safe_job_id(job_id):
        return jsonify({"error": "Geçersiz job ID"}), 400

    with jobs_lock:
        job = dict(jobs.get(job_id, {}))
    filename = job.get("filename")
    save_dir = job.get("save_dir", DOWNLOAD_DIR)
    if not filename:
        history = load_history()
        for h in history:
            if h.get("job_id") == job_id:
                filename = h.get("filename")
                save_dir = h.get("save_dir", DOWNLOAD_DIR)
                break
    if not filename:
        return jsonify({"error": "Dosya bulunamadı"}), 404

    # Path traversal koruması
    if not safe_filepath(save_dir, filename):
        log.warning("Path traversal denemesi: job=%s file=%s", job_id, filename)
        return jsonify({"error": "Güvenlik hatası"}), 403

    filepath = os.path.join(save_dir, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Dosya silinmiş olabilir"}), 404

    s = load_settings()
    auto_delete = s.get("auto_delete_after_send", True)

    if auto_delete:
        import tempfile
        ext = os.path.splitext(filepath)[1]
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp.close()
        shutil.copy2(filepath, tmp.name)
        try:
            os.remove(filepath)
        except Exception:
            pass

        def cleanup(tmp_path):
            time.sleep(30)
            try: os.remove(tmp_path)
            except Exception: pass

        t = threading.Thread(target=cleanup, args=(tmp.name,), daemon=True)
        t.start()

        return send_file(tmp.name, as_attachment=True, download_name=filename.split("_", 1)[-1])
    else:
        return send_file(filepath, as_attachment=True, download_name=filename.split("_", 1)[-1])

@app.route("/api/history")
def get_history():
    search = request.args.get("q", "").strip().lower()
    fmt_filter = request.args.get("format", "").strip().lower()
    history = load_history()
    for item in history:
        fname    = item.get("filename", "")
        save_dir = item.get("save_dir", DOWNLOAD_DIR)
        item["file_exists"] = os.path.exists(os.path.join(save_dir, fname))
    # Filtreleme
    if search:
        history = [h for h in history if search in h.get("title", "").lower()
                   or search in h.get("uploader", "").lower()
                   or search in h.get("url", "").lower()]
    if fmt_filter:
        history = [h for h in history if h.get("format", "").lower() == fmt_filter]
    return jsonify(history)

@app.route("/api/history/<job_id>", methods=["DELETE"])
def delete_history_item(job_id):
    if not safe_job_id(job_id):
        return jsonify({"error": "Geçersiz job ID"}), 400
    with history_lock:
        history = [h for h in load_history() if h.get("job_id") != job_id]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})

@app.route("/api/history", methods=["DELETE"])
def clear_history():
    with history_lock:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    return jsonify({"ok": True})

# ── Disk & Temizlik ──────────────────────────────────────────
@app.route("/api/disk")
def disk_info():
    s        = load_settings()
    out_dir  = s.get("save_dir") or DOWNLOAD_DIR
    total, used, free = shutil.disk_usage(out_dir)
    dl_size = sum(
        os.path.getsize(os.path.join(out_dir, f))
        for f in os.listdir(out_dir)
        if os.path.isfile(os.path.join(out_dir, f))
    )
    return jsonify({
        "total":   total,
        "used":    used,
        "free":    free,
        "dl_size": dl_size,
        "dl_count": len([f for f in os.listdir(out_dir) if os.path.isfile(os.path.join(out_dir, f))]),
    })

@app.route("/api/clean", methods=["DELETE"])
def clean_downloads():
    s       = load_settings()
    out_dir = s.get("save_dir") or DOWNLOAD_DIR
    count   = 0
    for f in os.listdir(out_dir):
        fp = os.path.join(out_dir, f)
        if os.path.isfile(fp):
            os.remove(fp)
            count += 1
    log.info("İndirme klasörü temizlendi: %d dosya silindi", count)
    return jsonify({"deleted": count})

# ── Ayarlar ──────────────────────────────────────────────────
@app.route("/api/settings", methods=["GET"])
def get_settings():
    s = load_settings()
    s_safe = dict(s)
    if s_safe.get("access_password"):
        s_safe["access_password"] = "••••••"
    return jsonify(s_safe)

@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json()
    s    = load_settings()
    if "save_dir" in data:
        d = data["save_dir"].strip()
        if d and not os.path.exists(d):
            try: os.makedirs(d)
            except Exception as e:
                return jsonify({"error": str(e)}), 400
        s["save_dir"] = d or DOWNLOAD_DIR
    if "theme" in data:
        s["theme"] = data["theme"]
    if "auto_delete_after_send" in data:
        s["auto_delete_after_send"] = bool(data["auto_delete_after_send"])
    if "access_password" in data and data["access_password"] != "••••••":
        s["access_password"] = data["access_password"]
    save_settings(s)
    return jsonify({"ok": True})

# ── Sürüm & Changelog ────────────────────────────────────────
@app.route("/api/version")
def get_version():
    try:
        ytdlp_ver = yt_dlp.version.__version__
    except Exception:
        ytdlp_ver = "bilinmiyor"
    try:
        py_ver = sys.version.split()[0]
    except Exception:
        py_ver = "bilinmiyor"
    return jsonify({
        "app_version": APP_VERSION,
        "ytdlp_version": ytdlp_ver,
        "python_version": py_ver,
        "changelog": CHANGELOG,
    })

# ── yt-dlp Güncelleme (sadece localhost) ──────────────────────
@app.route("/api/update-ytdlp", methods=["POST"])
def update_ytdlp():
    # Güvenlik: Sadece localhost'tan erişime izin ver
    if request.remote_addr not in ("127.0.0.1", "::1"):
        log.warning("yt-dlp güncelleme engellendi: %s", request.remote_addr)
        return jsonify({"error": "Bu işlem sadece bilgisayardan yapılabilir."}), 403
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            log.info("yt-dlp güncellendi: %s", result.stdout.strip().split('\n')[-1])
            return jsonify({"ok": True, "output": result.stdout.strip()})
        else:
            return jsonify({"error": result.stderr.strip()}), 500
    except Exception as e:
        log.error("yt-dlp güncelleme hatası: %s", e)
        return jsonify({"error": str(e)}), 500

# ── Altyazı indirme ──────────────────────────────────────────
@app.route("/api/subtitles", methods=["POST"])
def download_subtitles():
    data = request.get_json()
    url  = data.get("url", "").strip()
    lang = data.get("lang", "tr")
    if not url:
        return jsonify({"error": "URL gerekli"}), 400

    job_id   = str(uuid.uuid4())[:8]
    with jobs_lock:
        jobs[job_id] = {"status": "downloading", "progress": 0, "created_at": time.time()}
    s        = load_settings()
    out_dir  = s.get("save_dir") or DOWNLOAD_DIR

    def sub_task():
        try:
            ydl_opts = {
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": [lang, "en"],
                "subtitlesformat": "srt",
                "outtmpl": os.path.join(out_dir, f"{job_id}_%(title)s.%(ext)s"),
                "quiet": True, "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info  = ydl.extract_info(url, download=True)
                title = sanitize_filename(info.get("title", "subtitle"))

            files = [f for f in os.listdir(out_dir) if f.startswith(job_id)]
            if files:
                with jobs_lock:
                    jobs[job_id].update({"status": "done", "progress": 100,
                                         "filename": files[0], "title": title, "save_dir": out_dir})
                save_history_entry({"job_id": job_id, "title": title, "url": url,
                    "format": "srt", "quality": "", "thumbnail": "",
                    "duration": 0, "uploader": "", "filesize": 0,
                    "filename": files[0], "save_dir": out_dir,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
            else:
                with jobs_lock:
                    jobs[job_id].update({"status": "error", "error": "Altyazı bulunamadı."})
        except Exception as e:
            with jobs_lock:
                jobs[job_id].update({"status": "error", "error": str(e)})
            log.error("Altyazı hatası: job=%s error=%s", job_id, e)

    threading.Thread(target=sub_task, daemon=True).start()
    return jsonify({"job_id": job_id})

# ── Video kesme ───────────────────────────────────────────────
@app.route("/api/trim", methods=["POST"])
def trim_video():
    data     = request.get_json()
    job_id   = data.get("job_id", "")
    start    = data.get("start", "0")
    end      = data.get("end", "")
    if not job_id:
        return jsonify({"error": "job_id gerekli"}), 400
    if not safe_job_id(job_id):
        return jsonify({"error": "Geçersiz job ID"}), 400

    with jobs_lock:
        job = dict(jobs.get(job_id, {}))
    filename = job.get("filename")
    save_dir = job.get("save_dir", DOWNLOAD_DIR)
    if not filename:
        hist = load_history()
        for h in hist:
            if h.get("job_id") == job_id:
                filename = h.get("filename"); save_dir = h.get("save_dir", DOWNLOAD_DIR); break
    if not filename:
        return jsonify({"error": "Dosya bulunamadı"}), 404

    src = os.path.join(save_dir, filename)
    ext = os.path.splitext(filename)[1]
    trim_id   = str(uuid.uuid4())[:8]
    out_name  = f"{trim_id}_trimmed{ext}"
    out_path  = os.path.join(save_dir, out_name)
    with jobs_lock:
        jobs[trim_id] = {"status": "processing", "progress": 50, "created_at": time.time()}

    def trim_task():
        try:
            cmd = ["ffmpeg", "-y", "-i", src, "-ss", str(start)]
            if end:
                cmd += ["-to", str(end)]
            cmd += ["-c", "copy", out_path]
            subprocess.run(cmd, check=True, capture_output=True)
            fsize = os.path.getsize(out_path)
            with jobs_lock:
                jobs[trim_id].update({"status": "done", "progress": 100,
                                       "filename": out_name, "title": "Kesilmiş video",
                                       "save_dir": save_dir})
            save_history_entry({"job_id": trim_id, "title": "Kesilmiş: " + filename,
                "url": "", "format": ext.lstrip("."), "quality": "",
                "thumbnail": "", "duration": 0, "uploader": "",
                "filesize": fsize, "filename": out_name, "save_dir": save_dir,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
        except Exception as e:
            with jobs_lock:
                jobs[trim_id].update({"status": "error", "error": str(e)})
            log.error("Trim hatası: job=%s error=%s", trim_id, e)

    threading.Thread(target=trim_task, daemon=True).start()
    return jsonify({"trim_job_id": trim_id})

# ── Ses hızı / pitch ─────────────────────────────────────────
@app.route("/api/speed", methods=["POST"])
def change_speed():
    data    = request.get_json()
    job_id  = data.get("job_id", "")
    speed   = float(data.get("speed", 1.0))
    pitch   = float(data.get("pitch", 1.0))
    if not job_id:
        return jsonify({"error": "job_id gerekli"}), 400
    if not safe_job_id(job_id):
        return jsonify({"error": "Geçersiz job ID"}), 400
    if not (0.25 <= speed <= 4.0):
        return jsonify({"error": "Hız 0.25-4.0 arasında olmalı"}), 400

    with jobs_lock:
        job = dict(jobs.get(job_id, {}))
    filename = job.get("filename")
    save_dir = job.get("save_dir", DOWNLOAD_DIR)
    if not filename:
        hist = load_history()
        for h in hist:
            if h.get("job_id") == job_id:
                filename = h.get("filename"); save_dir = h.get("save_dir", DOWNLOAD_DIR); break
    if not filename:
        return jsonify({"error": "Dosya bulunamadı"}), 404

    src      = os.path.join(save_dir, filename)
    ext      = os.path.splitext(filename)[1]
    sp_id    = str(uuid.uuid4())[:8]
    out_name = f"{sp_id}_speed{ext}"
    out_path = os.path.join(save_dir, out_name)
    with jobs_lock:
        jobs[sp_id] = {"status": "processing", "progress": 50, "created_at": time.time()}

    def speed_task():
        try:
            atempo_filters = []
            s = speed
            while s > 2.0:
                atempo_filters.append("atempo=2.0"); s /= 2.0
            while s < 0.5:
                atempo_filters.append("atempo=0.5"); s /= 0.5
            atempo_filters.append(f"atempo={s:.4f}")

            audio_filter = ",".join(atempo_filters)
            if pitch != 1.0:
                audio_filter += f",asetrate=44100*{pitch:.4f},aresample=44100"

            if ext.lower() in [".mp3", ".m4a", ".aac", ".wav"]:
                cmd = ["ffmpeg", "-y", "-i", src, "-filter:a", audio_filter, out_path]
            else:
                cmd = ["ffmpeg", "-y", "-i", src,
                       "-filter:a", audio_filter,
                       "-filter:v", f"setpts={1/speed:.4f}*PTS",
                       out_path]

            subprocess.run(cmd, check=True, capture_output=True)
            fsize = os.path.getsize(out_path)
            with jobs_lock:
                jobs[sp_id].update({"status": "done", "progress": 100,
                                     "filename": out_name, "title": f"Hız x{speed}",
                                     "save_dir": save_dir})
            save_history_entry({"job_id": sp_id, "title": f"Hız x{speed}: " + filename,
                "url": "", "format": ext.lstrip("."), "quality": "",
                "thumbnail": "", "duration": 0, "uploader": "",
                "filesize": fsize, "filename": out_name, "save_dir": save_dir,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
        except Exception as e:
            with jobs_lock:
                jobs[sp_id].update({"status": "error", "error": str(e)})
            log.error("Hız değiştirme hatası: job=%s error=%s", sp_id, e)

    threading.Thread(target=speed_task, daemon=True).start()
    return jsonify({"speed_job_id": sp_id})

# ── Share Target (Android Paylaş menüsü) ─────────────────────
@app.route("/share-target")
def share_target():
    from flask import redirect
    url   = request.args.get("url", "")
    text  = request.args.get("text", "")
    title = request.args.get("title", "")
    shared = url or text or title
    return redirect(f"/?shared={shared}")

# ── Aktif job'lar (çoklu indirme UI için) ─────────────────────
@app.route("/api/jobs")
def get_active_jobs():
    with jobs_lock:
        active = {jid: dict(j) for jid, j in jobs.items()
                  if j.get("status") in ("queued", "downloading", "processing")}
    return jsonify(active)

if __name__ == "__main__":
    log.info("FETCH v%s başlatılıyor — port 5000", APP_VERSION)
    app.run(debug=True, port=5000)
