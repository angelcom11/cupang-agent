/**
 * 재고 관리 — 기존 Jinja 화면(templates/inventory.html)과 같은 일을 한다.
 *
 * 동작은 전부 /api/items/* 로 가고, 그 몸통은 Jinja 화면과 같은 함수를 쓴다
 * (app.py 의 _toggle_featured / _toggle_sale / _update_stock). 한쪽만 고쳐지는 일을 막는다.
 *
 * 열이 많아서 화면이 시끄러워지기 쉽다. 그래서 저장 버튼은 값을 건드린 줄에만 나온다.
 */
import {useEffect, useMemo, useState} from "react";
import {VStack, HStack, StackItem} from "@astryxdesign/core/Stack";
import {Section} from "@astryxdesign/core/Section";
import {Text, Heading} from "@astryxdesign/core/Text";
import {Badge} from "@astryxdesign/core/Badge";
import {Switch} from "@astryxdesign/core/Switch";
import {Icon} from "@astryxdesign/core/Icon";
import {IconButton} from "@astryxdesign/core/IconButton";
import {TextInput} from "@astryxdesign/core/TextInput";
import {NumberInput} from "@astryxdesign/core/NumberInput";
import {Button} from "@astryxdesign/core/Button";
import {Banner} from "@astryxdesign/core/Banner";
import {Divider} from "@astryxdesign/core/Divider";
import {EmptyState} from "@astryxdesign/core/EmptyState";
import {Spinner} from "@astryxdesign/core/Spinner";
import {Table, proportional, pixel, useTableSelection, useTableSelectionState} from "@astryxdesign/core/Table";
import {
  AuthError,
  deleteItems,
  fetchInventory,
  saveStock,
  toggleFeatured,
  toggleSale,
  won,
} from "../api";
import type {InventoryItem} from "../api";
import {StarIcon as StarOutline, MagnifyingGlassIcon} from "@heroicons/react/24/outline";
import {StarIcon as StarSolid} from "@heroicons/react/24/solid";

type Row = InventoryItem & Record<string, unknown>;

/** 한 줄에서 사람이 고친 값. 저장 전까지만 들고 있는다. */
interface Edit {
  stock?: number | null;
  low?: number | null;
}

interface Notice {
  status: "success" | "error";
  title: string;
  description?: string;
}

export default function Inventory() {
  const [items, setItems] = useState<Row[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [query, setQuery] = useState("");
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [confirmText, setConfirmText] = useState("");
  const [stopFirst, setStopFirst] = useState(true);

  const onFail = (e: unknown) => {
    if (e instanceof AuthError) {
      location.href = "/login";
      return;
    }
    setNotice({status: "error", title: "실패했습니다", description: e instanceof Error ? e.message : String(e)});
  };

  const reload = async () => {
    const data = await fetchInventory();
    setItems(data.items as Row[]);
    return data;
  };

  useEffect(() => {
    let alive = true;
    fetchInventory()
      .then((d) => {
        if (alive) setItems(d.items as Row[]);
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
    if (items === null) return [];
    const q = query.trim().toLowerCase();
    if (q === "") return items;
    // 상품명과 옵션ID 둘 다로 찾는다 — 현장에서는 옵션ID 로 찾는 일이 많다.
    return items.filter(
      (i) => i.name.toLowerCase().includes(q) || i.vendor_item_id.toLowerCase().includes(q),
    );
  }, [items, query]);

  // 삭제 경고 위에 초록 성공 배너가 남아 있으면 신호가 섞인다.
  useEffect(() => {
    if (selectedKeys.size > 0) setNotice(null);
  }, [selectedKeys]);

  const {selectionConfig, selectionState} = useTableSelectionState<Row>({
    data: visible,
    idKey: "vendor_item_id",
    selectedKeys,
    setSelectedKeys,
  });
  const selectionPlugin = useTableSelection<Row>(selectionConfig);

  const editOf = (vid: string): Edit => edits[vid] ?? {};
  const setEdit = (vid: string, patch: Edit) =>
    setEdits((prev) => ({...prev, [vid]: {...prev[vid], ...patch}}));
  const isDirty = (r: Row) => {
    const e = editOf(r.vendor_item_id);
    return (
      (e.stock !== undefined && e.stock !== r.stock) || (e.low !== undefined && e.low !== r.low_stock)
    );
  };

  if (loadError !== null) {
    return (
      <Section padding={6}>
        <EmptyState title="재고를 불러오지 못했습니다" description={loadError} />
      </Section>
    );
  }
  if (items === null) {
    return (
      <Section padding={6}>
        <VStack vAlign="center" padding={6}>
          <Spinner label="불러오는 중" />
        </VStack>
      </Section>
    );
  }

  const selectedItems = items.filter((i) => selectedKeys.has(i.vendor_item_id));

  return (
    <Section padding={6}>
      <VStack gap={6}>
        <HStack gap={3} vAlign="center" wrap="wrap">
          <StackItem size="fill">
            <Heading level={1}>재고 관리</Heading>
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

        {selectedItems.length > 0 ? (
          // 되돌릴 수 없는 일이다. 무엇을 지우는지 이름으로 보여주고, 경고 배너로 띄운다.
          <Banner
            status="error"
            title={`${selectedItems.length}개 상품을 삭제합니다 — 되돌릴 수 없습니다`}
            description={`쿠팡에서 지워집니다: ${selectedItems
              .slice(0, 3)
              .map((i) => i.name)
              .join(", ")}${selectedItems.length > 3 ? ` 외 ${selectedItems.length - 3}개` : ""}`}
            // Banner 의 children 은 기본으로 접혀 있다(collapsible 기본 true). 삭제 확인을
            // 접어두면 사용자가 열 생각을 못 한다 — 실제로 확인칸과 버튼이 안 보였다.
            collapsible={false}
          >
            <VStack gap={3}>
              <HStack gap={3} vAlign="end" wrap="wrap">
                <VStack width={200}>
                  <TextInput
                    label="확인: '삭제' 를 입력"
                    value={confirmText}
                    onChange={setConfirmText}
                  />
                </VStack>
                {/* 고른 게 모두 이미 판매중지면 이 토글은 쓸 데가 없다. */}
                {selectedItems.some((i) => i.on_sale) ? (
                  <Switch
                    label="먼저 판매중지"
                    value={stopFirst}
                    onChange={setStopFirst}
                    description="판매중인 상품은 중지해야 지워집니다"
                  />
                ) : null}
                <StackItem size="static">
                  <Button
                    label="삭제"
                    variant="destructive"
                    isDisabled={confirmText.trim() !== "삭제"}
                    clickAction={async () => {
                      try {
                        const {results} = await deleteItems(
                          selectedItems.map((i) => i.seller_product_id),
                          confirmText,
                          stopFirst,
                        );
                        const failed = results.filter((r) => !r.ok);
                        setNotice(
                          failed.length === 0
                            ? {status: "success", title: `${results.length}개 삭제했습니다`}
                            : {
                                status: "error",
                                title: `${failed.length}개 실패`,
                                description: failed.map((r) => `${r.name}: ${r.message}`).join(" / "),
                              },
                        );
                        selectionState.clearSelection();
                        setConfirmText("");
                        await reload();
                      } catch (e) {
                        onFail(e);
                      }
                    }}
                  />
                </StackItem>
                <Button label="취소" variant="secondary" onClick={() => selectionState.clearSelection()} />
              </HStack>
            </VStack>
          </Banner>
        ) : null}

        <HStack gap={2} vAlign="center">
          <Text size="sm" color="secondary">
            상품 {items.length}개
            {query.trim() === "" ? "" : ` 중 ${visible.length}개 표시`}
          </Text>
          <Text size="sm" color="secondary">
            · 재고나 기준을 고치면 그 줄에 저장 버튼이 나옵니다
          </Text>
        </HStack>

        <Divider />

        {visible.length === 0 ? (
          <EmptyState
            title={query.trim() === "" ? "상품이 없습니다" : "찾는 상품이 없습니다"}
            description={query.trim() === "" ? "쿠팡 동기화가 끝나면 여기에 나옵니다." : `'${query}' 와 맞는 상품이 없습니다.`}
            actions={query.trim() === "" ? undefined : <Button label="검색 지우기" variant="secondary" onClick={() => setQuery("")} />}
          />
        ) : (
          <Table<Row>
            data={visible}
            idKey="vendor_item_id"
            density="balanced"
            hasHover
            plugins={{selection: selectionPlugin}}
            columns={[
              {
                key: "featured",
                header: "주력",
                width: pixel(70),
                align: "center",
                // 스위치를 두 열에 나란히 두면 뜻을 혼동한다. 스위치는 판매 on/off 에만 쓰고
                // 주력은 별로 보인다 (기존 Jinja 화면의 ☆ 와 같은 뜻).
                renderCell: (r: Row) => (
                  <IconButton
                    label={r.featured ? `${r.name} 주력 해제` : `${r.name} 주력 지정`}
                    icon={<Icon icon={r.featured ? StarSolid : StarOutline} size="sm" />}
                    variant="ghost"
                    clickAction={async () => {
                      try {
                        await toggleFeatured(r.vendor_item_id);
                        await reload();
                      } catch (e) {
                        onFail(e);
                      }
                    }}
                  />
                ),
              },
              {
                key: "name",
                header: "상품 / 옵션",
                width: proportional(1),
                renderCell: (r: Row) => (
                  <VStack gap={0.5} hAlign="start">
                    <Text maxLines={2}>{r.name}</Text>
                    <Text size="sm" color="secondary">
                      {r.vendor_item_id}
                    </Text>
                  </VStack>
                ),
              },
              {
                key: "on_sale",
                header: "판매상태",
                width: pixel(170),
                renderCell: (r: Row) => (
                  <HStack gap={2} vAlign="center">
                    <Switch
                      label={`${r.name} 판매`}
                      isLabelHidden
                      value={r.on_sale}
                      changeAction={async () => {
                        try {
                          const {message} = await toggleSale(r.vendor_item_id);
                          setNotice({status: "success", title: message});
                          await reload();
                        } catch (e) {
                          onFail(e);
                        }
                      }}
                    />
                    {r.auto_stopped ? <Badge variant="warning" label="자동중지" /> : null}
                  </HStack>
                ),
              },
              {
                key: "sale_price",
                header: "판매가",
                width: pixel(110),
                align: "end",
                renderCell: (r: Row) => <Text textWrap="nowrap">{won(r.sale_price)}</Text>,
              },
              {
                key: "stock",
                header: "재고",
                width: pixel(120),
                align: "end",
                // 입력칸을 직접 고치게 둔다. 저장은 아래 열의 버튼으로 한 번에.
                renderCell: (r: Row) => (
                  // 기준 이하면 칸 자체가 붉어진다. 0 과 130 이 똑같아 보이면 안 된다.
                  // message 는 주지 않는다 — 입력칸 아래에 상자가 생겨 행 높이가 들쭉날쭉해진다.
                  <NumberInput
                    label={`${r.name} 재고`}
                    isLabelHidden
                    min={0}
                    width={90}
                    status={
                      r.stock === 0
                        ? {type: "error"}
                        : r.stock <= r.low_stock
                          ? {type: "warning"}
                          : undefined
                    }
                    value={editOf(r.vendor_item_id).stock ?? r.stock}
                    onChange={(v) => setEdit(r.vendor_item_id, {stock: v})}
                  />
                ),
              },
              {
                key: "low_stock",
                header: "부족 기준",
                width: pixel(110),
                align: "end",
                renderCell: (r: Row) => (
                  <NumberInput
                    label={`${r.name} 부족 알림 기준`}
                    isLabelHidden
                    min={0}
                    width={80}
                    value={editOf(r.vendor_item_id).low ?? r.low_stock}
                    onChange={(v) => setEdit(r.vendor_item_id, {low: v})}
                  />
                ),
              },
              {
                key: "save",
                header: "",
                width: pixel(80),
                align: "center",
                // 모든 줄에 버튼을 두면 화면이 시끄럽다. 값을 건드린 줄에만 낸다.
                renderCell: (r: Row) =>
                  isDirty(r) ? (
                    <Button
                      label="저장"
                      size="sm"
                      clickAction={async () => {
                        const e = editOf(r.vendor_item_id);
                        try {
                          const {message} = await saveStock(
                            r.vendor_item_id,
                            // 서버는 빈 값이면 재고를 건드리지 않는다. 기준만 고친 줄이 그렇다.
                            e.stock === undefined || e.stock === null ? "" : String(e.stock),
                            String(e.low ?? r.low_stock),
                          );
                          setNotice({status: "success", title: message});
                          setEdits((prev) => {
                            const next = {...prev};
                            delete next[r.vendor_item_id];
                            return next;
                          });
                          await reload();
                        } catch (err) {
                          onFail(err);
                        }
                      }}
                    />
                  ) : null,
              },
            ]}
          />
        )}
      </VStack>
    </Section>
  );
}
