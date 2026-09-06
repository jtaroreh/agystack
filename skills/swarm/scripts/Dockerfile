FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    git-lfs \
    curl \
    ca-certificates \
    gnupg \
    build-essential \
    pkg-config \
    libssl-dev \
    bubblewrap \
    util-linux \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal \
    && chmod -R a+w /usr/local/cargo \
    && chmod -R a+w /usr/local/rustup

RUN useradd -m -u 1000 -s /bin/bash worker

RUN git lfs install --system

WORKDIR /app

RUN pip install --no-cache-dir google-antigravity google-cloud-storage google-cloud-run google-cloud-logging google-genai

COPY cloud_worker.py /app/cloud_worker.py
COPY storage_uploader.py /app/storage_uploader.py
COPY storage_messenger.py /app/storage_messenger.py

RUN mkdir -p /workspace \
    && chown -R worker:worker /workspace /app

USER worker

ENTRYPOINT ["python", "/app/cloud_worker.py"]
