/**
 * 화면 폭이 좁은지 알려준다.
 *
 * 왜 필요한가: 대시보드는 본문 + 오른쪽 알림 레일(340px) 두 칸이다. 폭이 좁아지면
 * 본문이 짜부라져 "대시보드" 제목이 한 글자씩 네 줄로 쪼개졌다(390px 에서 실측 128px).
 * Astryx 의 Stack 에는 minWidth 가 없고 Grid 의 auto-fit 은 칸을 균등하게 나눠
 * 2:1 비율을 지킬 수 없어서, 좁을 때만 위아래로 쌓는다.
 */
import {useEffect, useState} from "react";

/** 레일을 접는 기준. 본문 약 600 + 레일 340 + 사이드바 260 이 들어가는 폭. */
export const NARROW = 1100;

export function useIsNarrow(maxWidth: number = NARROW): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.innerWidth < maxWidth,
  );
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${maxWidth - 1}px)`);
    const onChange = () => setNarrow(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => {
      mq.removeEventListener("change", onChange);
    };
  }, [maxWidth]);
  return narrow;
}
