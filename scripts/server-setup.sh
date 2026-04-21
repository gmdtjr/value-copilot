#!/bin/bash
# EC2 초기 설정 스크립트 (최초 1회만 실행)
# 사용법: ./scripts/server-setup.sh

set -e

HOST="ec2-user@3.26.145.173"
KEY="~/.ssh/bot.pem"

echo "=== EC2 Docker 설치 ==="
ssh -i "$KEY" "$HOST" '
  set -e

  echo "--- Docker 설치 ---"
  sudo dnf update -y
  sudo dnf install -y docker
  sudo systemctl start docker
  sudo systemctl enable docker
  sudo usermod -aG docker ec2-user

  echo "--- Docker Compose 플러그인 설치 ---"
  sudo mkdir -p /usr/local/lib/docker/cli-plugins
  sudo curl -SL https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-linux-x86_64 \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

  echo "--- 프로젝트 디렉토리 생성 ---"
  mkdir -p ~/value-copilot

  echo "--- 설치 완료 ---"
  docker --version
  docker compose version
'

echo ""
echo "=== 완료 ==="
echo "중요: SSH 재접속 후 docker 그룹이 적용됩니다."
echo "다음 단계: ./deploy.sh 실행"
