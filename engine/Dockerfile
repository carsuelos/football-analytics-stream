# The engine: a virtualenv built by uv, copied onto a slim Python base.
# Build context: engine/. The xT grid is mounted at run time, not baked in.
ARG PYTHON=3.13

FROM python:${PYTHON}-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# Dependencies first, so code changes reuse this layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

FROM python:${PYTHON}-slim
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER nobody
EXPOSE 8000
ENTRYPOINT ["engine", "--host", "0.0.0.0", "--port", "8000", "--xt-grid", "/data/xt/open_xt_12x8_v1.json"]
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=2)"]
