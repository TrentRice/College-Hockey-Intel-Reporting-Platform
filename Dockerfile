# CHIRP API image. Code only: no data, no .env (see .dockerignore). The data lives in the
# Postgres volume and the API key is passed in when the container starts.
# Build and run with: make api-up
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# dependencies first, so code changes don't reinstall them
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY config ./config
COPY src ./src
COPY db ./db
COPY .streamlit ./.streamlit

# never run as root
RUN useradd --system --uid 10001 chirp
USER chirp

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# 0.0.0.0 here is inside the container only. Who can reach it is decided by the published
# port in docker-compose.yml, which is 127.0.0.1 (this machine) only.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
