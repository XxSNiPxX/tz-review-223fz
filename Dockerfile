# Review engine + web server. CPU only. Models and the knowledge base are mounted as volumes (see docker-compose.yml).
FROM python:3.10-slim

ARG WITH_LLM=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer libreoffice-calc p7zip-full file \
        $( [ "$WITH_LLM" = "1" ] && echo build-essential cmake ) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# CPU-only PyTorch (the default wheel ships ~3 GB of CUDA libraries that a CPU server never uses)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir scikit-learn sentence-transformers transformers huggingface_hub numpy joblib \
    && if [ "$WITH_LLM" = "1" ]; then pip install --no-cache-dir llama-cpp-python; fi

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
