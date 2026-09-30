FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    fonts-liberation \
    fontconfig \
    ca-certificates \
    && fc-cache -f -v \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=3002

# Un solo worker: el directo vive en un hilo de este proceso.
# El POST /live/start responde enseguida; el timeout cubre solo esa respuesta.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 120 app:app
