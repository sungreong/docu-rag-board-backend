@echo off
echo 프로덕션 환경 시작 중...

echo 도커 컨테이너 빌드 및 시작...
docker-compose -f docker-compose.prod.yml up -d --build

echo 서비스 접속 정보:
echo.
echo 웹 애플리케이션: http://localhost
echo API 문서: http://localhost/docs
echo.
echo 로그를 확인하려면 'docker-compose -f docker-compose.prod.yml logs -f' 명령어를 사용하세요.
echo 서비스를 중지하려면 'docker-compose -f docker-compose.prod.yml down' 명령어를 사용하세요.
echo. 