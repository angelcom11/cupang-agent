import {StrictMode} from "react";
import {createRoot} from "react-dom/client";
import {Theme} from "@astryxdesign/core/theme";
import {themes, defaultThemeSlug} from "./astryx-themes";
import {useThemeMode} from "./theme-mode";
import App from "./App";
import "./globals.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root 가 없습니다 — index.html 을 확인하세요");

/** 저장된 화면 모드를 Theme 에 넘긴다. 설정에서 바꾸면 바로 다시 그려진다. */
function Themed() {
  return (
    <Theme theme={themes[defaultThemeSlug]} mode={useThemeMode()}>
      <App />
    </Theme>
  );
}

createRoot(root).render(
  <StrictMode>
    <Themed />
  </StrictMode>,
);
