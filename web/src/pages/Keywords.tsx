/**
 * 실시간 검색어 — 기존 Jinja 화면(templates/keywords.html)과 같은 일을 한다.
 *
 * 내가 파는 상품 이름에서 바탕말을 뽑아, 고른 출처(구글·네이버·다음·쿠팡)의
 * 연관검색어를 보여준다. 출처 하나가 실패해도 화면은 그대로 뜨고 오류만 적는다.
 */
import {useCallback, useEffect, useState} from "react";
import {VStack, HStack, StackItem} from "@astryxdesign/core/Stack";
import {Section} from "@astryxdesign/core/Section";
import {Card} from "@astryxdesign/core/Card";
import {Grid} from "@astryxdesign/core/Grid";
import {Text, Heading} from "@astryxdesign/core/Text";
import {Badge} from "@astryxdesign/core/Badge";
import {Button} from "@astryxdesign/core/Button";
import {Banner} from "@astryxdesign/core/Banner";
import {Divider} from "@astryxdesign/core/Divider";
import {EmptyState} from "@astryxdesign/core/EmptyState";
import {Spinner} from "@astryxdesign/core/Spinner";
import {Token} from "@astryxdesign/core/Token";
import {SegmentedControl, SegmentedControlItem} from "@astryxdesign/core/SegmentedControl";
import {AuthError, fetchKeywords} from "../api";
import type {KeywordData, KeywordProduct} from "../api";

/**
 * 칩에서 되풀이되는 바탕말을 뗀다.
 *
 * 검색어 8개가 모두 "고속충전 케이블 …" 로 시작하면 칩이 길어지고 카드가 빽빽해진다.
 * 바탕말은 카드 위에 한 번 적어 두고, 칩에는 덧말만 남긴다.
 * 바탕말로 시작하지 않는 검색어는 그대로 둔다.
 */
function suffixOf(keyword: string, base: string): string {
  if (base === "" || !keyword.startsWith(base)) return keyword;
  const rest = keyword.slice(base.length).trim();
  return rest === "" ? keyword : rest;
}

function ProductCard({product}: {product: KeywordProduct}) {
  return (
    <Card padding={4}>
      <VStack gap={3} hAlign="start">
        {/* 배지를 제목과 같은 줄에 두면 배지 개수에 따라 제목 시작 위치가 달라진다 */}
        {product.featured || !product.on_sale ? (
          <HStack gap={2} vAlign="center" wrap="wrap">
            {/* 파란 칩들과 섞이지 않게 다른 계열로 */}
            {product.featured ? <Badge variant="purple" label="주력" /> : null}
            {!product.on_sale ? <Badge variant="error" label="판매중지" /> : null}
          </HStack>
        ) : null}
        <Text weight="semibold" maxLines={2}>
          {product.name}
        </Text>
        {product.error !== null ? (
          // 한 상품만 실패할 수 있다. 나머지는 그대로 보여준다.
          <Text size="sm" color="secondary">
            이 상품은 가져오지 못했습니다: {product.error}
          </Text>
        ) : product.keywords.length === 0 ? (
          <Text size="sm" color="secondary">
            연관검색어가 없습니다
          </Text>
        ) : (
          // Link 로 두면 맨 글자로 이어져 어디서 끊기는지 안 보였다. Token 은 칩 모양이라
          // 경계가 보이고 href 도 받는다. 누르면 그 검색어로 실제 검색 결과를 연다.
          <HStack gap={2} wrap="wrap">
            {/* 핵심어를 칩 흐름의 맨 앞에 둔다. 덧말 칩과 한 줄에서 이어지므로 줄바꿈이
                의도처럼 읽히고, '+덧말' 이 무엇과 합쳐지는지도 바로 보인다. */}
            <Token label={product.query} size="sm" color="gray" />
            {product.keywords.map((k) => {
              const suffix = suffixOf(k.keyword, product.query);
              return (
                <Token
                  key={k.keyword}
                  // 칩에 '추천' 만 있으면 '추천' 을 검색하는 줄로 읽힌다. '+' 로 합쳐짐을 보인다.
                  label={suffix === k.keyword ? k.keyword : `+${suffix}`}
                  // href 를 주면 같은 탭에서 열려 앱을 떠난다. Token 은 target 을 받지 않으므로
                  // 직접 새 탭으로 연다 (기존 Jinja 화면도 target="_blank" 였다).
                  onClick={() => window.open(k.url, "_blank", "noopener,noreferrer")}
                  size="sm"
                  color="blue"
                />
              );
            })}
          </HStack>
        )}
      </VStack>
    </Card>
  );
}

export default function Keywords() {
  const [data, setData] = useState<KeywordData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const load = useCallback(
    async (which?: string) => {
      setIsBusy(true);
      try {
        const d = await fetchKeywords(which);
        setData(d);
        setSource(d.source);
        setLoadError(null);
      } catch (e) {
        if (e instanceof AuthError) {
          location.href = "/login";
          return;
        }
        setLoadError(e instanceof Error ? e.message : String(e));
      } finally {
        setIsBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  if (loadError !== null) {
    return (
      <Section padding={6}>
        <EmptyState
          title="검색어를 불러오지 못했습니다"
          description={loadError}
          actions={<Button label="다시 시도" variant="secondary" clickAction={async () => load()} />}
        />
      </Section>
    );
  }
  if (data === null) {
    return (
      <Section padding={6}>
        <VStack vAlign="center" padding={6}>
          <Spinner label="불러오는 중" />
        </VStack>
      </Section>
    );
  }

  return (
    <Section padding={6}>
      <VStack gap={6}>
        <HStack gap={3} vAlign="center" wrap="wrap">
          <StackItem size="fill">
            <VStack gap={1} hAlign="start">
              <Heading level={1}>실시간 검색어</Heading>
              <Text size="sm" color="secondary">
                {data.label} 기준 · {data.checked} 확인 · 상품 {data.products.length}개
              </Text>
            </VStack>
          </StackItem>
          <Button label="새로 가져오기" variant="secondary" isLoading={isBusy} clickAction={async () => load(source ?? undefined)} />
        </HStack>

        {/* 실거래 모드인데 검색어만 모의면 사용자가 알아야 한다. 가짜 숫자로 결정하면 안 된다. */}
        {data.mock_on_live ? (
          <Banner
            status="warning"
            title="검색어가 모의 데이터입니다"
            description="실거래 모드로 돌고 있지만 검색어 제공자는 모의 상태입니다. 아래 검색어로 판단하지 마세요."
          />
        ) : data.mock ? (
          <Banner
            status="info"
            title="모의 검색어"
            description="실제 검색 데이터가 아닌 예시입니다."
          />
        ) : null}

        {data.related_error !== null ? (
          <Banner
            status="warning"
            title={`${data.label} 에서 가져오지 못했습니다`}
            description={data.related_error}
          />
        ) : null}

        <HStack gap={3} vAlign="center" wrap="wrap">
          <SegmentedControl
            label="검색어 출처"
            value={source ?? data.source}
            onChange={(v) => {
              setSource(v);
              void load(v);
            }}
          >
            {data.sources.map((s) => (
              <SegmentedControlItem key={s.id} value={s.id} label={s.label} />
            ))}
          </SegmentedControl>
        </HStack>

        <Text size="sm" color="secondary">
          검색어를 누르면 실제 검색 결과가 열립니다
        </Text>

        <Divider />

        {data.products.length === 0 ? (
          <EmptyState title="상품이 없습니다" description="쿠팡 동기화가 끝나면 여기에 나옵니다." />
        ) : (
          <Grid columns={{minWidth: 340, repeat: "fit"}} gap={4}>
            {data.products.map((p) => (
              <ProductCard key={p.name} product={p} />
            ))}
          </Grid>
        )}
      </VStack>
    </Section>
  );
}
