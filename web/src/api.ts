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

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: {Accept: "application/json", "Content-Type": "application/json"},
    body: JSON.stringify(body ?? {}),
  });
  if (res.status === 401) throw new AuthError("로그인이 필요합니다");
  // 서버가 실패 이유를 한국어로 준다. HTTP 숫자보다 그 문구가 쓸모 있다.
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const reason =
      data !== null && typeof data === "object" && "error" in data
        ? String((data as {error: unknown}).error)
        : `요청 실패 (HTTP ${res.status})`;
    throw new Error(reason);
  }
  return data as T;
}

/** 재고 화면의 한 줄. /api/inventory 의 items 그대로. */
export interface InventoryItem {
  vendor_item_id: string;
  seller_product_id: string;
  name: string;
  status: string;
  on_sale: boolean;
  auto_stopped: boolean;
  featured: boolean;
  sale_price: number;
  stock: number;
  low_stock: number;
}

export interface InventoryData {
  last_sync: string | null;
  error: string | null;
  items: InventoryItem[];
}

export interface DeleteResult {
  name: string;
  ok: boolean;
  message: string;
}

export const fetchInventory = () => get<InventoryData>("/api/inventory");

export const toggleFeatured = (vid: string) => post<{item: InventoryItem}>(`/api/items/${vid}/featured`);

export const toggleSale = (vid: string) =>
  post<{message: string; item: InventoryItem}>(`/api/items/${vid}/sale`);

export const saveStock = (vid: string, stock: string, lowStock: string) =>
  post<{message: string; item: InventoryItem}>(`/api/items/${vid}/stock`, {
    stock,
    low_stock: lowStock,
  });

/** 삭제는 되돌릴 수 없다. confirm 에 '삭제' 를 정확히 보내야 서버가 지운다. */
export const deleteItems = (sellerProductIds: string[], confirm: string, stopFirst: boolean) =>
  post<{results: DeleteResult[]}>("/api/items/delete", {
    seller_product_id: sellerProductIds,
    confirm,
    stop_first: stopFirst,
  });

/** 1,234 처럼 세 자리마다 쉼표. 기존 화면의 '{:,}' 포맷과 같게 보이도록. */
export const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;
