#!/bin/bash

echo "개발 환경 시작 중..."

echo "도커 컨테이너 빌드 및 시작..."
docker-compose up -d --build

echo "서비스 접속 정보:"
echo ""
echo "프론트엔드: http://localhost:3000"
echo "백엔드 API: http://localhost:8000/api"
echo "API 문서: http://localhost:8000/docs"
echo "MinIO 콘솔: http://localhost:9001 (minioadmin/minioadmin)"
echo "PostgreSQL: localhost:5432 (postgres/password)"
echo ""
echo "로그를 확인하려면 'docker-compose logs -f' 명령어를 사용하세요."
echo "서비스를 중지하려면 'docker-compose down' 명령어를 사용하세요."
echo "" 