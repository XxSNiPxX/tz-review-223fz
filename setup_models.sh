#!/usr/bin/env bash
# Install the local model stack (CPU only) and download the open-weight models into models/.
#   tier 2: scikit-learn baselines, sentence-transformers embeddings (intfloat/multilingual-e5-small, ~470 MB)
#   tier 3: Qwen2.5-7B-Instruct GGUF Q4_K_M (~4.7 GB, bartowski single-file build) via llama-cpp-python
set -e
cd "$(dirname "$0")"
[ -d .venv ] && source .venv/bin/activate
pip install -q scikit-learn sentence-transformers "huggingface_hub[cli]" numpy
pip install -q llama-cpp-python
mkdir -p models
export HF_HUB_ENABLE_HF_TRANSFER=0
python3 - <<'EOF'
from huggingface_hub import snapshot_download, hf_hub_download
p = snapshot_download("intfloat/multilingual-e5-small", local_dir="models/multilingual-e5-small")
print("embeddings:", p)
g = hf_hub_download("bartowski/Qwen2.5-7B-Instruct-GGUF", "Qwen2.5-7B-Instruct-Q4_K_M.gguf", local_dir="models")
print("llm:", g)
EOF
ls -la models | head
