"""
FETCH Discord Botu
Kurulum:
  pip install discord.py requests
  
Kullanım:
  !indir <url>           → MP4 indirir
  !mp3 <url>             → MP3 indirir
  !altyazi <url>         → Altyazı indirir
  !yardim                → Komutları gösterir
"""

import discord
import requests
import asyncio
import time
import os

# ── AYARLAR ─────────────────────────────────────────────
DISCORD_TOKEN = "BURAYA_DISCORD_BOT_TOKEN"   # discord.com/developers
FETCH_URL     = "http://localhost:5000"       # FETCH sunucu adresi
FETCH_TOKEN   = ""                            # Ayarladıysan şifre, yoksa boş
PREFIX        = "!"
# ────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

HEADERS = {"X-Access-Token": FETCH_TOKEN} if FETCH_TOKEN else {}


def start_download(url, fmt="mp4", quality="best"):
    r = requests.post(f"{FETCH_URL}/api/download",
                      json={"url": url, "format": fmt, "quality": quality},
                      headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()["job_id"]


def start_subtitle(url, lang="tr"):
    r = requests.post(f"{FETCH_URL}/api/subtitles",
                      json={"url": url, "lang": lang},
                      headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()["job_id"]


def poll_job(job_id, timeout=300):
    """İş tamamlanana kadar bekle, (status, filename, title) döndür"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{FETCH_URL}/api/status/{job_id}",
                         headers=HEADERS, timeout=5)
        d = r.json()
        if d["status"] == "done":
            return d
        if d["status"] == "error":
            raise Exception(d.get("error", "Bilinmeyen hata"))
        time.sleep(2)
    raise Exception("Zaman aşımı")


async def send_file_from_fetch(channel, job_id, title, fmt):
    """FETCH'ten dosyayı alıp Discord'a gönder"""
    r = requests.get(f"{FETCH_URL}/api/file/{job_id}",
                     headers=HEADERS, stream=True, timeout=120)
    r.raise_for_status()

    # Dosya adını belirle
    ext = "mp3" if fmt == "mp3" else "srt" if fmt == "srt" else "mp4"
    fname = f"{title[:50]}.{ext}"
    tmp_path = os.path.join(os.path.dirname(__file__), f"tmp_{job_id}.{ext}")

    with open(tmp_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    try:
        await channel.send(
            content=f"✅ **{title}**",
            file=discord.File(tmp_path, filename=fname)
        )
    finally:
        try: os.remove(tmp_path)
        except: pass


@client.event
async def on_ready():
    print(f"FETCH Discord Botu aktif: {client.user}")


@client.event
async def on_message(msg):
    if msg.author == client.user:
        return

    content = msg.content.strip()
    parts   = content.split(maxsplit=1)
    cmd     = parts[0].lower() if parts else ""
    arg     = parts[1].strip() if len(parts) > 1 else ""

    if cmd == f"{PREFIX}yardim":
        embed = discord.Embed(title="FETCH Bot Komutları", color=0xc8f03d)
        embed.add_field(name=f"{PREFIX}indir <url>",   value="MP4 video indir",     inline=False)
        embed.add_field(name=f"{PREFIX}mp3 <url>",     value="MP3 ses indir",        inline=False)
        embed.add_field(name=f"{PREFIX}altyazi <url>", value="Altyazı .srt indir",  inline=False)
        embed.set_footer(text="FETCH Medya İndirici")
        await msg.channel.send(embed=embed)
        return

    if cmd in (f"{PREFIX}indir", f"{PREFIX}mp3", f"{PREFIX}altyazi"):
        if not arg:
            await msg.channel.send("⚠️ URL gerekli. Örnek: `!indir https://youtube.com/...`")
            return

        fmt = "mp3" if cmd == f"{PREFIX}mp3" else "srt" if cmd == f"{PREFIX}altyazi" else "mp4"
        status_msg = await msg.channel.send(f"⏳ İndiriliyor...")

        try:
            loop = asyncio.get_event_loop()
            if fmt == "srt":
                job_id = await loop.run_in_executor(None, start_subtitle, arg, "tr")
            else:
                job_id = await loop.run_in_executor(None, start_download, arg, fmt)

            await status_msg.edit(content=f"📥 %0 işleniyor...")

            # Poll
            job = await loop.run_in_executor(None, poll_job, job_id)
            await status_msg.edit(content=f"📤 Yükleniyor...")

            await send_file_from_fetch(msg.channel, job_id, job.get("title", "dosya"), fmt)
            await status_msg.delete()

        except Exception as e:
            await status_msg.edit(content=f"❌ Hata: {e}")


client.run(DISCORD_TOKEN)
