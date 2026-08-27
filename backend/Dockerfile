# Mirror, not registry-1.docker.io — see frontend/Dockerfile: the shared build
# IP hits Docker Hub's anonymous pull limit and the build fails on the FROM line.
FROM mirror.gcr.io/library/python:3.12-slim

WORKDIR /app

# System dependencies for psycopg2, yt-dlp, whisper
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Run migrations then start server (use python -m to avoid PATH issues)
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
