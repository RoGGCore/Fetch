FROM python:3.11-slim

# ffmpeg kurulumu
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bağımlılıkları yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama dosyalarını kopyala
COPY . .

# downloads klasörünü oluştur
RUN mkdir -p downloads

# Port
EXPOSE 5000

# Başlat
CMD ["python", "app.py"]
