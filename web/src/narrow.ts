/**
 * 좁은 화면 기준. 두 칸 짜리 화면(본문 + 레일)을 세로로 쌓는 폭이다.
 *
 * 본문 약 600 + 레일 340 + 사이드바 260 이 들어가려면 1100 은 있어야 한다. 그보다
 * 좁으면 본문이 짜부라져 "대시보드" 제목이 한 글자씩 네 줄로 쪼개졌다(390px 실측 128px).
 *
 * 훅은 직접 만들지 않는다 — Astryx 의 useMediaQuery 가 같은 일을 한다.
 * (@astryxdesign/core/hooks). 처음엔 모르고 use-narrow.ts 를 따로 만들었다.
 */
export const NARROW_QUERY = "(max-width: 1099px)";
