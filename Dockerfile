FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Links the GHCR package to the repository (and its README, licence and permissions).
LABEL org.opencontainers.image.source="https://github.com/Constantin-Hentgen/Remy" \
      org.opencontainers.image.description="Remy: self-hosted nutrition tracking for endurance athletes" \
      org.opencontainers.image.licenses="MIT"

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer stays cached while pyproject.toml and uv.lock do not change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra server --extra postgres --no-install-project

COPY README.md LICENSE NOTICE ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra server --extra postgres --no-editable

# /data holds the SQLite database (named volume; it inherits these permissions when first created).
RUN useradd --system --no-create-home remy && mkdir -p /data && chown remy /data
VOLUME /data
USER remy

ENV PATH="/app/.venv/bin:$PATH" DATABASE_URL=sqlite:////data/remy.db
EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["remy", "serve"]
