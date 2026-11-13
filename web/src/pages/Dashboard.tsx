/**
 * 대시보드 — 기존 Jinja 화면(templates/dashboard.html)과 같은 내용을 Astryx 로.
 *
 * 뼈대는 astryx 의 dashboard-alert-rail 템플릿을 따른다: 왼쪽에 KPI 와 본문,
 * 오른쪽에 알림 레일. 숫자는 /api/dashboard 가 주며 기존 화면과 같은 계산
 * (app.py 의 _dashboard_data)을 쓰므로 두 화면이 어긋나지 않는다.
 *
 * 규칙: div/span 금지 — 레이아웃은 전부 컴포넌트가 맡는다. 색·간격은 props 와 토큰만.
 */
import {useEffect, useState} from "react";
import {Grid} from "@astryxdesign/core/Grid";
import {VStack, HStack, StackItem} from "@astryxdesign/core/Stack";
import {Section} from "@astryxdesign/core/Section";
import {Card} from "@astryxdesign/core/Card";
import {Text, Heading} from "@astryxdesign/core/Text";
import {Badge} from "@astryxdesign/core/Badge";
import {StatusDot} from "@astryxdesign/core/StatusDot";
import {List, ListItem} from "@astryxdesign/core/List";
import {Table, proportional, pixel} from "@astryxdesign/core/Table";
import type {TableColumn} from "@astryxdesign/core/Table";
import {EmptyState} from "@astryxdesign/core/EmptyState";
import {Spinner} from "@astryxdesign/core/Spinner";
import {Divider} from "@astryxdesign/core/Divider";
import {fetchDashboard, won, AuthError} from "../api";
import {useIsNarrow} from "../use-narrow";
import type {Alert, DashboardData, FeaturedItem, PriceRow} from "../api";

/**
 * KPI 한 칸. 기존 화면은 나쁜 수치를 빨간 글자로 보였는데, Astryx 의 Text 색에는
 * error 가 없다 (primary·secondary·disabled·placeholder·accent·inherit 뿐).
 * 그래서 나쁜 수치는 Badge 로 보인다 — 개수를 나타내는 자리라 Badge 의 용도에 맞다.
 */
function Kpi({label, value, isBad}: {label: string; value: string; isBad?: boolean}) {
  return (
    <Card padding={4}>
      {/* align="start" 가 없으면 자식이 칸 폭 전체로 늘어난다 */}
      <VStack gap={1} align="start">
        <HStack gap={1.5} align="center">
          {isBad === true ? <StatusDot variant="error" label="주의" /> : null}
          <Text size="sm" color="secondary" textWrap="nowrap">
            {label}
          </Text>
        </HStack>
        {/* 나쁜 값도 같은 크기로 보인다. 숫자를 배지로 바꾸면 칸마다 글자 크기가 달라 보인다. */}
        <Text size="xl" weight="bold" textWrap="nowrap">
          {value}
        </Text>
      </VStack>
    </Card>
  );
}

function FeaturedCard({item, threshold}: {item: FeaturedItem; threshold: number}) {
  const lowStock = item.stock < threshold;
  return (
    <Card padding={4}>
      <VStack gap={3}>
        <HStack gap={2} justify="between" align="start">
          <Text weight="semibold" maxLines={2}>
            {item.name}
          </Text>
          {/* HStack 자식은 기본으로 줄어든다. static 으로 묶지 않으면 "판매..." 로 잘린다. */}
          <StackItem size="static">
            {item.on_sale ? (
              <Badge variant="success" label="판매중" />
            ) : (
              <Badge variant="error" label={item.auto_stopped ? "자동품절" : "판매중지"} />
            )}
          </StackItem>
        </HStack>
        <Grid columns={2} gap={2}>
          <VStack gap={0.5} align="start">
            <Text size="sm" color="secondary">
              판매가
            </Text>
            <Text weight="semibold" textWrap="nowrap">{won(item.sale_price)}</Text>
          </VStack>
          <VStack gap={0.5} align="start">
            <Text size="sm" color="secondary">
              재고
            </Text>
            {lowStock ? (
              <Badge variant="error" label={`${item.stock}개`} />
            ) : (
              <Text weight="semibold" textWrap="nowrap">{item.stock}개</Text>
            )}
          </VStack>
          <VStack gap={0.5} align="start">
            <Text size="sm" color="secondary">
              경쟁 최저
            </Text>
            <Text weight="semibold" textWrap="nowrap">{item.lowest === null ? "-" : won(item.lowest)}</Text>
          </VStack>
          <VStack gap={0.5} align="start">
            <Text size="sm" color="secondary">
              가격 순위
            </Text>
            <Badge
              variant={item.rank === 1 ? "success" : item.rank === item.total ? "error" : "neutral"}
              label={`${item.rank}/${item.total}`}
            />
          </VStack>
        </Grid>
      </VStack>
    </Card>
  );
}

/** StatusDot 이 받는 값은 accent·error·neutral·success·warning 뿐이다 (info 는 없다). */
const ALERT_DOT: Record<Alert["level"], "error" | "warning" | "accent"> = {
  danger: "error",
  warn: "warning",
  info: "accent",
};

function Alerts({alerts}: {alerts: Alert[]}) {
  const firing = alerts.filter((a) => a.level === "danger").length;
  return (
    <VStack gap={3}>
      <HStack gap={2} justify="between" align="center">
        <Heading level={2}>최근 알림</Heading>
        {firing > 0 ? <Badge variant="error" label={`${firing}건 주의`} /> : null}
      </HStack>
      {alerts.length === 0 ? (
        <EmptyState
          title="알림이 없습니다"
          description="가격이 밀리거나 재고가 부족하면 여기에 쌓입니다."
          isCompact
        />
      ) : (
        <List hasDividers>
          {alerts.map((a, i) => (
            <ListItem
              key={`${a.at}-${i}`}
              startContent={<StatusDot variant={ALERT_DOT[a.level]} label={a.level} />}
              label={a.message}
              description={a.at}
            />
          ))}
        </List>
      )}
    </VStack>
  );
}

type PriceTableRow = PriceRow & Record<string, unknown>;

function PriceTable({rows, isNarrow}: {rows: PriceRow[]; isNarrow: boolean}) {
  // 좁은 화면에서는 '경쟁 최저' 와 '순위' 가 화면 밖으로 밀려 안 보였다.
  // 차이 배지가 심각도를 담고 있으니, 폰에서는 상품·내 가격·차이만 남긴다.
  // 배열로 빼면 align 이 넓은 string 으로 추론된다. 타입을 못박는다.
  const columns: TableColumn<PriceTableRow>[] = [
        {
          key: "name",
          header: "상품",
          width: proportional(3),
          // 폰에서 상품명이 4글자로 잘려 구분이 안 됐다 → 두 줄까지 허용
          renderCell: (r: PriceTableRow) => (
            <HStack gap={1.5} align="center">
              {r.featured ? <Badge variant="info" label="주력" /> : null}
              <Text maxLines={isNarrow ? 2 : 1}>{r.name}</Text>
            </HStack>
          ),
        },
        {
          key: "sale_price",
          header: "내 가격",
          align: "end" as const,
          width: pixel(110),
          renderCell: (r: PriceTableRow) => <Text textWrap="nowrap">{won(r.sale_price)}</Text>,
        },
        ...(isNarrow
          ? []
          : [{
              key: "lowest",
              header: "경쟁 최저",
              align: "end" as const,
              width: pixel(110),
              renderCell: (r: PriceTableRow) => (
                <Text textWrap="nowrap">{r.lowest === null ? "-" : won(r.lowest)}</Text>
              ),
            }]),
        {
          key: "diff",
          header: "차이",
          align: "end" as const,
          width: pixel(120),
          // 전부 빨강이면 심각도가 안 보인다. 내 가격의 10% 이상 밀렸을 때만 빨강,
          // 그보다 적게 밀렸으면 주황, 내가 더 싸면 초록.
          renderCell: (r: PriceTableRow) =>
            r.diff === null ? (
              <Text color="secondary">-</Text>
            ) : (
              <Badge
                variant={r.diff <= 0 ? "success" : r.diff >= r.sale_price * 0.1 ? "error" : "warning"}
                label={r.diff > 0 ? `+${won(r.diff)}` : won(r.diff)}
              />
            ),
        },
        ...(isNarrow
          ? []
          : [{
              key: "rank",
              header: "순위",
              align: "center" as const,
              width: pixel(90),
              // 1등은 초록, 꼴등은 빨강, 그 사이는 중립. 2/6 까지 빨강일 이유가 없다.
              renderCell: (r: PriceTableRow) => (
                <Badge
                  variant={r.rank === 1 ? "success" : r.rank === r.total ? "error" : "neutral"}
                  label={`${r.rank}/${r.total}`}
                />
              ),
            }]),
  ];
  return <Table data={rows as PriceTableRow[]} columns={columns} />;
}

export default function Dashboard() {
  const isNarrow = useIsNarrow();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetchDashboard()
        .then((d) => {
          if (!alive) return;
          setData(d);
          setError(null);
        })
        .catch((e: unknown) => {
          if (e instanceof AuthError) {
            location.href = "/login";
            return;
          }
          if (alive) setError(e instanceof Error ? e.message : String(e));
        });
    void load();
    const timer = setInterval(() => void load(), 30_000); // 기존 화면과 같은 30초 주기
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  if (error !== null) {
    return (
      <Section padding={6}>
        <EmptyState title="데이터를 불러오지 못했습니다" description={error} />
      </Section>
    );
  }
  if (data === null) {
    return (
      <Section padding={6}>
        <VStack align="center" padding={6}>
          <Spinner label="불러오는 중" />
        </VStack>
      </Section>
    );
  }

  const {kpi, featured, alerts, prices, soldout_threshold: threshold} = data;

  const main = (
    <Section padding={6}>
        <VStack gap={6}>
          <VStack gap={1}>
            <Heading level={1}>대시보드</Heading>
            <HStack gap={2} align="center">
              <StatusDot variant={data.sync_error === null ? "success" : "error"} label="동기화" />
              <Text size="sm" color="secondary">
                {data.sync_error === null
                  ? `마지막 동기화 ${data.last_sync ?? "-"}`
                  : `동기화 실패: ${data.sync_error}`}
              </Text>
            </HStack>
          </VStack>

          {/* auto-fit 은 데스크톱에서 5+1 로 쪼개져 외톨이가 생긴다. 폭에 따라 못박는다.
              390px 에서 3열은 화면을 넘고 라벨이 잘렸다. */}
          <Grid columns={isNarrow ? 2 : 3} gap={3}>
            <Kpi label="판매 옵션 수" value={`${kpi.total}`} />
            <Kpi label="재고 금액" value={won(kpi.stock_value)} />
            {/* 판매중인 것만 센다 — 자동품절된 0개 재고는 아래 품절 칸으로 간다 */}
            <Kpi label="재고 부족(판매중)" value={`${kpi.low}`} isBad={kpi.low > 0} />
            <Kpi label="품절·판매중지" value={`${kpi.soldout}`} isBad={kpi.soldout > 0} />
            <Kpi label="최저가 밀림" value={`${kpi.undercut}`} isBad={kpi.undercut > 0} />
            <Kpi label="자동 가격조정 ON" value={`${kpi.auto}`} />
          </Grid>

          <Divider />

          <VStack gap={3}>
            <HStack gap={2} align="center">
              <Heading level={2}>주력 상품</Heading>
              <Text size="sm" color="secondary">
                카드를 누르면 재고 관리로 갑니다
              </Text>
            </HStack>
            {featured.length === 0 ? (
              <EmptyState
                title="지정한 주력 상품이 없습니다"
                description="재고 관리에서 ☆를 눌러 추가하세요."
                isCompact
              />
            ) : (
              <Grid columns={{minWidth: 220, repeat: "fit"}} gap={3}>
                {featured.map((f) => (
                  <FeaturedCard key={f.vendor_item_id} item={f} threshold={threshold} />
                ))}
              </Grid>
            )}
          </VStack>

          <Divider />

          <VStack gap={3}>
            <Heading level={2}>가격 경쟁 현황</Heading>
            <PriceTable rows={prices} isNarrow={isNarrow} />
          </VStack>
        </VStack>
    </Section>
  );

  // 좁은 화면에서는 레일을 아래로 쌓는다. 나란히 두면 본문이 짜부라져
  // 제목이 한 글자씩 쪼개진다 (390px 에서 실측 128px).
  if (isNarrow) {
    return (
      <VStack gap={0}>
        {main}
        <Section padding={6} variant="section" dividers={["start"]}>
          <Alerts alerts={alerts} />
        </Section>
      </VStack>
    );
  }

  return (
    <HStack gap={0}>
      <StackItem size="fill">{main}</StackItem>
      <Section padding={6} variant="section" dividers={["start"]} width={340}>
        <Alerts alerts={alerts} />
      </Section>
    </HStack>
  );
}
