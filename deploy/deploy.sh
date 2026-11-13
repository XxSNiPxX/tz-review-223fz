#!/usr/bin/env bash
# Deploy the review server to a VPS so it is reachable on http://<HOST>/
#   ./deploy/deploy.sh root@185.17.3.218            # rules + retrieval (no LLM), ~1 GB upload
#   WITH_LLM=1 ./deploy/deploy.sh root@HOST          # also upload Qwen (4.7 GB) and build llama.cpp (needs ~10 GB RAM)
#   REVIEW_BASIC_AUTH=jury:secret ./deploy/deploy.sh root@HOST   # protect the page with a login
# Step 1b stops other services on ports 80/443/8000 (docker: stop, restart=no; systemd: stop+disable; others: kill)
# and records them in /opt/tz-review/stopped_services.txt so they can be restored.
# Uses SSH keys only (BatchMode): run `ssh-copy-id root@HOST` once beforehand.
set -euo pipefail
TARGET="${1:?usage: deploy.sh user@host}"
HOST="${TARGET#*@}"
WITH_LLM="${WITH_LLM:-0}"
LITE="${LITE:-auto}"                      # auto: lite when the server has < 2 GB RAM
DIR=/opt/tz-review
cd "$(dirname "$0")/.."
SSH="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new $TARGET"

echo "== 1/6 SSH check (key-based)"
$SSH 'echo connected: $(hostname) $(. /etc/os-release; echo $PRETTY_NAME) cpu=$(nproc) ram=$(free -g | awk "/Mem/{print \$2}")G disk_free=$(df -h / | awk "NR==2{print \$4}")'

echo "== 1b Stop whatever else serves on ports 80/443/8000 (recorded in $DIR/stopped_services.txt for restore)"
$SSH "mkdir -p $DIR; LOG=$DIR/stopped_services.txt; date >> \$LOG
  echo '--- listeners before:'; ss -ltnp | grep -E ':(80|443|8000)\\b' || echo none
  if command -v docker >/dev/null; then
    for c in \$(docker ps --format '{{.ID}} {{.Names}} {{.Ports}}' | grep -E ':(80|443|8000)->' | grep -v ' tz-review ' | awk '{print \$1}'); do
      echo \"docker container \$(docker inspect -f '{{.Name}} {{.Config.Image}} restart={{.HostConfig.RestartPolicy.Name}}' \$c)\" | tee -a \$LOG
      docker update --restart=no \$c >/dev/null; docker stop \$c >/dev/null && echo '  stopped (not removed)'
    done
  fi
  for pid in \$(ss -ltnpH | grep -E ':(80|443|8000)\\b' | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do
    unit=\$(ps -o unit= -p \$pid 2>/dev/null | tr -d ' ')
    if [ -n \"\$unit\" ] && [ \"\$unit\" != '-' ] && systemctl is-active --quiet \"\$unit\" 2>/dev/null && ! echo \"\$unit\" | grep -q -E '^(docker|containerd)'; then
      echo \"systemd unit \$unit (pid \$pid: \$(ps -o cmd= -p \$pid | cut -c1-120))\" | tee -a \$LOG
      systemctl stop \"\$unit\"; systemctl disable \"\$unit\" 2>/dev/null; echo '  stopped and disabled'
    elif ! ps -o cmd= -p \$pid | grep -q -E 'docker-proxy|containerd'; then
      echo \"process \$pid: \$(ps -o cmd= -p \$pid | cut -c1-160)\" | tee -a \$LOG
      kill \$pid && echo '  terminated'
    fi
  done
  sleep 2; echo '--- listeners after:'; ss -ltnp | grep -E ':(80|443|8000)\\b' || echo none"

RAM_MB=$($SSH "free -m | awk '/Mem/{print \$2}'")
if [ "$LITE" = "auto" ]; then LITE=$([ "$RAM_MB" -lt 2000 ] && echo 1 || echo 0); fi
echo "   RAM ${RAM_MB} MB -> LITE=$LITE"
echo "== 1c Swap (2 GB) if none"
$SSH 'swapon --show | grep -q . && echo "swap present" || (fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile && grep -q "^/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab; swapon --show)'

echo "== 2/6 Docker"
$SSH 'command -v docker >/dev/null && docker compose version >/dev/null 2>&1 && echo "docker present" || (export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && (apt-get install -y -qq docker.io docker-compose-v2 || apt-get install -y -qq docker.io docker-compose-plugin) && systemctl enable --now docker && docker --version)'
$SSH "mkdir -p $DIR/data/index $DIR/models"

echo "== 3/6 Code (tracked files only)"
git ls-files -z | rsync -az --from0 --files-from=- ./ "$TARGET:$DIR/"
rsync -az deploy/ "$TARGET:$DIR/deploy/"

echo "== 4/6 Knowledge base and models"
rsync -az --info=progress2 data/procurement.sqlite "$TARGET:$DIR/data/"
rsync -az data/index/ "$TARGET:$DIR/data/index/"
[ -d data/case ] && rsync -az data/case/ "$TARGET:$DIR/data/case/"
[ -d data/samples ] && rsync -az data/samples/ "$TARGET:$DIR/data/samples/"
E5=models/multilingual-e5-small
if [ "$LITE" != "1" ]; then rsync -az --relative "$E5/./config.json" "$E5/./model.safetensors" "$E5/./modules.json" "$E5/./sentence_bert_config.json" \
      "$E5/./tokenizer.json" "$E5/./tokenizer_config.json" "$E5/./special_tokens_map.json" "$E5/./sentencepiece.bpe.model" "$E5/./1_Pooling" \
      "$TARGET:$DIR/models/multilingual-e5-small/" 2>/dev/null || rsync -az --exclude onnx --exclude openvino --exclude pytorch_model.bin --exclude .eval_results "$E5/" "$TARGET:$DIR/$E5/"
[ -d models/clause-role ] && rsync -az models/clause-role/ "$TARGET:$DIR/models/clause-role/"; fi
if [ "$WITH_LLM" = "1" ]; then rsync -az --info=progress2 models/Qwen2.5-7B-Instruct-Q4_K_M.gguf "$TARGET:$DIR/models/"; fi

echo "== 5/6 Build and start (first build 5-10 min)"
$SSH "cd $DIR && printf 'WITH_LLM=%s\nLITE=%s\nREVIEW_BASIC_AUTH=%s\n' '$WITH_LLM' '$LITE' '${REVIEW_BASIC_AUTH:-}' > deploy/.env && \
      docker compose --env-file deploy/.env -f deploy/docker-compose.vps.yml up -d --build && \
      (command -v ufw >/dev/null && ufw status | grep -q active && ufw allow 80/tcp || true)"

echo "== 6/6 Health check"
for i in $(seq 1 30); do
  if curl -s -m 5 "http://$HOST/api/health" | grep -q ok; then echo "UP: http://$HOST/"; exit 0; fi; sleep 5
done
echo "not responding yet; logs:"; $SSH "cd $DIR && docker compose -f deploy/docker-compose.vps.yml logs --tail 40"; exit 1
