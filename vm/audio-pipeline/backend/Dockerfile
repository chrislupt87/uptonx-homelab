FROM python:3.11-slim

# System deps: ffmpeg for audio decoding, libsndfile for soundfile,
# libgomp for OpenMP (librosa), git for pyannote
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 libgomp1 git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install CPU-only PyTorch FIRST — prevents pulling 2GB CUDA build
RUN pip install --no-cache-dir \
    torch==2.3.1+cpu \
    torchaudio==2.3.1+cpu \
    --extra-index-url https://download.pytorch.org/whl/cpu

# Install remaining dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-bake Whisper large-v3 at image build time (~3GB download)
RUN python -c "\
from faster_whisper import WhisperModel; \
print('Downloading Whisper large-v3...'); \
WhisperModel('large-v3', device='cpu', compute_type='int8'); \
print('Whisper large-v3 cached.')"

COPY . .

# 2 uvicorn workers — enough for single-user homelab use
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio", "--workers", "1"]
