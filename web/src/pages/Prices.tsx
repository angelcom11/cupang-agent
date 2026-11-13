/**
 * 경쟁가 비교 — 기존 Jinja 화면(templates/prices.html)과 같은 일을 한다.
 *
 * 열이 8개(상품·내 가격·경쟁 최저·차이·순위·경쟁 판매자·추이·규칙)여서 한 줄에 다 넣으면
 * 읽을 수 없다. 그래서 줄을 펼치면 경쟁 판매자 목록과 최저가 추이, 자동조정 규칙이 나온다.
 * 표에는 판단에 필요한 숫자만 둔다.
 *
 * 규칙 저장은 /api/prices/rule 로 가고, 그 몸통은 Jinja 화면과 같은 함수를 쓴다
 * (app.py 의 _save_price_rule).
 */
import {useEffect, useMemo, useState} from "react";
import {VStack, HStack, StackItem} from "@astryxdesign/core/Stack";
import {Section} from "@astryxdesign/core/Section";
import {Grid} from "@astryxdesign/core/Grid";
import {Text, Heading} from "@astryxdesign/core/Text";
import {Badge} from "@astryxdesign/core/Badge";
import {StatusDot} from "@astryxdesign/core/StatusDot";
import {Switch} from "@astryxdesign/core/Switch";
import {NumberInput} from "@astryxdesign/core/NumberInput";
import {TextInput} from "@astryxdesign/core/TextInput";
import {Button} from "@astryxdesign/core/Button";
import {Banner} from "@astryxdesign/core/Banner";
import {Divider} from "@astryxdesign/core/Divider";
import {EmptyState} from "@astryxdesign/core/EmptyState";
import {Spinner} from "@astryxdesign/core/Spinner";
import {Icon} from "@astryxdesign/core/Icon";
import {Link} from "@astryxdesign/core/Link";
import {MetadataList, MetadataListItem} from "@astryxdesign/core/MetadataList";
import {Table, proportional, pixel, useTableRowExpansion} from "@astryxdesign/core/Table";
import {MagnifyingGlassIcon} from "@heroicons/react/24/outline";
import {AuthError, fetchPrices, savePriceRule, saveCompetitorShop, won} from "../api";
import type {Competitor, HistoryPoint, PriceDetailRow} from "../api";

type Row = PriceDetailRow & Record<string, unknown>;

/**
 * 자동조정이 다음 확인 때 실제로 할 일.
 *
 * services.py 의 _check_price 는 `lowest >= sale_price` 면 그냥 반환한다 —
 * 즉 가격을 내릴 뿐 올리지 않는다. 화면이 이걸 말해주지 않으면, 내 가격이
 * 경쟁 최저보다 싼데 자동조정이 ON 인 상태가 "곧 올리려나?" 처럼 보인다.
 */
function rulePreview(r: PriceDetailRow): {status: "success" | "warning" | "info"; text: string} {
  if (!r.auto_reprice) {
    return {status: "info", text: "자동조정이 꺼져 있어 가격을 건드리지 않습니다."};
  }
  if (r.lowest === null) {
    return {status: "info", text: "경쟁 호가가 아직 없어 조정할 기준이 없습니다."};
  }
  if (r.lowest >= r.sale_price) {
    return {
      status: "success",
      text: "지금은 내 가격이 경쟁 최저 이하입니다. 자동조정은 가격을 내릴 뿐 올리지 않으므로 아무 일도 하지 않습니다.",
    };
  }
  const target = r.lowest - r.undercut;
  if (target < r.min_price) {
    return {
      status: "warning",
      text: `맞추려면 ${won(target)} 가 되는데 하한가 ${won(r.min_price)} 아래입니다. 조정하지 않고 알림만 남깁니다.`,
    };
  }
  return {
    status: "warning",
    text: `다음 확인 때 ${won(r.sale_price)} → ${won(target)} 로 내립니다 (경쟁 최저 ${won(r.lowest)} 보다 ${won(r.undercut)} 싸게).`,
  };
}

/** 밀린 금액을 심각도로 나눈다. 전부 빨강이면 무엇이 급한지 안 보인다. */
function diffVariant(diff: number, myPrice: number): "success" | "warning" | "error" {
  if (diff <= 0) return "success";
  return diff >= myPrice * 0.1 ? "error" : "warning";
}

/**
 * 최저가 추이 — 점 몇 개를 글자로 보여준다.
 *
 * 차트 라이브러리를 쓰지 않는 이유: 이 자리에 필요한 것은 "오르고 있나 내리고 있나"
 * 한 가지다. 모의 모드에서는 점이 한 개뿐이라 선을 그려도 보이지 않는다.
 */
function Trend({history}: {history: HistoryPoint[]}) {
  if (history.length === 0) {
    return (
      <Text size="sm" color="secondary">
        아직 쌓인 기록이 없습니다
      </Text>
    );
  }
  const lows = history.map((h) => h.low);
  const first = lows[0];
  const last = lows[lows.length - 1];
  const change = last - first;
  return (
    <VStack gap={2} hAlign="start">
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Text size="sm" color="secondary">
          최저 {won(Math.min(...lows))} · 최고 {won(Math.max(...lows))} · 기록 {history.length}회
        </Text>
        {history.length > 1 ? (
          <Badge
            variant={change > 0 ? "warning" : change < 0 ? "error" : "neutral"}
            label={change === 0 ? "변동 없음" : `${change > 0 ? "+" : ""}${won(change)}`}
          />
        ) : null}
      </HStack>
      <MetadataList columns="multi" orientation="vertical" label={{position: "top"}}>
        {history.slice(-6).map((h) => (
          <MetadataListItem key={h.at} label={h.at.slice(5, 16)}>
            {won(h.low)}
          </MetadataListItem>
        ))}
      </MetadataList>
    </VStack>
  );
}

/** 경쟁 판매자 한 줄. 샵 주소를 등록해두면 다음부터 바로 열어볼 수 있다. */
function CompetitorRow({
  c,
  myPrice,
  isLowest,
  onSaveShop,
}: {
  c: Competitor;
  myPrice: number;
  isLowest: boolean;
  onSaveShop: (seller: string, url: string) => Promise<void>;
}) {
  const [url, setUrl] = useState(c.shop ?? "");
  return (
    <HStack gap={3} vAlign="center" wrap="wrap">
      <StackItem size="fill">
        <HStack gap={2} vAlign="center">
          <Text weight="semibold">{c.seller}</Text>
          <Text textWrap="nowrap">{won(c.price)}</Text>
          {isLowest ? <Badge variant="warning" label="최저" /> : null}
          {/* 내 가격보다 싼 곳만 표시한다. 그게 대응이 필요한 쪽이다. */}
          {c.price < myPrice ? <Badge variant="error" label={`나보다 ${won(myPrice - c.price)} 싸다`} /> : null}
          {c.shop !== null && c.shop !== "" ? (
            <Link href={c.shop} target="_blank" label="샵 열기">
              샵 열기
            </Link>
          ) : null}
        </HStack>
      </StackItem>
      <VStack width={280}>
        <TextInput
          // 라벨을 보이게 두면 입력칸 위에 떠서 윗줄에 붙은 것처럼 읽힌다.
          // 머리글은 목록 위에 한 번만 둔다.
          label={`${c.seller} 샵 주소 또는 업체코드`}
          isLabelHidden
          value={url}
          onChange={setUrl}
          placeholder="A00012345 또는 shop.coupang.com/…"
        />
      </VStack>
      <Button
        label="저장"
        variant="secondary"
        clickAction={async () => {
          await onSaveShop(c.seller, url);
        }}
      />
    </HStack>
  );
}

export default function Prices() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{status: "success" | "error"; title: string; description?: string} | null>(null);
  const [query, setQuery] = useState("");
  const [onlyUndercut, setOnlyUndercut] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, {undercut?: number | null; min?: number | null}>>({});

  const onFail = (e: unknown) => {
    if (e instanceof AuthError) {
      location.href = "/login";
      return;
    }
    setNotice({status: "error", title: "실패했습니다", description: e instanceof Error ? e.message : String(e)});
  };

  const reload = async () => {
    const d = await fetchPrices();
    setRows(d.rows as Row[]);
  };

  useEffect(() => {
    let alive = true;
    fetchPrices()
      .then((d) => {
        if (alive) setRows(d.rows as Row[]);
      })
      .catch((e: unknown) => {
        if (e instanceof AuthError) {
          location.href = "/login";
          return;
        }
        if (alive) setLoadError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  const visible = useMemo(() => {
    if (rows === null) return [];
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (onlyUndercut && !(r.diff !== null && r.diff > 0)) return false;
      if (q === "") return true;
      return r.name.toLowerCase().includes(q) || r.vendor_item_id.toLowerCase().includes(q);
    });
  }, [rows, query, onlyUndercut]);

  const expansionPlugin = useTableRowExpansion<Row>({
    expandedKeys,
    onToggle: (key) =>
      setExpandedKeys((prev) => {
        const next = new Set(prev);
        if (next.has(key)) {
          next.delete(key);
        } else {
          next.add(key);
        }
        return next;
      }),
    getRowKey: (r) => r.vendor_item_id,
    getRowLabel: (r) => `${r.name} 자세히`,
    hasRowClickExpansion: true,
    renderExpanded: (r) => (
      <VStack gap={5} padding={4}>
        <Grid columns={2} gap={5}>
          <VStack gap={3} hAlign="start">
            <Heading level={3}>경쟁 판매자 {r.competitors.length}곳</Heading>
            {r.competitors.length === 0 ? (
              <Text size="sm" color="secondary">
                아직 수집된 경쟁 호가가 없습니다.
              </Text>
            ) : (
              <VStack gap={3}>
                <HStack gap={3} vAlign="center">
                  <StackItem size="fill">
                    <Text size="sm" color="secondary">
                      판매자 / 호가
                    </Text>
                  </StackItem>
                  <VStack width={280} hAlign="start">
                    <Text size="sm" color="secondary">
                      샵 주소 또는 업체코드
                    </Text>
                  </VStack>
                </HStack>
                {r.competitors.map((c) => (
                  <CompetitorRow
                    key={c.seller}
                    c={c}
                    myPrice={r.sale_price}
                    isLowest={c.price === r.lowest}
                    onSaveShop={async (seller, url) => {
                      try {
                        await saveCompetitorShop(seller, url);
                        setNotice({status: "success", title: `${seller} 샵 주소를 저장했습니다`});
                        await reload();
                      } catch (e) {
                        onFail(e);
                      }
                    }}
                  />
                ))}
              </VStack>
            )}
          </VStack>

          <VStack gap={3} hAlign="start">
            <Heading level={3}>최저가 추이</Heading>
            <Trend history={r.history} />
          </VStack>
        </Grid>

        <Divider />

        <VStack gap={3} hAlign="start">
          <Heading level={3}>자동 가격조정</Heading>
          <Text size="sm" color="secondary">
            경쟁 최저가보다 인하폭만큼 싸게 맞춥니다. 하한가 아래로는 내려가지 않고, 가격을 올리지도 않습니다.
          </Text>
          <Banner status={rulePreview(r).status} title="지금 규칙대로라면" description={rulePreview(r).text} />
          <HStack gap={4} vAlign="end" wrap="wrap">
            <Switch
              label="자동조정 사용"
              value={r.auto_reprice}
              changeAction={async (checked) => {
                try {
                  const d = drafts[r.vendor_item_id] ?? {};
                  await savePriceRule(
                    r.vendor_item_id,
                    checked,
                    d.undercut ?? r.undercut,
                    d.min ?? r.min_price,
                  );
                  setNotice({status: "success", title: "가격 규칙을 저장했습니다"});
                  await reload();
                } catch (e) {
                  onFail(e);
                }
              }}
            />
            <NumberInput
              label="인하폭 (원)"
              min={0}
              width={130}
              value={drafts[r.vendor_item_id]?.undercut ?? r.undercut}
              onChange={(v) =>
                setDrafts((prev) => ({
                  ...prev,
                  [r.vendor_item_id]: {...prev[r.vendor_item_id], undercut: v},
                }))
              }
            />
            <NumberInput
              label="하한가 (원)"
              min={0}
              width={150}
              value={drafts[r.vendor_item_id]?.min ?? r.min_price}
              onChange={(v) =>
                setDrafts((prev) => ({
                  ...prev,
                  [r.vendor_item_id]: {...prev[r.vendor_item_id], min: v},
                }))
              }
            />
            <Button
              label="규칙 저장"
              clickAction={async () => {
                try {
                  const d = drafts[r.vendor_item_id] ?? {};
                  await savePriceRule(
                    r.vendor_item_id,
                    r.auto_reprice,
                    d.undercut ?? r.undercut,
                    d.min ?? r.min_price,
                  );
                  setNotice({status: "success", title: "가격 규칙을 저장했습니다"});
                  setDrafts((prev) => {
                    const next = {...prev};
                    delete next[r.vendor_item_id];
                    return next;
                  });
                  await reload();
                } catch (e) {
                  onFail(e);
                }
              }}
            />
          </HStack>
        </VStack>
      </VStack>
    ),
  });

  if (loadError !== null) {
    return (
      <Section padding={6}>
        <EmptyState title="경쟁가를 불러오지 못했습니다" description={loadError} />
      </Section>
    );
  }
  if (rows === null) {
    return (
      <Section padding={6}>
        <VStack vAlign="center" padding={6}>
          <Spinner label="불러오는 중" />
        </VStack>
      </Section>
    );
  }

  const undercutCount = rows.filter((r) => r.diff !== null && r.diff > 0).length;

  return (
    <Section padding={6}>
      <VStack gap={6}>
        <HStack gap={3} vAlign="center" wrap="wrap">
          <StackItem size="fill">
            <VStack gap={1} hAlign="start">
              <Heading level={1}>경쟁가 비교</Heading>
              <HStack gap={2} vAlign="center">
                <StatusDot variant={undercutCount === 0 ? "success" : "warning"} label="가격 상태" />
                <Text size="sm" color="secondary">
                  {undercutCount === 0
                    ? "최저가에 밀린 상품이 없습니다"
                    : `${undercutCount}개 상품이 경쟁 최저가보다 비쌉니다`}
                </Text>
              </HStack>
            </VStack>
          </StackItem>
          <VStack width={280}>
            <TextInput
              label="상품명 또는 옵션ID 로 찾기"
              isLabelHidden
              value={query}
              onChange={setQuery}
              placeholder="상품명 · 옵션ID"
              startIcon={<Icon icon={MagnifyingGlassIcon} size="sm" />}
              hasClear
            />
          </VStack>
        </HStack>

        {notice !== null ? (
          <Banner
            status={notice.status}
            title={notice.title}
            description={notice.description}
            isDismissable
            onDismiss={() => setNotice(null)}
          />
        ) : null}

        <HStack gap={3} vAlign="center" wrap="wrap">
          <Switch label="밀린 상품만 보기" value={onlyUndercut} onChange={setOnlyUndercut} />
          <Text size="sm" color="secondary">
            · 줄을 누르면 경쟁 판매자와 추이, 자동조정 규칙이 열립니다
          </Text>
        </HStack>

        <Divider />

        {visible.length === 0 ? (
          <EmptyState
            title={onlyUndercut ? "밀린 상품이 없습니다" : "상품이 없습니다"}
            description={onlyUndercut ? "모든 상품이 경쟁 최저가 이하입니다." : "쿠팡 동기화가 끝나면 여기에 나옵니다."}
            actions={
              onlyUndercut ? (
                <Button label="전체 보기" variant="secondary" onClick={() => setOnlyUndercut(false)} />
              ) : undefined
            }
          />
        ) : (
          <Table<Row>
            data={visible}
            idKey="vendor_item_id"
            density="balanced"
            hasHover
            plugins={{expansion: expansionPlugin}}
            columns={[
              {
                key: "name",
                header: "상품",
                width: proportional(1),
                renderCell: (r: Row) => (
                  <VStack gap={0.5} hAlign="start">
                    <HStack gap={1.5} vAlign="center">
                      {r.featured ? <Badge variant="info" label="주력" /> : null}
                      <Text maxLines={1}>{r.name}</Text>
                    </HStack>
                    <Text size="sm" color="secondary">
                      {r.vendor_item_id}
                    </Text>
                  </VStack>
                ),
              },
              {
                key: "sale_price",
                header: "내 가격",
                width: pixel(110),
                align: "end",
                renderCell: (r: Row) => <Text textWrap="nowrap">{won(r.sale_price)}</Text>,
              },
              {
                key: "lowest",
                header: "경쟁 최저",
                width: pixel(110),
                align: "end",
                renderCell: (r: Row) => (
                  <Text textWrap="nowrap">{r.lowest === null ? "-" : won(r.lowest)}</Text>
                ),
              },
              {
                key: "diff",
                header: "차이",
                width: pixel(120),
                align: "end",
                renderCell: (r: Row) =>
                  r.diff === null ? (
                    <Text color="secondary">-</Text>
                  ) : (
                    <Badge
                      variant={diffVariant(r.diff, r.sale_price)}
                      label={r.diff > 0 ? `+${won(r.diff)}` : won(r.diff)}
                    />
                  ),
              },
              {
                key: "rank",
                header: "순위",
                width: pixel(90),
                align: "center",
                renderCell: (r: Row) => (
                  <Badge
                    variant={r.rank === 1 ? "success" : r.rank === r.total ? "error" : "neutral"}
                    label={`${r.rank}/${r.total}`}
                  />
                ),
              },
              {
                key: "competitors",
                header: "경쟁 판매자",
                width: pixel(110),
                align: "center",
                renderCell: (r: Row) => (
                  <Text size="sm" color="secondary">
                    {r.competitors.length}곳
                  </Text>
                ),
              },
              {
                key: "auto_reprice",
                header: "자동조정",
                width: pixel(100),
                align: "center",
                // 표에서는 상태만 보인다. 켜고 끄는 건 줄을 펼쳐서 한다 —
                // 가격을 바꾸는 일이라 인하폭·하한가를 같이 보면서 결정해야 한다.
                renderCell: (r: Row) =>
                  r.auto_reprice ? <Badge variant="success" label="ON" /> : <Badge variant="neutral" label="OFF" />,
              },
            ]}
          />
        )}
      </VStack>
    </Section>
  );
}
