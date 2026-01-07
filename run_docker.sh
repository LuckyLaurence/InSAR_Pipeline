#!/bin/bash
PROJECT_ROOT=$(pwd)
HOST_NETRC="$HOME/.netrc" 

# Does .netrc exist?
if [ ! -f "$HOST_NETRC" ]; then
    echo "❌ 找不到 $HOST_NETRC，请检查路径"
    exit 1
fi

docker run --rm -it \
  --env-file .env \
  -v "$PROJECT_ROOT/data:/app/data" \
  -v "$PROJECT_ROOT/code:/app/code" \
  -v "$HOME/.netrc:/tmp/host_netrc:ro" \
  insar-app:v1.5 python code/main_parallel.py