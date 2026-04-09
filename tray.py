"""
FETCH — Sistem Tepsisi Uygulaması
Tamamen arka planda çalışır, terminal veya pencere açmaz.
"""

import threading
import webbrowser
import os
import sys

from PIL import Image, ImageDraw
import pystray
from pyngrok import ngrok

sys.path.insert(0, os.path.dirname(__file__))
from app import app as flask_app

# ── Global state ─────────────────────────────────────────────
ngrok_url    = None
tray_icon    = None


# ── İkon ─────────────────────────────────────────────────────
def create_tray_image(connected=False):
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size-1, size-1], radius=14, fill="#0a0a0a")
    accent = "#c8f03d" if connected else "#555555"
    x, y = 16, 12
    d.rectangle([x, y,      x+26, y+5],  fill=accent)
    d.rectangle([x, y,      x+5,  y+40], fill=accent)
    d.rectangle([x, y+17,   x+20, y+22], fill=accent)
    return img


def create_icon_files():
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_dir, exist_ok=True)
    for size in [192, 512]:
        path = os.path.join(static_dir, f"icon-{size}.png")
        if not os.path.exists(path):
            img = Image.new("RGBA", (size, size), (0,0,0,0))
            d   = ImageDraw.Draw(img)
            r   = size // 5
            d.rounded_rectangle([0,0,size-1,size-1], radius=r, fill="#0a0a0a")
            m   = size // 8
            w   = size - 2*m
            bw  = max(2, w//5)
            d.rectangle([m, m, m+w, m+bw], fill="#c8f03d")
            d.rectangle([m, m, m+bw, m+w], fill="#c8f03d")
            my  = m + w//2 - bw//2
            d.rectangle([m, my, m+int(w*0.65), my+bw], fill="#c8f03d")
            img.save(path, "PNG")


# ── Windows bildirimi (tkinter YOK) ──────────────────────────
def win_notify(title, msg):
    """Görev çubuğu balonu — tkinter gerektirmez"""
    try:
        from ctypes import windll, wintypes
        import ctypes
        # Basit mesaj kutusu yerine tray balonu kullan
        if tray_icon:
            tray_icon.notify(msg, title)
    except Exception:
        pass


def copy_to_clipboard(text):
    """Panoya kopyala — tkinter YOK"""
    try:
        import subprocess
        subprocess.run(['clip'], input=text.encode('utf-8'), check=True)
    except Exception:
        pass


# ── Flask ─────────────────────────────────────────────────────
def start_flask():
    flask_app.run(port=5000, use_reloader=False, threaded=True)


# ── Ngrok ─────────────────────────────────────────────────────
def start_ngrok():
    global ngrok_url
    try:
        try: ngrok.kill()
        except Exception: pass
        import time; time.sleep(1)
        tunnel    = ngrok.connect(5000, "http")
        ngrok_url = tunnel.public_url
        # İkonu yeşile çevir
        if tray_icon:
            tray_icon.icon  = create_tray_image(connected=True)
            tray_icon.title = f"FETCH — {ngrok_url}"
    except Exception as e:
        ngrok_url = None
        if tray_icon:
            tray_icon.title = "FETCH — Ngrok baglanti hatasi"
            tray_icon.notify("Ngrok Hatasi", "Authtoken gecersiz veya eksik. Lutfen kontrol edin.")


# ── Menü aksiyonları ─────────────────────────────────────────
def action_open(icon, item):
    webbrowser.open("http://localhost:5000")

def action_show_ngrok(icon, item):
    if ngrok_url and not str(ngrok_url).startswith("HATA"):
        win_notify("Ngrok Linki", ngrok_url)
    else:
        win_notify("FETCH", "Ngrok henüz hazır değil...")

def action_copy_ngrok(icon, item):
    if ngrok_url:
        copy_to_clipboard(ngrok_url)
        win_notify("FETCH", "Link panoya kopyalandı!")

def action_quit(icon, item):
    try: ngrok.kill()
    except Exception: pass
    icon.stop()
    os._exit(0)


# ── Menü ─────────────────────────────────────────────────────
def build_menu():
    return pystray.Menu(
        pystray.MenuItem("FETCH Medya İndirici", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Tarayıcıda Aç",       action_open,        default=True),
        pystray.MenuItem("Ngrok Linkini Göster", action_show_ngrok),
        pystray.MenuItem("Linki Kopyala",        action_copy_ngrok),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Çıkış",                action_quit),
    )


# ── Ana giriş ─────────────────────────────────────────────────
def main():
    global tray_icon

    create_icon_files()

    threading.Thread(target=start_flask, daemon=True).start()
    threading.Thread(target=start_ngrok, daemon=True).start()

    tray_icon = pystray.Icon(
        name  = "FETCH",
        icon  = create_tray_image(connected=False),
        title = "FETCH — Başlatılıyor...",
        menu  = build_menu(),
    )
    tray_icon.run()


if __name__ == "__main__":
    main()
