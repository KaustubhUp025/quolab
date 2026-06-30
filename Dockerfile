# Digest-pinned base for reproducible builds (python:3.12-slim at pin time).
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

# git is needed for shallow-clone fetching of target repos.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md requirements-lock.txt ./
COPY src ./src

# Reproducible install: pinned, hash-verified transitive deps first (runtime + pg extra),
# then the package itself without re-resolving dependencies.
RUN pip install --no-cache-dir --require-hashes -r requirements-lock.txt \
    && pip install --no-cache-dir --no-deps ".[pg]"

ENV QUOLAB_HOST=0.0.0.0 \
    QUOLAB_PORT=8080 \
    QUOLAB_STORE=pgvector

EXPOSE 8080
CMD ["python", "-m", "quolab.app"]
