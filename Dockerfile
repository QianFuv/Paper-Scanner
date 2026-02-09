FROM python:3.12.2-slim AS build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

COPY scripts/ scripts/

RUN uv sync --frozen --no-dev


FROM python:3.12.2-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends libstdc++6 libgcc-s1 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY --from=build /app/.venv .venv/
COPY --from=build /app/pyproject.toml ./
COPY --from=build /app/scripts scripts/

COPY libs/simple-linux libs/simple-linux
COPY data/meta data/meta

ENV PATH="/app/.venv/bin:$PATH"
ENV API_HOST="0.0.0.0"

EXPOSE 8000

CMD ["uv", "run", "api"]
