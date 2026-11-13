/**
 * 상품 등록 마법사 — 기존 Jinja 화면(templates/register.html, 503줄)을 옮긴 것.
 *
 * 단계 목록 · 기본값 · 검증 · 임시저장은 전부 서버가 갖고 있다(product_form.py).
 * 여기서 다시 정의하지 않는다 — 규칙이 갈라지면 한쪽만 고쳐지는 사고가 난다.
 *
 * 핵심은 오류 처리다. /api/register/validate 는 오류마다 고칠 단계를 붙여 준다
 * ({message, step, sub}). 그래서 "뭐가 틀렸는지는 알려주는데 어디서 고치는지 모르는"
 * 상태가 생기지 않는다. 오류를 누르면 그 단계로 데려간다.
 */
import {useCallback, useEffect, useMemo, useState} from "react";
import {Banner} from "@astryxdesign/core/Banner";
import {Button} from "@astryxdesign/core/Button";
import {Card} from "@astryxdesign/core/Card";
import {Divider} from "@astryxdesign/core/Divider";
import {FormLayout} from "@astryxdesign/core/FormLayout";
import {NumberInput} from "@astryxdesign/core/NumberInput";
import {RadioList, RadioListItem} from "@astryxdesign/core/RadioList";
import {Section} from "@astryxdesign/core/Section";
import {Selector} from "@astryxdesign/core/Selector";
import {Spinner} from "@astryxdesign/core/Spinner";
import {HStack, StackItem, VStack} from "@astryxdesign/core/Stack";
import {Toolbar} from "@astryxdesign/core/Toolbar";
import {Step, Stepper} from "@astryxdesign/core/Stepper";
import {Switch} from "@astryxdesign/core/Switch";
import {Heading, Text} from "@astryxdesign/core/Text";
import {TextArea} from "@astryxdesign/core/TextArea";
import {TextInput} from "@astryxdesign/core/TextInput";
import {useMediaQuery} from "@astryxdesign/core/hooks";
import {NARROW_QUERY} from "../narrow";
import {
  fetchRegisterMeta,
  loadRegisterDraft,
  registerSubmit,
  registerValidate,
  RegisterInvalid,
  saveRegisterDraft,
  type RegisterDraft,
  type RegisterError,
  type RegisterForm,
  type RegisterMeta,
} from "../api";


/** 쿠팡이 정한 값들. 라벨은 기존 화면과 같은 말을 쓴다. */
const DELIVERY_METHODS = [
  {value: "SEQUENCIAL", label: "일반배송(순차배송)"},
  {value: "COLD_FRESH", label: "신선냉동"},
  {value: "MAKE_ORDER", label: "주문제작"},
];
const CHARGE_TYPES = [
  {value: "FREE", label: "무료배송"},
  {value: "NOT_FREE", label: "유료배송"},
  {value: "CONDITIONAL_FREE", label: "조건부 무료배송"},
];
const COURIERS = [
  {value: "CJGLS", label: "CJ대한통운"},
  {value: "HANJIN", label: "한진택배"},
  {value: "HYUNDAI", label: "롯데택배"},
  {value: "KGB", label: "로젠택배"},
  {value: "EPOST", label: "우체국"},
];
const OFFER_CONDITIONS = [
  {value: "NEW", label: "새 상품"},
  {value: "REFURBISHED", label: "리퍼"},
  {value: "USED_BEST", label: "중고(최상)"},
  {value: "USED_GOOD", label: "중고(상)"},
];

/**
 * 숫자칸의 빈 값. 0 을 넣으면 "값이 0" 처럼 보여서, 판매가를 안 넣은 건지
 * 0원인 건지 구분이 안 된다. NumberInput 은 null 을 빈 칸으로 받는다.
 */
function num(raw: string): number | null {
  const t = raw.trim();
  return t === "" ? null : Number(t);
}

function str(form: RegisterForm, key: string): string {
  const v = form[key];
  return v === null || v === undefined ? "" : String(v);
}

export default function Register() {
  // 좁으면 단계 목록을 위로 눕힌다 — 14단계가 세로 레일로는 다 안 들어간다.
  const isNarrow = useMediaQuery(NARROW_QUERY);
  const [meta, setMeta] = useState<RegisterMeta | null>(null);
  const [form, setForm] = useState<RegisterForm>({});
  const [stepId, setStepId] = useState("s-name");
  const [errors, setErrors] = useState<RegisterError[]>([]);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  const [draftId, setDraftId] = useState<number | null>(null);
  const [remember, setRemember] = useState(false);

  useEffect(() => {
    fetchRegisterMeta()
      .then((m) => {
        setMeta(m);
        setForm(m.form);
      })
      .catch((e: Error) => setFailure(e.message));
  }, []);

  const set = useCallback((key: string, value: unknown) => {
    setForm((f: RegisterForm) => ({...f, [key]: value}));
  }, []);

  /** 단계마다 오류가 몇 개인지 — 단계 목록에 그대로 표시한다. */
  const errorsByStep = useMemo(() => {
    const m: Record<string, RegisterError[]> = {};
    for (const e of errors) (m[e.step] ??= []).push(e);
    return m;
  }, [errors]);

  const steps = meta?.steps ?? [];
  const index = Math.max(0, steps.findIndex((s) => s.id === stepId));
  const current = steps[index];

  async function check(): Promise<boolean> {
    setBusy("검사");
    setNotice("");
    setFailure("");
    try {
      const r = await registerValidate(form);
      setErrors(r.errors);
      if (r.errors.length > 0) {
        // 틀린 곳이 여러 단계에 흩어져 있을 수 있다. 첫 번째 단계로 데려간다.
        setStepId(r.errors[0].step);
        setFailure("고칠 곳이 있습니다. 아래 목록을 누르면 그 단계로 갑니다.");
      } else {
        setNotice("검사를 통과했습니다. 판매요청을 보낼 수 있습니다.");
      }
      return r.errors.length === 0;
    } catch (e) {
      setFailure((e as Error).message);
      return false;
    } finally {
      setBusy("");
    }
  }

  async function saveDraft() {
    setBusy("임시저장");
    setFailure("");
    try {
      const r = await saveRegisterDraft(form, draftId, remember);
      setDraftId(r.draft_id);
      setNotice(r.message);
      setMeta((m) => (m === null ? m : {...m, drafts: r.drafts}));
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function loadDraft(id: number) {
    setBusy("불러오기");
    setFailure("");
    try {
      const r = await loadRegisterDraft(id);
      setForm(r.form);
      setDraftId(r.draft_id);
      setErrors([]);
      setNotice("임시저장을 불러왔습니다. 이어서 고치세요.");
      setStepId("s-name");
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  /** action=save 는 쿠팡에 임시저장, request 는 바로 판매요청 — WING 의 두 버튼과 같다. */
  async function submit(action: "save" | "request") {
    setBusy(action === "request" ? "판매요청" : "쿠팡 임시저장");
    setNotice("");
    setFailure("");
    try {
      const r = await registerSubmit(form, action, draftId, remember);
      setErrors([]);
      setDraftId(r.draft_id);
      setNotice(r.message);
    } catch (e) {
      // 검증 실패는 보통의 실패가 아니다. 고칠 목록을 받아 그 단계로 데려간다.
      if (e instanceof RegisterInvalid) {
        setErrors(e.errors);
        setStepId(e.errors[0].step);
        setFailure("고칠 곳이 있습니다. 아래 목록을 누르면 그 단계로 갑니다.");
      } else {
        setFailure((e as Error).message);
      }
    } finally {
      setBusy("");
    }
  }

  if (failure !== "" && meta === null) {
    return (
      <Section padding={6}>
        <VStack gap={4}>
          <Heading level={1}>상품 등록</Heading>
          <Banner status="error" title="등록 화면을 열지 못했습니다" collapsible={false}>
            <Text>{failure}</Text>
          </Banner>
        </VStack>
      </Section>
    );
  }
  if (meta === null || current === undefined) {
    return (
      <Section padding={6}>
        <VStack gap={4}>
          <Heading level={1}>상품 등록</Heading>
          <HStack gap={2} align="center">
            <Spinner />
            <Text color="secondary">불러오는 중…</Text>
          </HStack>
        </VStack>
      </Section>
    );
  }

  const stepList = (
    <Stepper
      // step·activeStep 은 0 부터다 (d.ts: Zero-based index). 1 부터 넘기면
      // 2단계 표시가 "3" 으로 밀린다.
      activeStep={index}
      orientation={isNarrow ? "horizontal" : "vertical"}
      onStepClick={(n: number) => setStepId(steps[n].id)}
      label="등록 단계"
    >
      {steps.map((s, i) => (
        <Step
          key={s.id}
          step={i}
          label={s.label}
          // 오류가 있는 단계를 목록에서 바로 알아보게 한다. 검사를 누르기 전에는
          // 아무 단계도 빨갛지 않다 — 아직 틀렸다고 말할 근거가 없다.
          status={errorsByStep[s.id] === undefined ? undefined : "error"}
          endContent={
            errorsByStep[s.id] === undefined ? null : (
              <Text size="2xs" color="secondary">
                {errorsByStep[s.id].length}
              </Text>
            )
          }
        />
      ))}
    </Stepper>
  );

  const body = (
    <VStack gap={4}>
      <Heading level={2}>{current.label}</Heading>
      {errorsByStep[current.id] === undefined ? null : (
        <Banner status="error" title="이 단계에서 고칠 것" collapsible={false}>
          <VStack gap={1}>
            {errorsByStep[current.id].map((e) => (
              <Text key={e.message} size="sm">
                {e.message}
              </Text>
            ))}
          </VStack>
        </Banner>
      )}
      <StepFields
        stepId={current.id}
        form={form}
        set={set}
        meta={meta}
        remember={remember}
        onRemember={setRemember}
      />
    </VStack>
  );

  return (
    <Section padding={6}>
      <VStack gap={4}>
        <Heading level={1}>상품 등록</Heading>
        {meta.mode !== "live" ? (
          <Banner status="info" title={`모의 모드입니다 (${meta.mode})`} collapsible={false}>
            <Text size="sm">쿠팡에 실제로 보내지 않습니다. 화면과 검증만 확인할 수 있습니다.</Text>
          </Banner>
        ) : null}
        {notice === "" ? null : (
          <Banner status="success" title={notice} collapsible={false} />
        )}
        {failure === "" ? null : (
          <Banner status="error" title={failure} collapsible={false}>
            {errors.length === 0 ? null : (
              <VStack gap={1} align="start">
                {errors.map((e) => (
                  <Button
                    key={e.message + e.step}
                    variant="ghost"
                    size="sm"
                    label={`${steps.find((s) => s.id === e.step)?.label ?? e.step} · ${e.message}`}
                    onClick={() => setStepId(e.step)}
                  />
                ))}
              </VStack>
            )}
          </Banner>
        )}

        {isNarrow ? (
          <VStack gap={4}>
            {stepList}
            <Divider isFullBleed />
            {body}
          </VStack>
        ) : (
          <HStack gap={0} align="start">
            {/* Stepper 가 이미 세로선을 그린다. 여기에 dividers 를 더하면 선이 두 겹이 되고
                아래 툴바를 뚫고 나온다. */}
            <Section width={260} variant="section" padding={4}>
              {stepList}
            </Section>
            <StackItem size="fill">
              <Section padding={4}>{body}</Section>
            </StackItem>
          </HStack>
        )}

        <ActionBar
          busy={busy}
          index={index}
          total={steps.length}
          drafts={meta.drafts}
          draftId={draftId}
          onStep={(n) => setStepId(steps[n].id)}
          onCheck={check}
          onSaveDraft={saveDraft}
          onLoadDraft={loadDraft}
          onSubmit={submit}
        />
      </VStack>
    </Section>
  );
}

function ActionBar({
  busy,
  index,
  total,
  drafts,
  draftId,
  onStep,
  onCheck,
  onSaveDraft,
  onLoadDraft,
  onSubmit,
}: {
  busy: string;
  index: number;
  total: number;
  drafts: RegisterDraft[];
  draftId: number | null;
  onStep: (n: number) => void;
  onCheck: () => void;
  onSaveDraft: () => void;
  onLoadDraft: (id: number) => void;
  onSubmit: (action: "save" | "request") => void;
}) {
  const working = busy !== "";
  return (
    // Toolbar 는 위에 구분선을 긋고 버튼 묶음을 양 끝으로 보낸다. 긴 폼 아래에
    // 그냥 두면 어디까지가 입력이고 어디부터가 동작인지 구분이 안 된다.
    <VStack gap={3}>
      <Toolbar
        label="등록 동작"
        dividers={["top"]}
        startContent={
          <HStack gap={2}>
            <Button
              variant="secondary"
              label="이전 단계"
              isDisabled={index === 0 || working}
              onClick={() => onStep(index - 1)}
            />
            <Button
              variant="secondary"
              label="다음 단계"
              isDisabled={index >= total - 1 || working}
              onClick={() => onStep(index + 1)}
            />
          </HStack>
        }
        endContent={
          <HStack gap={2}>
            <Button
              variant="secondary"
              label={busy === "검사" ? "검사 중…" : "검사"}
              isDisabled={working}
              onClick={onCheck}
            />
            <Button
              variant="secondary"
              label={busy === "임시저장" ? "저장 중…" : "임시저장"}
              isDisabled={working}
              onClick={onSaveDraft}
            />
            <Button
              variant="primary"
              label={busy === "판매요청" ? "보내는 중…" : "판매요청"}
              isDisabled={working}
              onClick={() => onSubmit("request")}
            />
          </HStack>
        }
      />
      {draftId === null ? null : (
        <Text size="xsm" color="secondary">
          임시저장 #{draftId} 에 이어 쓰는 중
        </Text>
      )}
      {drafts.length === 0 ? null : (
        <HStack gap={2} align="center">
          <Text size="xsm" color="secondary">
            임시저장 불러오기
          </Text>
          {drafts.slice(0, 5).map((d) => (
            <Button
              key={d.id}
              variant="ghost"
              size="sm"
              label={d.name === "" ? `#${d.id} (이름 없음)` : d.name}
              tooltip={`${d.updated_at}${d.note === null ? "" : ` · ${d.note}`}`}
              isDisabled={working}
              onClick={() => onLoadDraft(d.id)}
            />
          ))}
        </HStack>
      )}
    </VStack>
  );
}

/** 단계별 입력. 아직 안 옮긴 단계는 기존 화면으로 보낸다 — 빈 화면을 보여주지 않는다. */
function StepFields({
  stepId,
  form,
  set,
  meta,
  remember,
  onRemember,
}: {
  stepId: string;
  form: RegisterForm;
  set: (key: string, value: unknown) => void;
  meta: RegisterMeta;
  remember: boolean;
  onRemember: (v: boolean) => void;
}) {
  if (stepId === "s-name") {
    return (
      <VStack gap={4} width={760}>
        <TextInput
          label="노출상품명"
          isRequired
          value={str(form, "display_name")}
          onChange={(v: string) => set("display_name", v)}
          description="구매자에게 보이는 이름입니다. 예: 데일리핏 스텐 진공 보온보냉 텀블러 500ml"
        />
        <TextInput
          label="등록상품명"
          value={str(form, "name")}
          onChange={(v: string) => set("name", v)}
          description="비워 두면 노출상품명을 씁니다. 판매자만 보는 이름입니다."
        />
      </VStack>
    );
  }
  if (stepId === "s-cat") {
    return (
      <VStack gap={4} width={760}>
        <TextInput
          label="카테고리 코드"
          isRequired
          value={str(form, "category_code")}
          onChange={(v: string) => set("category_code", v)}
          description="쿠팡 카테고리 번호입니다. 번호를 넣으면 필수 옵션과 제공고시를 쿠팡에서 불러옵니다."
        />
      </VStack>
    );
  }
  if (stepId === "s-main") {
    return (
      <VStack gap={5} width={760}>
        <FormLayout direction="horizontal">
          <TextInput
            label="브랜드"
            value={str(form, "brand")}
            onChange={(v: string) => set("brand", v)}
          />
          <TextInput
            label="제조사"
            value={str(form, "manufacture")}
            onChange={(v: string) => set("manufacture", v)}
          />
        </FormLayout>
        <Divider />
        <FormLayout direction="horizontal">
          <TextInput
            label="인증 종류"
            value={str(form, "certification_type")}
            onChange={(v: string) => set("certification_type", v)}
            description="해당 없으면 비워 둡니다."
          />
          <TextInput
            label="인증 번호"
            value={str(form, "certification_code")}
            onChange={(v: string) => set("certification_code", v)}
          />
        </FormLayout>
        <Divider />
        <Selector
          label="상품 상태"
          options={OFFER_CONDITIONS}
          value={str(form, "offer_condition")}
          onChange={(v: string) => set("offer_condition", v)}
        />
        <TextArea
          label="상품 상태 설명"
          value={str(form, "offer_description")}
          onChange={(v: string) => set("offer_description", v)}
          description="중고·리퍼라면 상태를 적습니다. 예: 박스 개봉, 사용감 거의 없음"
        />
        <Divider />
        <FormLayout direction="horizontal">
          <NumberInput
            label="1인 최대 구매수량"
            value={num(str(form, "max_per_person"))}
            onChange={(v: number | null) => set("max_per_person", v === null ? "" : String(v))}
            description="0 이면 제한하지 않습니다."
          />
          <NumberInput
            label="제한 기간"
            units="일"
            value={num(str(form, "max_per_person_period"))}
            onChange={(v: number | null) => set("max_per_person_period", v === null ? "" : String(v))}
          />
        </FormLayout>
        <FormLayout direction="horizontal">
          <TextInput
            label="판매 시작"
            value={str(form, "sale_start")}
            onChange={(v: string) => set("sale_start", v)}
            description="비워 두면 바로 시작합니다. 형식: 2026-11-13T09:00"
          />
          <TextInput
            label="판매 종료"
            value={str(form, "sale_end")}
            onChange={(v: string) => set("sale_end", v)}
          />
        </FormLayout>
      </VStack>
    );
  }
  if (stepId === "s-ship") {
    const outbound = meta.places.outbound.map((p) => ({value: p.code, label: p.name}));
    return (
      <VStack gap={5} width={760}>
        <Selector
          label="배송 방법"
          options={DELIVERY_METHODS}
          value={str(form, "delivery_method")}
          onChange={(v: string) => set("delivery_method", v)}
        />
        <FormLayout direction="horizontal">
          <Selector
            label="택배사"
            options={COURIERS}
            value={str(form, "delivery_company")}
            onChange={(v: string) => set("delivery_company", v)}
          />
          <Selector
            label="출고지"
            options={outbound.length === 0 ? [{value: "", label: "(등록된 출고지가 없습니다)"}] : outbound}
            value={str(form, "outbound_place_code")}
            onChange={(v: string) => set("outbound_place_code", v)}
          />
        </FormLayout>
        <Divider />
        <Selector
          label="배송비 종류"
          options={CHARGE_TYPES}
          value={str(form, "delivery_charge_type")}
          onChange={(v: string) => set("delivery_charge_type", v)}
        />
        <FormLayout direction="horizontal">
          <NumberInput
            label="배송비"
            units="원"
            value={num(str(form, "delivery_charge"))}
            onChange={(v: number | null) => set("delivery_charge", v === null ? "" : String(v))}
          />
          <NumberInput
            label="무료배송 기준 금액"
            units="원"
            value={num(str(form, "free_ship_over"))}
            onChange={(v: number | null) => set("free_ship_over", v === null ? "" : String(v))}
            description="조건부 무료배송일 때만 씁니다."
          />
        </FormLayout>
        <NumberInput
          label="출고 소요일"
          units="일"
          value={num(str(form, "outbound_days"))}
          onChange={(v: number | null) => set("outbound_days", v === null ? "" : String(v))}
        />
        <TextInput
          label="구매자 안내 문구"
          value={str(form, "extra_info_message")}
          onChange={(v: string) => set("extra_info_message", v)}
          description="예: 각인 문구를 요청사항에 적어 주세요"
        />
      </VStack>
    );
  }
  if (stepId === "s-return") {
    const centers = meta.places.returns.map((p) => ({value: p.code, label: p.name}));
    const mode = str(form, "return_mode") === "direct" ? "direct" : "center";
    return (
      <VStack gap={5} width={760}>
        <RadioList
          label="반품지"
          value={mode}
          onChange={(v: string) => set("return_mode", v)}
        >
          <RadioListItem
            value="center"
            label="등록된 반품지를 쓴다"
            description="쿠팡에 등록해 둔 반품지 중에서 고릅니다."
          />
          <RadioListItem
            value="direct"
            label="주소를 직접 넣는다"
            description="반품지를 등록하지 않았을 때 씁니다."
          />
        </RadioList>
        {mode === "center" ? (
          <Selector
            label="반품지"
            options={centers.length === 0 ? [{value: "", label: "(등록된 반품지가 없습니다)"}] : centers}
            value={str(form, "return_center_code")}
            onChange={(v: string) => set("return_center_code", v)}
          />
        ) : (
          <VStack gap={4}>
            <FormLayout direction="horizontal">
              <TextInput
                label="반품지 이름"
                value={str(form, "return_name")}
                onChange={(v: string) => set("return_name", v)}
                description="예: 본사 반품센터"
              />
              <TextInput
                label="연락처"
                value={str(form, "return_phone")}
                onChange={(v: string) => set("return_phone", v)}
              />
            </FormLayout>
            <FormLayout direction="horizontal">
              <TextInput
                label="우편번호"
                value={str(form, "return_zip")}
                onChange={(v: string) => set("return_zip", v)}
              />
              <TextInput
                label="주소"
                value={str(form, "return_addr")}
                onChange={(v: string) => set("return_addr", v)}
              />
            </FormLayout>
            <TextInput
              label="상세 주소"
              value={str(form, "return_addr_detail")}
              onChange={(v: string) => set("return_addr_detail", v)}
            />
          </VStack>
        )}
        <Divider />
        {/* 기존 화면도 이 자리에 둔다 — 배송·반품 설정을 다음 등록에 재사용하는 이야기다. */}
        <Switch
          label="이 배송·반품 설정을 기본값으로 저장"
          value={remember}
          onChange={onRemember}
          description={
            meta.has_saved_defaults
              ? "저장된 기본값이 있습니다. 켜 두면 지금 값으로 덮어씁니다."
              : "켜 두면 다음 등록부터 이 값이 미리 채워집니다."
          }
        />
        <Divider />
        <FormLayout direction="horizontal">
          <NumberInput
            label="반품 배송비"
            units="원"
            value={num(str(form, "return_charge"))}
            onChange={(v: number | null) => set("return_charge", v === null ? "" : String(v))}
          />
          <NumberInput
            label="초도 배송비"
            units="원"
            value={num(str(form, "delivery_charge_on_return"))}
            onChange={(v: number | null) => set("delivery_charge_on_return", v === null ? "" : String(v))}
          />
        </FormLayout>
      </VStack>
    );
  }
  if (stepId === "s-option") {
    return <OptionStep form={form} set={set} />;
  }
  if (stepId === "s-image") {
    return (
      <VStack gap={4} width={760}>
        <TextInput
          label="대표 이미지 주소"
          isRequired
          value={str(form, "image_url")}
          onChange={(v: string) => set("image_url", v)}
          description="https:// 로 시작하는 이미지 주소입니다. 쿠팡이 이 주소에서 받아갑니다."
        />
        <ImageListField
          label="추가 이미지"
          hint={`최대 ${meta.max_detail_images}장. 한 줄에 한 주소씩 넣으세요.`}
          value={asStrings(form, "detail_images")}
          max={meta.max_detail_images}
          onChange={(list) => set("detail_images", list)}
        />
      </VStack>
    );
  }
  if (stepId === "s-detail") {
    return (
      <VStack gap={4} width={900}>
        <TextArea
          label="상세설명"
          value={str(form, "description_html")}
          onChange={(v: string) => set("description_html", v)}
          rows={14}
          description="HTML 을 그대로 넣습니다. 이미지는 아래 주소 목록에 넣으면 본문 끝에 붙습니다."
        />
        <ImageListField
          label="상세설명 이미지"
          hint="한 줄에 한 주소씩. 본문 아래에 순서대로 붙습니다."
          value={asStrings(form, "content_images")}
          max={20}
          onChange={(list) => set("content_images", list)}
        />
      </VStack>
    );
  }
  if (stepId === "s-keyword") {
    return (
      <VStack gap={4} width={760}>
        <TagListField
          label="검색어"
          hint="구매자가 찾을 말을 쉼표나 줄바꿈으로 구분해 넣습니다. 상품명에 없는 말이 쓸모 있습니다."
          value={asStrings(form, "search_tags")}
          onChange={(list) => set("search_tags", list)}
        />
      </VStack>
    );
  }
  if (stepId === "s-notice") {
    return (
      <VStack gap={4} width={760}>
        <TextInput
          label="고시정보 분류"
          value={str(form, "notice_category")}
          onChange={(v: string) => set("notice_category", v)}
          description="비워 두면 카테고리에 맞는 분류를 쿠팡에서 받아 자동으로 채웁니다."
        />
        <PairsField
          label="고시정보"
          hint="항목과 값. 카테고리를 넣고 '검사' 를 누르면 필요한 항목을 알려 줍니다."
          value={asPairs(form, "notices")}
          onChange={(pairs) => set("notices", fromPairs(pairs))}
        />
      </VStack>
    );
  }
  if (stepId === "s-filter") {
    return (
      <VStack gap={4} width={760}>
        <PairsField
          label="검색필터"
          hint="카테고리가 정한 필터입니다. 항목 이름은 쿠팡이 정한 그대로 넣어야 합니다."
          value={asPairs(form, "filter_attrs")}
          onChange={(pairs) => set("filter_attrs", fromPairs(pairs))}
        />
      </VStack>
    );
  }
  if (stepId === "s-docs") {
    return (
      <VStack gap={4} width={760}>
        <PairsField
          label="구비서류"
          hint="서류 이름과 파일 주소. 카테고리에 따라 필요한 서류가 다릅니다."
          value={asPairs(form, "docs")}
          onChange={(pairs) => set("docs", fromPairs(pairs))}
        />
      </VStack>
    );
  }
  if (stepId === "s-rg") {
    const on = form.rg_enabled === true || str(form, "rg_enabled") === "Y";
    return (
      <VStack gap={4} width={760}>
        <Switch
          label="로켓그로스로 보낸다"
          value={on}
          onChange={(v: boolean) => set("rg_enabled", v)}
          description="쿠팡 물류센터에 입고해 쿠팡이 배송합니다. 끄면 아래 칸은 쓰지 않습니다."
        />
        {!on ? null : (
          <VStack gap={4}>
            <TextInput
              label="입고지 이름"
              value={str(form, "rg_inbound_name")}
              onChange={(v: string) => set("rg_inbound_name", v)}
            />
            <FormLayout direction="horizontal">
              <NumberInput
                label="가로"
                units="mm"
                value={num(str(form, "rg_width"))}
                onChange={(v: number | null) => set("rg_width", v === null ? "" : String(v))}
              />
              <NumberInput
                label="세로"
                units="mm"
                value={num(str(form, "rg_length"))}
                onChange={(v: number | null) => set("rg_length", v === null ? "" : String(v))}
              />
            </FormLayout>
            <FormLayout direction="horizontal">
              <NumberInput
                label="높이"
                units="mm"
                value={num(str(form, "rg_height"))}
                onChange={(v: number | null) => set("rg_height", v === null ? "" : String(v))}
              />
              <NumberInput
                label="무게(포장 포함)"
                units="g"
                value={num(str(form, "rg_weight"))}
                onChange={(v: number | null) => set("rg_weight", v === null ? "" : String(v))}
              />
            </FormLayout>
            <FormLayout direction="horizontal">
              <NumberInput
                label="내용물 무게"
                units="g"
                value={num(str(form, "rg_net_weight"))}
                onChange={(v: number | null) => set("rg_net_weight", v === null ? "" : String(v))}
              />
              <NumberInput
                label="유통기한"
                units="일"
                value={num(str(form, "rg_expiry_days"))}
                onChange={(v: number | null) => set("rg_expiry_days", v === null ? "" : String(v))}
                description="해당 없으면 0"
              />
            </FormLayout>
          </VStack>
        )}
      </VStack>
    );
  }
  if (stepId === "s-confirm") {
    return (
      <VStack gap={4} width={760}>
        <TextInput
          label="WING 아이디"
          value={str(form, "vendor_user_id")}
          onChange={(v: string) => set("vendor_user_id", v)}
          description="쿠팡에 보낼 때 쓰는 판매자 계정 아이디입니다."
        />
        <Card padding={4}>
          <VStack gap={2}>
            <Text weight="bold">보내기 전에</Text>
            <Text size="sm" color="secondary">
              아래 '검사' 로 먼저 확인하세요. 틀린 곳이 있으면 고칠 단계를 알려 줍니다.
              '판매요청' 을 누르면 쿠팡에 바로 판매요청으로 올라갑니다.
            </Text>
          </VStack>
        </Card>
      </VStack>
    );
  }
  // 단계 목록은 서버가 준다. 새 단계가 생기면 여기 없는 id 가 올 수 있다 —
  // 빈 화면을 보여주지 않고 기존 화면으로 보낸다.
  return (
    <Banner status="info" title="이 단계는 기존 화면에서 작성합니다" collapsible={false}>
      <VStack gap={2} align="start">
        <Text size="sm">아직 이 화면에 없는 단계입니다.</Text>
        <Button variant="secondary" as="a" href="/register" label="기존 등록 화면 열기" />
      </VStack>
    </Banner>
  );
}

/** 폼 안의 문자열 목록(JSON_KEYS 의 list). 서버가 list 로 받으므로 배열로 보낸다. */
function asStrings(form: RegisterForm, key: string): string[] {
  const v = form[key];
  return Array.isArray(v) ? v.map((x) => String(x)) : [];
}

/** 폼 안의 dict 를 [이름, 값] 쌍으로. 화면에서는 줄 단위로 고치는 게 편하다. */
function asPairs(form: RegisterForm, key: string): [string, string][] {
  const v = form[key];
  if (v === null || typeof v !== "object" || Array.isArray(v)) return [];
  return Object.entries(v as Record<string, unknown>).map(([k, val]) => [k, String(val ?? "")]);
}

function fromPairs(pairs: [string, string][]): Record<string, string> {
  const out: Record<string, string> = {};
  // 이름이 빈 줄은 버린다 — 서버에 빈 키를 보내면 고시정보 검증이 엉뚱한 말을 한다.
  for (const [k, v] of pairs) if (k.trim() !== "") out[k.trim()] = v;
  return out;
}

interface Option {
  values: Record<string, string>;
  sale_price: string;
  original_price: string;
  stock: string;
  model_no: string;
  barcode: string;
  sku: string;
}

function asOptions(form: RegisterForm): Option[] {
  const v = form.options;
  if (!Array.isArray(v)) return [];
  return v.map((raw) => {
    const o = (raw ?? {}) as Record<string, unknown>;
    const values = o.values;
    return {
      values:
        values !== null && typeof values === "object" && !Array.isArray(values)
          ? Object.fromEntries(
              Object.entries(values as Record<string, unknown>).map(([k, x]) => [k, String(x ?? "")]),
            )
          : {},
      sale_price: String(o.sale_price ?? ""),
      original_price: String(o.original_price ?? ""),
      stock: String(o.stock ?? ""),
      model_no: String(o.model_no ?? ""),
      barcode: String(o.barcode ?? ""),
      sku: String(o.sku ?? ""),
    };
  });
}

/**
 * 옵션 단계. 여기가 가장 큰 단계다 (최대 200줄).
 *
 * 옵션이 2개 이상이면 서버가 '옵션 종류'(색상·사이즈 같은)를 요구한다. 그래서 종류를
 * 먼저 정하고, 줄마다 그 종류의 값을 넣는 순서로 만든다 — 기존 화면과 같은 순서다.
 */
function OptionStep({
  form,
  set,
}: {
  form: RegisterForm;
  set: (key: string, value: unknown) => void;
}) {
  const types = asStrings(form, "option_types");
  const options = asOptions(form);

  const setOption = (i: number, patch: Partial<Option>) => {
    set(
      "options",
      options.map((o, j) => (j === i ? {...o, ...patch} : o)),
    );
  };

  return (
    <VStack gap={5}>
      <TagListField
        label="옵션 종류"
        hint="예: 색상, 사이즈. 옵션이 2개 이상이면 반드시 정해야 합니다. 쉼표나 줄바꿈으로 구분하세요."
        value={types}
        onChange={(list) => set("option_types", list)}
      />
      <Divider />
      <VStack gap={3}>
        <HStack gap={2} align="center" hAlign="between" width="100%">
          <Text weight="bold">옵션 {options.length}개</Text>
          <HStack gap={2}>
            <Button
              variant="secondary"
              size="sm"
              label="옵션 추가"
              isDisabled={options.length >= 200}
              onClick={() =>
                set("options", [
                  ...options,
                  {
                    values: Object.fromEntries(types.map((t) => [t, ""])),
                    sale_price: "",
                    original_price: "",
                    stock: "",
                    model_no: "",
                    barcode: "",
                    sku: "",
                  },
                ])
              }
            />
          </HStack>
        </HStack>
        {options.length === 0 ? (
          <Banner status="info" title="옵션을 하나 이상 넣어야 합니다" collapsible={false}>
            <Text size="sm">
              판매가가 옵션에 들어갑니다. 옵션이 하나면 종류 없이 판매가만 넣어도 됩니다.
            </Text>
          </Banner>
        ) : (
          options.map((o, i) => (
            <Card key={i} padding={4}>
              <VStack gap={3}>
                <HStack gap={2} align="center" hAlign="between" width="100%">
                  <Text size="sm" color="secondary">
                    {i + 1}번째 옵션
                  </Text>
                  <Button
                    variant="ghost"
                    size="sm"
                    label="이 옵션 삭제"
                    onClick={() =>
                      set(
                        "options",
                        options.filter((_, j) => j !== i),
                      )
                    }
                  />
                </HStack>
                {types.length === 0 ? null : (
                  <FormLayout direction="horizontal">
                    {types.map((t) => (
                      <TextInput
                        key={t}
                        label={t}
                        value={o.values[t] ?? ""}
                        onChange={(v: string) =>
                          setOption(i, {values: {...o.values, [t]: v}})
                        }
                      />
                    ))}
                  </FormLayout>
                )}
                <FormLayout direction="horizontal">
                  <NumberInput
                    label="판매가"
                    units="원"
                    value={num(o.sale_price)}
                    onChange={(v: number | null) => setOption(i, {sale_price: v === null ? "" : String(v)})}
                    description="10원 단위로 넣습니다."
                  />
                  <NumberInput
                    label="정상가"
                    units="원"
                    value={num(o.original_price)}
                    onChange={(v: number | null) => setOption(i, {original_price: v === null ? "" : String(v)})}
                    description="할인율 기준입니다. 판매가보다 작을 수 없습니다."
                  />
                </FormLayout>
                <FormLayout direction="horizontal">
                  <NumberInput
                    label="재고"
                    units="개"
                    value={num(o.stock)}
                    onChange={(v: number | null) => setOption(i, {stock: v === null ? "" : String(v)})}
                  />
                  <TextInput
                    label="모델번호"
                    value={o.model_no}
                    onChange={(v: string) => setOption(i, {model_no: v})}
                  />
                </FormLayout>
                <FormLayout direction="horizontal">
                  <TextInput
                    label="바코드"
                    value={o.barcode}
                    onChange={(v: string) => setOption(i, {barcode: v})}
                  />
                  <TextInput
                    label="판매자 상품코드"
                    value={o.sku}
                    onChange={(v: string) => setOption(i, {sku: v})}
                  />
                </FormLayout>
              </VStack>
            </Card>
          ))
        )}
      </VStack>
    </VStack>
  );
}

/**
 * 줄 단위로 고치는 목록. 쉼표·줄바꿈으로 나눈다.
 *
 * 칩 UI 로 만들지 않은 이유: 검색어는 수십 개를 한꺼번에 붙여 넣는 일이 많다.
 * 칩은 하나씩 넣게 만들어서 그 일을 더 번거롭게 한다.
 */
function TagListField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: string[];
  onChange: (list: string[]) => void;
}) {
  const [text, setText] = useState(value.join(", "));
  // 바깥에서 폼이 바뀌면(임시저장 불러오기) 글상자도 따라가야 한다.
  useEffect(() => {
    setText(value.join(", "));
  }, [value]);
  return (
    <VStack gap={2}>
      <TextArea
        label={label}
        value={text}
        onChange={(v: string) => setText(v)}
        onBlur={() => onChange(split(text))}
        rows={3}
        description={hint}
      />
      <Text size="2xs" color="secondary">
        {split(text).length}개
      </Text>
    </VStack>
  );
}

function split(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((x) => x.trim())
    .filter((x) => x !== "");
}

/** 이미지 주소 목록. 장수 제한이 있어 TagListField 와 따로 둔다. */
function ImageListField({
  label,
  hint,
  value,
  max,
  onChange,
}: {
  label: string;
  hint: string;
  value: string[];
  max: number;
  onChange: (list: string[]) => void;
}) {
  const [text, setText] = useState(value.join("\n"));
  useEffect(() => {
    setText(value.join("\n"));
  }, [value]);
  const list = split(text);
  const tooMany = list.length > max;
  return (
    <VStack gap={2}>
      <TextArea
        label={label}
        value={text}
        onChange={(v: string) => setText(v)}
        onBlur={() => onChange(list.slice(0, max))}
        rows={5}
        description={hint}
        status={tooMany ? {type: "error"} : undefined}
      />
      <Text size="2xs" color={tooMany ? "accent" : "secondary"}>
        {list.length} / {max}장
        {tooMany ? ` — 넘는 ${list.length - max}장은 저장할 때 버립니다` : ""}
      </Text>
    </VStack>
  );
}

/** 이름-값 쌍 목록 (고시정보·검색필터·구비서류). 서버는 dict 로 받는다. */
function PairsField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: [string, string][];
  onChange: (pairs: [string, string][]) => void;
}) {
  return (
    <VStack gap={3}>
      <VStack gap={1} align="start">
        <Text weight="bold">{label}</Text>
        <Text size="xsm" color="secondary">
          {hint}
        </Text>
      </VStack>
      {value.map(([k, v], i) => (
        <FormLayout key={i} direction="horizontal">
          <TextInput
            label="항목"
            isLabelHidden={i > 0}
            value={k}
            onChange={(nv: string) =>
              onChange(value.map((pair, j) => (j === i ? [nv, pair[1]] : pair)))
            }
          />
          <TextInput
            label="값"
            isLabelHidden={i > 0}
            value={v}
            onChange={(nv: string) =>
              onChange(value.map((pair, j) => (j === i ? [pair[0], nv] : pair)))
            }
          />
        </FormLayout>
      ))}
      <HStack gap={2}>
        <Button
          variant="secondary"
          size="sm"
          label="줄 추가"
          onClick={() => onChange([...value, ["", ""]])}
        />
        {value.length === 0 ? null : (
          <Button
            variant="ghost"
            size="sm"
            label="마지막 줄 삭제"
            onClick={() => onChange(value.slice(0, -1))}
          />
        )}
      </HStack>
    </VStack>
  );
}
