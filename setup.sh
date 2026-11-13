#!/usr/bin/env bash
# One-shot setup of a full local instance: knowledge base + fine-tuned models (GitHub release)
# and open-weight base models (Hugging Face). Nothing here is needed again at review time.
#   ./setup.sh            everything (~5.5 GB download, LLM included)
#   ./setup.sh --no-llm   skip the 4.7 GB Qwen GGUF (rules + small models only)
set -e
cd "$(dirname "$0")"
REPO=${REPO:-XxSNiPxX/tz-review-223fz}
TAG=${TAG:-v1.0}
URL="https://github.com/$REPO/releases/download/$TAG"
mkdir -p data models

fetch() { [ -f "$1" ] || curl -fL --retry 3 -o "$1" "$URL/$1"; }
echo "== 1/3 knowledge base and fine-tuned models ($URL)"
fetch tz-review-kb.tar.gz; fetch tz-review-models.tar.gz; fetch tz-review.sha256
sha256sum -c tz-review.sha256
tar xzf tz-review-kb.tar.gz && tar xzf tz-review-models.tar.gz

echo "== 2/3 embeddings: intfloat/multilingual-e5-small (~470 MB)"
python3 -m pip install -q "huggingface_hub>=0.23"
python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("intfloat/multilingual-e5-small", local_dir="models/multilingual-e5-small",
                  ignore_patterns=["onnx/*", "openvino/*", "*.bin"])
PY

if [ "$1" != "--no-llm" ]; then
  echo "== 3/3 LLM: Qwen2.5-7B-Instruct Q4_K_M GGUF (~4.7 GB)"
  python3 - <<'PY'
from huggingface_hub import hf_hub_download
hf_hub_download("bartowski/Qwen2.5-7B-Instruct-GGUF", "Qwen2.5-7B-Instruct-Q4_K_M.gguf", local_dir="models")
PY
else echo "== 3/3 LLM skipped"; fi
echo "Ready. Start with:  docker compose up --build -d   ->  http://localhost:8000"
