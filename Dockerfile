# Review engine + web server. CPU only. Models and the knowledge base are mounted as volumes (see docker-compose.yml).
FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer libreoffice-calc p7zip-full file build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir scikit-learn sentence-transformers huggingface_hub numpy llama-cpp-python

COPY procdata ./procdata
COPY web ./web
COPY kb ./kb
COPY schema.sql config.yaml collect.py review.py server.py eval_case.py setup_models.sh setup_ru_certs.sh ./
RUN mkdir -p data models certs

ENV PYTHONUNBUFFERED=1 \
    REVIEW_HOST=0.0.0.0 \
    REVIEW_PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/kb')" || exit 1
CMD ["sh", "-c", "uvicorn server:app --host ${REVIEW_HOST} --port ${REVIEW_PORT}"]
