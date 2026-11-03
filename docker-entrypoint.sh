#!/bin/sh
# 데이터 폴더(/data) 권한을 맞춘 뒤 일반 사용자로 프로그램을 실행한다.
# - 호스트 폴더를 /data 에 연결하면(예: ./wing-data:/data, NAS 공유 폴더) 폴더 주인이 root 등이라
#   일반 사용자로는 DB를 만들 수 없다 → 여기서 주인을 바꿔 준다.
# - PUID / PGID 로 실행 사용자 번호를 정할 수 있다 (기본 1000, NAS 사용자에 맞출 때).
set -e
DATA=/data
PUID=${PUID:-1000}
PGID=${PGID:-1000}

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA"
  # 주인이 다르면 바꾼다 (이미 맞으면 건너뜀 → 큰 uploads 폴더도 매번 다시 바꾸지 않음)
  if [ "$(stat -c %u "$DATA")" != "$PUID" ] || [ "$(stat -c %g "$DATA")" != "$PGID" ]; then
    chown -R "$PUID:$PGID" "$DATA" 2>/dev/null || echo "[경고] $DATA 의 주인을 바꾸지 못했습니다 (네트워크 드라이브 등)."
  fi
  if setpriv --reuid="$PUID" --regid="$PGID" --clear-groups test -w "$DATA"; then
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
  fi
  echo "[경고] uid $PUID 로 $DATA 에 쓸 수 없어 root 로 실행합니다. PUID/PGID 를 폴더 주인에 맞추면 일반 사용자로 실행됩니다."
  exec "$@"
fi

# docker run --user 처럼 처음부터 일반 사용자로 시작한 경우: 바꿀 권한이 없으니 확인만 한다
if [ ! -w "$DATA" ]; then
  echo "[오류] 데이터 폴더 $DATA 에 쓸 수 없습니다 (실행 사용자 uid $(id -u))."
  echo "       호스트 폴더 주인을 바꾸거나 (sudo chown -R $(id -u):$(id -g) <폴더>), --user 옵션을 빼고 실행하세요."
  exit 1
fi
exec "$@"
