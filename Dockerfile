FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg sox ttf-mscorefonts-installer fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=5000
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/service_account.json

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
