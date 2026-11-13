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

/** 경쟁 판매자 한 곳의 호가. */
export interface Competitor {
  seller: string;
  price: number;
  url: string;
  shop: string | null;
  checked_at: string;
}

export interface HistoryPoint {
  at: string;
  low: number;
  mine: number;
}

/** 경쟁가 비교의 한 줄. */
export interface PriceDetailRow {
  vendor_item_id: string;
  name: string;
  featured: boolean;
  sale_price: number;
  lowest: number | null;
  diff: number | null;
  rank: number;
  total: number;
  competitors: Competitor[];
  history: HistoryPoint[];
  auto_reprice: boolean;
  undercut: number;
  min_price: number;
}

export interface PricesData {
  last_sync: string | null;
  error: string | null;
  rows: PriceDetailRow[];
}

export const fetchPrices = () => get<PricesData>("/api/prices");

export const savePriceRule = (
  vid: string,
  autoReprice: boolean,
  undercut: number,
  minPrice: number,
) =>
  post<{message: string; item: PriceDetailRow}>("/api/prices/rule", {
    vendor_item_id: vid,
    auto_reprice: autoReprice,
    undercut,
    min_price: minPrice,
  });

export const saveCompetitorShop = (seller: string, url: string) =>
  post<{seller: string; shop: string | null}>("/api/competitor-shop", {seller, url});

/** 실시간 검색어: 내 상품별 연관검색어. 출처 하나가 실패해도 화면은 뜬다. */
export interface KeywordHit {
  keyword: string;
  url: string;
}

export interface KeywordProduct {
  name: string;
  /** 상품 이름에서 뽑아낸 검색의 바탕말. */
  query: string;
  featured: boolean;
  on_sale: boolean;
  keywords: KeywordHit[];
  error: string | null;
}

export interface KeywordSource {
  id: string;
  label: string;
}

export interface KeywordData {
  source: string;
  label: string;
  /** 모의 검색어 제공자로 돌고 있다 (인터넷에 묻지 않는다). */
  mock: boolean;
  /** 실거래 모드인데 검색어만 모의 — 사용자에게 알려야 한다. */
  mock_on_live: boolean;
  checked: string;
  sources: KeywordSource[];
  products: KeywordProduct[];
  related_error: string | null;
}

export const fetchKeywords = (source?: string) =>
  get<KeywordData>(`/api/keywords${source === undefined ? "" : `?source=${encodeURIComponent(source)}`}`);

/** 삭제는 되돌릴 수 없다. confirm 에 '삭제' 를 정확히 보내야 서버가 지운다. */
export const deleteItems = (sellerProductIds: string[], confirm: string, stopFirst: boolean) =>
  post<{results: DeleteResult[]}>("/api/items/delete", {
    seller_product_id: sellerProductIds,
    confirm,
    stop_first: stopFirst,
  });

/** 1,234 처럼 세 자리마다 쉼표. 기존 화면의 '{:,}' 포맷과 같게 보이도록. */
export const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;
