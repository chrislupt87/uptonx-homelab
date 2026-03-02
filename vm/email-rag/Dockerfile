FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_sm

COPY src/ ./src/
COPY sql/ ./sql/

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "email_rag.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
