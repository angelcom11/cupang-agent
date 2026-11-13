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

/** 설정 화면. 비밀값은 서버가 내보내지 않는다 — 있는지 여부만 온다. */
export interface SettingsKeys {
  access_key: string;
  has_secret_key: boolean;
  vendor_id: string;
  mode: "mock" | "live";
}

export interface SettingsRules {
  sync_interval_sec: number;
  soldout_threshold: number;
  auto_soldout: boolean;
  public_base_url: string;
}

export interface TelegramSettings {
  has_token: boolean;
  chat_id: string;
  enabled: boolean;
  topics: string[];
  frequency: string;
  send_from: string;
  send_to: string;
  outside: "hold" | "drop";
  pending: number;
  window_open: boolean;
  last_result: string | null;
}

export interface IdLabel {
  id: string;
  label: string;
}

export interface TelegramChat {
  id: string;
  title: string;
}

export interface SettingsData {
  keys: SettingsKeys;
  rules: SettingsRules;
  theme: string;
  themes: IdLabel[];
  telegram: TelegramSettings;
  topics: IdLabel[];
  frequencies: IdLabel[];
  categories: {count: number; leaves: number; source: string; updated_at: string; full: boolean};
  mock_competitor_live: boolean;
}

export const fetchSettings = () => get<SettingsData>("/api/settings");

/** action: test(연결 확인) · save · clear. 빈 칸은 서버가 기존 값으로 채운다. */
export const settingsKeys = (
  action: "test" | "save" | "clear",
  keys: {access_key?: string; secret_key?: string; vendor_id?: string},
) => post<{message: string; mode?: string}>("/api/settings/keys", {action, ...keys});

export const settingsRules = (rules: SettingsRules) =>
  post<{message: string}>("/api/settings/rules", rules);

export const settingsTheme = (theme: string) =>
  post<{message: string}>("/api/settings/theme", {theme});

export const settingsTelegram = (
  action: "save" | "test" | "find_chat" | "clear",
  tg: Partial<TelegramSettings> & {token?: string},
) => post<{message: string; chats: TelegramChat[] | null}>("/api/settings/telegram", {action, ...tg});

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

// ---------------- 상품 등록 마법사 ----------------
// 단계·기본값·검증은 서버(product_form.py)가 갖고 있다. 여기서 다시 정의하지 않는다.

/** 검증 오류 하나. step/sub 는 '어디서 고치는지' 다 — 마법사가 그 단계로 데려간다. */
export interface RegisterError {
  message: string;
  step: string;
  sub: number;
}

/**
 * 검증 실패는 보통의 요청 실패가 아니다. 서버가 400 과 함께 고칠 목록을 주는데,
 * post() 는 error 필드만 보고 그 목록을 버린다 — 마법사에는 그게 본문이다.
 */
export class RegisterInvalid extends Error {
  readonly errors: RegisterError[];
  constructor(errors: RegisterError[]) {
    super("고칠 곳이 있습니다");
    this.name = "RegisterInvalid";
    this.errors = errors;
  }
}

export interface ShippingPlace {
  code: string;
  name: string;
  address: string;
  usable: boolean;
}

export interface RegisterDraft {
  id: number;
  name: string;
  note: string | null;
  updated_at: string;
}

export type RegisterForm = Record<string, unknown>;

export interface RegisterMeta {
  steps: {id: string; label: string}[];
  main_subs: string[];
  form: RegisterForm;
  drafts: RegisterDraft[];
  /** 키는 outbound 와 returns 다 (return 이 아니다). errors 는 목록을 못 불러온 이유. */
  places: {outbound: ShippingPlace[]; returns: ShippingPlace[]; errors: string[]};
  has_saved_defaults: boolean;
  max_detail_images: number;
  mode: "mock" | "live";
}

/** 등록 API 전용 POST. 400 + {errors:[…]} 를 RegisterInvalid 로 바꿔 목록을 살려 보낸다. */
async function postRegister<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: {Accept: "application/json", "Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  if (res.status === 401) throw new AuthError("로그인이 필요합니다");
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    if (data !== null && typeof data === "object" && "errors" in data) {
      const list = (data as {errors: unknown}).errors;
      if (Array.isArray(list) && list.length > 0) throw new RegisterInvalid(list as RegisterError[]);
    }
    const reason =
      data !== null && typeof data === "object" && "error" in data
        ? String((data as {error: unknown}).error)
        : `요청 실패 (HTTP ${res.status})`;
    throw new Error(reason);
  }
  return data as T;
}

export const fetchRegisterMeta = () => get<RegisterMeta>("/api/register/meta");

/** 검증만. 200 으로 오고 errors 가 빈 배열이면 통과다. */
export const registerValidate = (form: RegisterForm) =>
  postRegister<{errors: RegisterError[]; form: RegisterForm}>("/api/register/validate", form);

/** 쿠팡에 보낼 본문을 그대로 돌려준다. 보내기 전에 눈으로 확인하는 자리다. */
export const registerPreview = (form: RegisterForm) =>
  postRegister<{errors: RegisterError[]; payload: unknown}>("/api/register/preview", form);

/** save=쿠팡에 임시저장 · request=바로 판매요청. WING 의 두 버튼과 같다. */
export const registerSubmit = (
  form: RegisterForm,
  action: "save" | "request",
  draftId: number | null,
  rememberDefaults: boolean,
) =>
  postRegister<{message: string; draft_id: number}>("/api/register/submit", {
    ...form,
    action,
    draft_id: draftId,
    remember_defaults: rememberDefaults,
  });

/** 내 서버에만 저장. 필수값이 없어도 언제든 된다 (기존 화면과 같다). */
export const saveRegisterDraft = (
  form: RegisterForm,
  draftId: number | null,
  rememberDefaults: boolean,
) =>
  postRegister<{message: string; draft_id: number; drafts: RegisterDraft[]}>(
    "/api/register/draft",
    {...form, draft_id: draftId, remember_defaults: rememberDefaults},
  );

export const loadRegisterDraft = (draftId: number) =>
  get<{draft_id: number; form: RegisterForm}>(`/api/register/draft/${draftId}`);
