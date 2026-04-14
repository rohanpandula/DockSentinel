FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (as root) — curl for HEALTHCHECK, node for CLI backends.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex@latest @google/gemini-cli@latest

# Create non-root user BEFORE COPY so --chown can land in a single layer.
RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser --home-dir /home/appuser --create-home appuser

# DOCK-03: deps layer cached separately from app code.
COPY --chown=appuser:appuser requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App code last (cache miss here doesn't re-run pip install).
COPY --chown=appuser:appuser . /app
RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:5000/api/health || exit 1

CMD ["/app/docker-entrypoint.sh"]
