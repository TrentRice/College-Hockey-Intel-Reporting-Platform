# CHIRP images, one per service, from one file. Code only: no data, no .env (see
# .dockerignore). The data lives in the Postgres volume and on this Mac through bind mounts;
# the API key is passed in when a container starts.
#
# Each target installs only its own dependency group (pyproject.toml), so the API image
# carries no Streamlit or pandas, and the dashboard no scraping libraries:
#   api        FastAPI + psycopg            docker compose builds target "api"
#   pipeline   scrapers, pandas, the loader target "pipeline"
#   dashboard  Streamlit                    target "dashboard"
# Build and run everything with: make up

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /app
# uv's download cache is a build cache mount (below), so it never ends up in an image
# never run as root
RUN useradd --system --uid 10001 chirp

# ---------------------------------------------------------------------------- api
FROM base AS api
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --group api --no-install-project
COPY config ./config
COPY src ./src
COPY db ./db
# The frozen win model's card (coefficients only; the .joblib file stays out of the image)
COPY models/*.json ./models/
USER chirp
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# 0.0.0.0 here is inside the container only. Who can reach it is decided by the published
# port in docker-compose.yml, which is 127.0.0.1 (this machine) only.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------- pipeline
FROM base AS pipeline
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --group pipeline --no-install-project
COPY config ./config
COPY src ./src
COPY db ./db
COPY models/*.json ./models/
USER chirp
CMD ["python", "-m", "src.pipeline.scheduler"]

# ---------------------------------------------------------------------------- dashboard
FROM base AS dashboard
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --group dashboard --no-install-project
COPY config ./config
COPY src ./src
COPY .streamlit ./.streamlit
USER chirp
EXPOSE 8501
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2)"]
CMD ["python", "-m", "streamlit", "run", "src/dashboard/app.py"]
