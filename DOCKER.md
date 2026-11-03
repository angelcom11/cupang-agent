# Docker로 설치하기

Windows · macOS · Linux · NAS · 라즈베리파이 어디서나 같은 방법으로 실행합니다.

| 이미지 플랫폼 | 쓰는 곳 |
|---|---|
| `linux/amd64` | 일반 PC·서버, Windows/Mac(인텔) Docker Desktop, 대부분의 NAS |
| `linux/arm64` | Apple 실리콘 Mac(M1~M4) Docker Desktop, 라즈베리파이 4·5(64비트), ARM 서버 |
| `linux/arm/v7` | 32비트 라즈베리파이 OS 등 |

Docker가 내 컴퓨터에 맞는 것을 자동으로 고릅니다.

## 1. 준비
- Windows / Mac: [Docker Desktop](https://www.docker.com/products/docker-desktop/) 설치
- Linux: Docker Engine + Compose 플러그인 설치
- 이미지 저장소(`ghcr.io/angelcom11/cupang-agent`)가 **비공개**이면 한 번 로그인합니다.
  GitHub에서 `read:packages` 권한 토큰을 만든 뒤:
  ```bash
  docker login ghcr.io -u angelcom11      # 비밀번호 칸에 토큰
  ```

## 2. 실행
[`docker-compose.yml`](docker-compose.yml) 파일을 받아 아무 폴더에 두고:
```bash
docker compose up -d
```
또는 compose 없이:
```bash
docker run -d --name wing-manager --restart unless-stopped \
  -p 26118:26118 -v wing-data:/data -e TZ=Asia/Seoul \
  ghcr.io/angelcom11/cupang-agent:latest
```
브라우저에서 **http://<이 컴퓨터 IP>:26118** (같은 컴퓨터면 http://127.0.0.1:26118).

## 3. 처음 계정 만들기
처음 접속하면 '관리자 계정 만들기' 화면이 나옵니다. **설정 코드**(6자리)는 컨테이너 로그에 있습니다:
```bash
docker compose logs wing | grep "설정 코드"      # 또는: docker logs wing-manager | grep "설정 코드"
```
그 다음은 설정 화면에서 쿠팡 API 키 · 카테고리 불러오기 · 텔레그램을 정합니다 (README '설정 한눈에 보기').

## 4. 데이터
- 설정(`config.json`), 로그인 정보(`.env`), DB(`wing.db`), 카테고리, 올린 이미지는 모두 **`wing-data` 볼륨(/data)** 에 저장됩니다.
  컨테이너를 지우거나 새 버전으로 바꿔도 남습니다.
- 백업: `docker run --rm -v wing-data:/data -v "$PWD":/backup alpine tar czf /backup/wing-backup.tgz -C /data .`
- 볼륨 대신 폴더를 쓰려면 `- ./wing-data:/data` 로 바꾸고, Linux에서는 `sudo chown -R 1000:1000 wing-data`
  (컨테이너는 보안을 위해 일반 사용자 uid 1000 으로 실행됩니다).

## 5. 업데이트 · 끄기
```bash
docker compose pull && docker compose up -d     # 새 버전으로
docker compose down                             # 끄기 (데이터는 남음)
```
특정 버전: `image: ghcr.io/angelcom11/cupang-agent:0.7.0`

## 참고
- 포트를 바꾸려면 compose 의 `"26118:26118"` 에서 **왼쪽** 숫자만 바꿉니다.
- 시간대는 `TZ` (기본 `Asia/Seoul`).
- 메뉴바 '서버 접속 주소'는 컨테이너 안 IP 대신 지금 접속한 주소를 보여 줍니다.
- 상품 이미지를 쿠팡이 가져가려면 인터넷에서 열리는 주소가 필요합니다 (설정 > 이미지 공개 주소).
- 직접 빌드: `docker build -t wing-manager .` / 여러 플랫폼: `docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 .`
