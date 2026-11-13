# 쿠팡 WING 매니저 — Docker 이미지
# 여러 플랫폼용(linux/amd64 · linux/arm64 · linux/arm/v7)으로 빌드합니다. Windows·macOS 는 Docker Desktop 이 linux 이미지를 실행합니다.

# --- 새 화면(React + Astryx) 번들 ---
# static/dist/ 는 .gitignore 대상이라 repo 에 없다. 여기서 만들지 않으면 이미지에
# 번들이 없어 운영에서 /ui 가 503 을 준다.
# --platform=$BUILDPLATFORM: 번들은 아키텍처와 무관한 정적 파일이다. 빌드 호스트에서
# 한 번만 만들어 3개 플랫폼이 함께 쓴다 — arm/v7 에뮬레이션으로 Rollup 을 돌리지 않는다.
FROM --platform=$BUILDPLATFORM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# vite.config.ts 의 outDir 이 ../static/dist 이므로 /app/static/dist 에 나온다
RUN npx vite build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul \
    WING_IN_DOCKER=1

# tzdata: 알림·이력 시각을 한국 시간으로 (TZ 로 바꿀 수 있음)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 wing \
 && mkdir -p /data && chown wing:wing /data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# 번들은 빌더 단계에서 가져온다 (빌드 호스트에 남아 있던 낡은 dist 를 쓰지 않도록
# .dockerignore 에서 static/dist 를 뺀다)
COPY --from=web /app/static/dist ./static/dist
# 프런트 소스는 실행에 필요 없다
RUN rm -rf /app/web && chmod 755 /app/docker-entrypoint.sh

# root 로 시작해 /data 권한을 맞춘 뒤 일반 사용자(PUID/PGID, 기본 1000)로 바꿔 실행한다 (docker-entrypoint.sh)
ENV PUID=1000 PGID=1000
VOLUME ["/data"]
EXPOSE 26118

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:26118/api/ping', timeout=4).status == 200 else 1)"

# 데이터(설정·DB·이미지·로그인 정보)는 모두 /data 볼륨에 저장됩니다.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "portable.py", "--no-browser", "--host", "0.0.0.0", "--port", "26118", "--data", "/data"]
