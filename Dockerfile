FROM python:3.12-slim

# git is needed for shallow-clone fetching of target repos.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

# Install the package. Add the 'pg' extra for the pgvector store in production.
RUN pip install --no-cache-dir ".[pg]"

ENV QUOLAB_HOST=0.0.0.0 \
    QUOLAB_PORT=8080 \
    QUOLAB_STORE=pgvector

EXPOSE 8080
CMD ["python", "-m", "quolab.app"]
