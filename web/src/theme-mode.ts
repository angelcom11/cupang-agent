/**
 * 화면 모드(시스템·라이트·다크).
 *
 * 첫 값은 Flask 가 /ui HTML 에 심어 보낸 <meta name="wing-theme"> 에서 읽는다.
 * API 로 받아서 고치면 밝게 떴다가 어두워지는 번쩍임이 생긴다.
 *
 * 설정 화면에서 바꾸면 바로 반영되어야 하므로, 모듈에 값을 두고 구독자에게 알린다
 * (상태를 App 까지 끌어올리면 설정 화면이 App 을 거쳐 올라가야 한다).
 */
import {useEffect, useState} from "react";

export type ThemeMode = "system" | "light" | "dark";

const MODES: ThemeMode[] = ["system", "light", "dark"];

function fromMeta(): ThemeMode {
  const found = document.querySelector('meta[name="wing-theme"]')?.getAttribute("content");
  return MODES.includes(found as ThemeMode) ? (found as ThemeMode) : "system";
}

let current: ThemeMode = fromMeta();
const listeners = new Set<(m: ThemeMode) => void>();

export function setThemeMode(mode: ThemeMode) {
  if (mode === current) return;
  current = mode;
  for (const fn of listeners) fn(mode);
}

/** 지금 모드를 돌려주고, 바뀌면 다시 그린다. */
export function useThemeMode(): ThemeMode {
  const [mode, setMode] = useState(current);
  useEffect(() => {
    listeners.add(setMode);
    return () => {
      listeners.delete(setMode);
    };
  }, []);
  return mode;
}
