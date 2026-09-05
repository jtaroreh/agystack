#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
export RUSTUP_HOME="${RUSTUP_HOME:-/usr/local/rustup}"
export CARGO_HOME="${CARGO_HOME:-/usr/local/cargo}"
export PATH="${CARGO_HOME}/bin:${PATH}"

apt-get update && apt-get install -y --no-install-recommends \
    git \
    git-lfs \
    curl \
    ca-certificates \
    gnupg \
    build-essential \
    pkg-config \
    libssl-dev \
    bubblewrap \
    util-linux

mkdir -p /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y --no-install-recommends nodejs
apt-get clean
rm -rf /var/lib/apt/lists/*

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.80.0 --profile minimal
chmod -R a+w "${CARGO_HOME}"
chmod -R a+rx "${RUSTUP_HOME}"

if ! id -u worker >/dev/null 2>&1; then
    useradd -m -u 1000 -s /bin/bash worker
fi

git lfs install --system
