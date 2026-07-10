FROM ghcr.io/astral-sh/uv:debian@sha256:12bcf9d33038200b3c7da0fa2b0f416482cf26ea764d0554fadf861d5d789833

WORKDIR /app

COPY vendor/pocket-tts/pyproject.toml ./
COPY vendor/pocket-tts/uv.lock ./
COPY vendor/pocket-tts/README.md ./
COPY vendor/pocket-tts/.python-version ./
COPY vendor/pocket-tts/pocket_tts ./pocket_tts

ENV UV_HTTP_TIMEOUT=600

RUN --mount=type=cache,target=/root/.cache/uv \
    for attempt in 1 2 3; do \
      uv sync --locked --no-dev && exit 0; \
      echo "Dependency installation attempt ${attempt} failed; retrying..."; \
      sleep 5; \
    done; \
    exit 1

RUN uv run --no-sync pocket-tts --help

ENTRYPOINT ["uv", "run", "--no-sync", "pocket-tts"]
