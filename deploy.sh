#!/bin/bash
# 배포 스크립트 — 로컬에서 실행
# 사용법: ./deploy.sh

set -e

HOST="ec2-user@3.26.145.173"
KEY="~/.ssh/bot.pem"
REMOTE_DIR="~/value-copilot"

echo "=== [1/3] 파일 전송 ==="
rsync -az --progress \
  -e "ssh -i $KEY" \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='backend/.scratchpad' \
  --exclude='scripts/server-setup.sh' \
  . "$HOST:$REMOTE_DIR/"

echo "=== [2/3] .env 전송 ==="
scp -i "$KEY" .env "$HOST:$REMOTE_DIR/.env"

echo "=== [3/3] 빌드 & 재시작 ==="
ssh -i "$KEY" "$HOST" "
  set -e
  cd $REMOTE_DIR
  docker compose -f docker-compose.prod.yml pull --ignore-buildable 2>/dev/null || true
  docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
  echo ''
  echo '--- 컨테이너 상태 ---'
  docker compose -f docker-compose.prod.yml ps
"

echo ""
echo "=== 배포 완료 ==="
echo "접속: http://3.26.145.173"
