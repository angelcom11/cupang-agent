/**
 * 앱 골격 — AppShell + SideNav + 라우팅.
 * 기존 Flask 화면(base.html)의 메뉴 6개를 그대로 옮겼다.
 * 규칙: div/span 금지, 색·간격은 토큰 또는 컴포넌트 props 로만.
 */
import {Suspense, lazy} from "react";
import {BrowserRouter, Navigate, Route, Routes, useLocation} from "react-router-dom";
import {AppShell} from "@astryxdesign/core/AppShell";
import {SideNav, SideNavHeading, SideNavItem} from "@astryxdesign/core/SideNav";
import {VStack} from "@astryxdesign/core/Stack";
import {Spinner} from "@astryxdesign/core/Spinner";
import {
  Squares2X2Icon,
  ArchiveBoxIcon,
  ArrowTrendingUpIcon,
  MagnifyingGlassIcon,
  PlusCircleIcon,
  Cog6ToothIcon,
} from "@heroicons/react/24/outline";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Inventory = lazy(() => import("./pages/Inventory"));
const Prices = lazy(() => import("./pages/Prices"));
const Keywords = lazy(() => import("./pages/Keywords"));
const Settings = lazy(() => import("./pages/Settings"));

/**
 * 메뉴 — 기존 화면과 경로·순서·이름을 맞춘다.
 * 아이콘은 heroicons 컴포넌트를 직접 넘긴다. Astryx 의미 이름(`package`, `new`, `settings` 등)은
 * neutral 테마의 레지스트리에 없어 빈 자리로 렌더됐다 — `search` 만 해석됐다.
 */
const NAV = [
  {href: "/", label: "대시보드", icon: Squares2X2Icon},
  {href: "/inventory", label: "재고 관리", icon: ArchiveBoxIcon},
  {href: "/prices", label: "경쟁가 비교", icon: ArrowTrendingUpIcon},
  {href: "/keywords", label: "실시간 검색어", icon: MagnifyingGlassIcon},
  {href: "/register", label: "상품 등록", icon: PlusCircleIcon},
  {href: "/settings", label: "설정", icon: Cog6ToothIcon},
];

function Nav() {
  const {pathname} = useLocation();
  return (
    <SideNav
      aria-label="주 메뉴"
      header={<SideNavHeading heading="WING 매니저" subheading="쿠팡 상점 관리" />}
      collapsible
    >
      {NAV.map((item) => (
        <SideNavItem
          key={item.href}
          label={item.label}
          icon={item.icon}
          href={item.href}
          isSelected={pathname === item.href}
        />
      ))}
    </SideNav>
  );
}

function Shell() {
  return (
    <AppShell sideNav={<Nav />} contentPadding={0} height="fill">
      <Suspense
        fallback={
          <VStack padding={6} align="center">
            <Spinner label="불러오는 중" />
          </VStack>
        }
      >
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/prices" element={<Prices />} />
          <Route path="/keywords" element={<Keywords />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}

export default function App() {
  return (
    // Flask 가 /ui 에서 이 SPA 를 띄운다 (자산은 /static/dist/ 에서 받는다).
    // 7개 화면을 다 옮기면 루트로 옮긴다.
    <BrowserRouter basename="/ui">
      <Shell />
    </BrowserRouter>
  );
}
