#!/bin/bash

echo "============================================"
echo "  법령 AI 챗봇 서버 시작"
echo "============================================"

if [ ! -f ".env" ]; then
    echo "[오류] .env 파일이 없습니다."
    echo ".env.example 을 복사하여 .env 를 만들고 API 키를 입력하세요."
    exit 1
fi

echo "[1/2] 패키지 설치 중..."
pip install -r requirements.txt -q

echo "[2/2] 서버 시작 중..."
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "접속 주소: http://localhost:8000"
echo "내부망 접속: http://${IP}:8000"
echo ""
echo "종료하려면 Ctrl+C 를 누르세요."
echo "============================================"

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
