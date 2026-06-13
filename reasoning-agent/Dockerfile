# LSR Synaptic Response Center — backend image
# Mirrors the Microsoft Foundry Hosted Agent packaging model (OCI image → ACR → Agent Service).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# curl is used by the container healthcheck only.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first to maximise layer caching.
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source.
COPY . /app/

# Security: run as an unprivileged user, never root.
RUN useradd --create-home --uid 10001 lsr \
    && chown -R lsr:lsr /app
USER lsr

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
