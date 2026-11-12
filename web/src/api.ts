/**
 * Flask API 클라이언트.
 * 로그인이 끊기면 서버가 /api/* 에 401 + {login:true} 를 주므로 로그인 화면으로 보낸다.
 */

export class AuthError extends Error {}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, {headers: {Accept: "application/json"}});
  if (res.status === 401) throw new AuthError("로그인이 필요합니다");
  if (!res.ok) throw new Error(`${path} 요청 실패 (HTTP ${res.status})`);
  return res.json() as Promise<T>;
}

export interface Kpi {
  total: number;
  stock_value: number;
  low: number;
  soldout: number;
  undercut: number;
  auto: number;
}

export interface FeaturedItem {
  vendor_item_id: string;
  name: string;
  on_sale: boolean;
  auto_stopped: boolean;
  sale_price: number;
  stock: number;
  lowest: number | null;
  rank: number;
  total: number;
}

export interface Alert {
  level: "danger" | "warn" | "info";
  kind: string;
  message: string;
  at: string;
}

export interface PriceRow {
  vendor_item_id: string;
  name: string;
  featured: boolean;
  sale_price: number;
  lowest: number | null;
  diff: number | null;
  rank: number;
  total: number;
}

export interface DashboardData {
  kpi: Kpi;
  featured: FeaturedItem[];
  alerts: Alert[];
  prices: PriceRow[];
  soldout_threshold: number;
  last_sync: string | null;
  sync_error: string | null;
}

export const fetchDashboard = () => get<DashboardData>("/api/dashboard");

/** 1,234 처럼 세 자리마다 쉼표. 기존 화면의 '{:,}' 포맷과 같게 보이도록. */
export const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;
