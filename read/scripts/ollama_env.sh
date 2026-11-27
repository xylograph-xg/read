#!/bin/bash
# 由配置/启动脚本 source；使用专用端口，不依赖 Ollama App 的默认服务。
export OLLAMA_MODELS="${HOME}/venv/models"
export OLLAMA_HOST="127.0.0.1:11435"
export OLLAMA_NO_CLOUD=1
READ_OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"
READ_OLLAMA_LOG="${HOME}/venv/logs/ollama.log"

start_read_ollama() {
  if [ ! -x "$READ_OLLAMA_BIN" ]; then
    echo "没有找到 Ollama：$READ_OLLAMA_BIN"
    return 1
  fi
  mkdir -p "$OLLAMA_MODELS" "$(dirname "$READ_OLLAMA_LOG")"
  if curl -fsS --max-time 2 "http://$OLLAMA_HOST/api/version" >/dev/null 2>&1; then
    return 0
  fi
  # A separate session keeps the service alive after the launcher exits.
  "${READ_OLLAMA_PYTHON:-${HOME}/venv/bin/python}" - "$READ_OLLAMA_BIN" "$READ_OLLAMA_LOG" <<'PY_START'
import subprocess, sys
with open(sys.argv[2], 'ab') as log:
    subprocess.Popen([sys.argv[1], 'serve'], stdin=subprocess.DEVNULL,
                     stdout=log, stderr=log, start_new_session=True)
PY_START
  for read_attempt in {1..30}; do
    if curl -fsS --max-time 2 "http://$OLLAMA_HOST/api/version" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Ollama 启动失败，请检查 $READ_OLLAMA_LOG"
  return 1
}
