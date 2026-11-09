#!/usr/bin/env bash
# Install the OCR runtime shared by every image that can process documents.
# Kept in one place so backend/worker/base images cannot drift on the language
# data the counterpart recovery pipeline depends on.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ell \
    tesseract-ocr-eng
rm -rf /var/lib/apt/lists/*
