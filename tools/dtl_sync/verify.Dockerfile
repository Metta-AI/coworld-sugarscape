FROM python:3.13.5-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.13
WORKDIR /dependencies
COPY pyproject.toml ./
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync \
    && uv export --no-hashes > /opt/dependencies.txt \
    && git config --system --add safe.directory /workspace \
    && git config --system --add safe.directory /workspace/src/sugarscape
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
