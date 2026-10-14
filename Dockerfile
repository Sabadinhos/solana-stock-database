FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# only Pillow (OG card); the rest is stdlib
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY collectors/meteora-dbc/package.json collectors/meteora-dbc/package-lock.json ./collectors/meteora-dbc/
RUN cd collectors/meteora-dbc && npm ci --omit=dev --ignore-scripts

COPY . .

# unprivileged user (does not run as root)
RUN useradd -m -u 1000 sdb && chown -R sdb:sdb /app
USER sdb

ENV PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080

# ingestor (StonkFun + Helius) in background, server in foreground
CMD ["sh", "-c", "if [ \"${SDB_DISABLE_EMBEDDED_SCHEDULER:-0}\" = \"1\" ]; then exec python server.py ${PORT:-8080}; else python scheduler.py ${SCHEDULE_SEC:-900} & exec python server.py ${PORT:-8080}; fi"]
