/**
 * 설정 — 기존 Jinja 화면(templates/settings.html)의 네 블록을 옮겼다:
 * API 키 · 자동화 · 화면 모드 · 텔레그램 알림.
 *
 * 로그인 화면 꾸미기(레이아웃·문구)는 아직 기존 화면에만 있다. 쓰는 일이 드물고
 * login_page.from_form 의 검증을 그대로 옮겨야 해서, 반쯤 옮기지 않고 링크로 보낸다.
 *
 * 비밀값은 서버가 내보내지 않는다. Secret Key 와 봇 토큰은 "저장됨" 표시만 보이고,
 * 빈 칸으로 저장하면 서버가 기존 값을 그대로 둔다.
 */
import {useEffect, useState} from "react";
import {VStack, HStack, StackItem} from "@astryxdesign/core/Stack";
import {Section} from "@astryxdesign/core/Section";
import {Card} from "@astryxdesign/core/Card";
import {Text, Heading} from "@astryxdesign/core/Text";
import {Badge} from "@astryxdesign/core/Badge";
import {Switch} from "@astryxdesign/core/Switch";
import {TextInput} from "@astryxdesign/core/TextInput";
import {NumberInput} from "@astryxdesign/core/NumberInput";
import {Button} from "@astryxdesign/core/Button";
import {Banner} from "@astryxdesign/core/Banner";
import {Divider} from "@astryxdesign/core/Divider";
import {EmptyState} from "@astryxdesign/core/EmptyState";
import {Spinner} from "@astryxdesign/core/Spinner";
import {Link} from "@astryxdesign/core/Link";
import {Token} from "@astryxdesign/core/Token";
import {RadioList, RadioListItem} from "@astryxdesign/core/RadioList";
import {CheckboxList, CheckboxListItem} from "@astryxdesign/core/CheckboxList";
import {
  AuthError,
  fetchSettings,
  settingsKeys,
  settingsRules,
  settingsTelegram,
  settingsTheme,
} from "../api";
import type {SettingsData, TelegramChat} from "../api";
import {setThemeMode} from "../theme-mode";
import type {ThemeMode} from "../theme-mode";

/** 글상자 한 가지 폭. 키·토큰·주소가 다 들어간다. */
const FIELD = 480;

interface Notice {
  status: "success" | "error";
  title: string;
  description?: string;
}

/** 설정 한 묶음. 제목과 설명을 같은 모양으로 두어 화면이 흩어지지 않게 한다. */
function Block({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Card padding={5}>
      <VStack gap={4} hAlign="start">
        <VStack gap={1} hAlign="start">
          <Heading level={2}>{title}</Heading>
          {description !== undefined ? (
            <Text size="sm" color="secondary">
              {description}
            </Text>
          ) : null}
        </VStack>
        {children}
      </VStack>
    </Card>
  );
}

export default function Settings() {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  // 입력 중인 값. 저장 전까지만 들고 있는다.
  const [accessKey, setAccessKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [vendorId, setVendorId] = useState("");
  const [interval, setIntervalSec] = useState<number | null>(30);
  const [threshold, setThreshold] = useState<number | null>(0);
  const [autoSoldout, setAutoSoldout] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [token, setToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [tgEnabled, setTgEnabled] = useState(false);
  const [topics, setTopics] = useState<string[]>([]);
  const [frequency, setFrequency] = useState("realtime");
  const [sendFrom, setSendFrom] = useState("00:00");
  const [sendTo, setSendTo] = useState("00:00");
  const [outside, setOutside] = useState<"hold" | "drop">("hold");
  const [chats, setChats] = useState<TelegramChat[] | null>(null);

  const fill = (d: SettingsData) => {
    setData(d);
    setAccessKey(d.keys.access_key);
    setVendorId(d.keys.vendor_id);
    setSecretKey(""); // 비밀키는 다시 채우지 않는다
    setIntervalSec(d.rules.sync_interval_sec);
    setThreshold(d.rules.soldout_threshold);
    setAutoSoldout(d.rules.auto_soldout);
    setBaseUrl(d.rules.public_base_url);
    setToken("");
    setChatId(d.telegram.chat_id);
    setTgEnabled(d.telegram.enabled);
    setTopics(d.telegram.topics);
    setFrequency(d.telegram.frequency);
    setSendFrom(d.telegram.send_from);
    setSendTo(d.telegram.send_to);
    setOutside(d.telegram.outside);
  };

  const onFail = (e: unknown) => {
    if (e instanceof AuthError) {
      location.href = "/login";
      return;
    }
    setNotice({status: "error", title: "실패했습니다", description: e instanceof Error ? e.message : String(e)});
  };

  const reload = async () => {
    fill(await fetchSettings());
  };

  useEffect(() => {
    let alive = true;
    fetchSettings()
      .then((d) => {
        if (alive) fill(d);
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

  if (loadError !== null) {
    return (
      <Section padding={6}>
        <EmptyState title="설정을 불러오지 못했습니다" description={loadError} />
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

  const keyPayload = {access_key: accessKey, secret_key: secretKey, vendor_id: vendorId};

  return (
    <Section padding={6}>
      {/* 카드를 화면 끝까지 늘리면 오른쪽이 텅 빈다. 읽기 좋은 폭으로 묶는다. */}
      <VStack gap={5} width={820}>
        <HStack gap={3} vAlign="center" wrap="wrap">
          <StackItem size="fill">
            <Heading level={1}>설정</Heading>
          </StackItem>
          <Badge
            variant={data.keys.mode === "live" ? "success" : "neutral"}
            label={data.keys.mode === "live" ? "실연동 모드" : "모의 모드"}
          />
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

        {/* 실거래 모드인데 경쟁가만 모의면 가격 판단을 하면 안 된다 */}
        {data.mock_competitor_live ? (
          <Banner
            status="warning"
            title="경쟁가가 모의 데이터입니다"
            description="실연동 모드지만 경쟁가 수집은 모의 상태입니다. 자동 가격조정은 이 상태에서 가격을 바꾸지 않습니다."
          />
        ) : null}

        <Block
          title="쿠팡 API 키"
          description={`지금 ${data.keys.mode === "live" ? "실연동" : "모의"} 모드입니다. 실연동으로 쓰려면 세 가지가 모두 필요합니다. 저장한 뒤 '연결 확인'으로 점검하세요.`}
        >
          <VStack gap={3} hAlign="start">
            <VStack width={FIELD}>
              <TextInput label="Access Key" value={accessKey} onChange={setAccessKey} />
            </VStack>
            <VStack width={FIELD}>
              <TextInput
                label="Secret Key"
                type="password"
                value={secretKey}
                onChange={setSecretKey}
                // 서버가 비밀키를 내보내지 않는다. 비워 두면 기존 값이 그대로 남는다.
                description={
                  data.keys.has_secret_key
                    ? "저장되어 있습니다. 비워 두면 그대로 둡니다."
                    : "아직 저장된 키가 없습니다."
                }
              />
            </VStack>
            <VStack width={FIELD}>
              <TextInput label="업체코드 (vendor id)" value={vendorId} onChange={setVendorId} />
            </VStack>
            {/* 버튼이 입력칸에 붙으면 그 칸의 일부처럼 보인다. 한 칸 띄운다. */}
            <HStack gap={3} wrap="wrap" hAlign="between" paddingBlockStart={2} width="100%">
              {/* 빈 StackItem 은 늘어나지 않는다. 저장 묶음을 담아야 삭제가 끝으로 밀린다. */}
              <StackItem size="fill">
                <HStack gap={3} wrap="wrap">
              <Button
                label="저장"
                clickAction={async () => {
                  try {
                    const {message} = await settingsKeys("save", keyPayload);
                    setNotice({status: "success", title: message});
                    await reload();
                  } catch (e) {
                    onFail(e);
                  }
                }}
              />
              <Button
                label="연결 확인"
                variant="ghost"
                clickAction={async () => {
                  try {
                    const {message} = await settingsKeys("test", keyPayload);
                    setNotice({status: "success", title: message});
                  } catch (e) {
                    onFail(e);
                  }
                }}
              />
                </HStack>
              </StackItem>
              {/* 되돌릴 수 없는 동작은 저장 옆에 붙이지 않는다 */}
              <Button
                label="키 삭제"
                variant="destructive"
                isDisabled={!data.keys.has_secret_key}
                clickAction={async () => {
                  try {
                    const {message} = await settingsKeys("clear", {});
                    setNotice({status: "success", title: message});
                    await reload();
                  } catch (e) {
                    onFail(e);
                  }
                }}
              />
            </HStack>
          </VStack>
        </Block>

        <Block title="자동화" description="쿠팡을 얼마나 자주 확인할지, 재고가 얼마나 남으면 알릴지 정합니다.">
          <VStack gap={3} hAlign="start">
            <HStack gap={4} wrap="wrap" vAlign="end">
              {/* 한쪽에만 설명을 달면 입력칸 높이가 어긋난다. 단위는 units 로 넣는다. */}
              <NumberInput
                label="확인 주기"
                units="초"
                min={5}
                width={140}
                value={interval}
                onChange={setIntervalSec}
              />
              <NumberInput
                label="재고 부족 기준"
                units="개"
                min={0}
                width={140}
                value={threshold}
                onChange={setThreshold}
              />
            </HStack>
            <Switch
              label="재고가 기준 이하로 떨어지면 자동으로 판매중지"
              value={autoSoldout}
              onChange={setAutoSoldout}
              description="다시 입고되어 기준을 넘으면 판매를 자동으로 재개합니다"
            />
            <VStack width={FIELD}>
              <TextInput
                label="이미지 공개 주소"
                value={baseUrl}
                onChange={setBaseUrl}
                placeholder="예: https://내도메인.com"
                description="상품 등록 때 쿠팡이 이미지를 받아갈 주소입니다. http:// 또는 https:// 로 시작해야 합니다."
              />
            </VStack>
            <HStack paddingBlockStart={2}>
              <Button
                label="자동화 설정 저장"
              clickAction={async () => {
                try {
                  const {message} = await settingsRules({
                    sync_interval_sec: interval ?? 30,
                    soldout_threshold: threshold ?? 0,
                    auto_soldout: autoSoldout,
                    public_base_url: baseUrl,
                  });
                    setNotice({status: "success", title: message});
                    await reload();
                  } catch (e) {
                    onFail(e);
                  }
                }}
              />
            </HStack>
          </VStack>
        </Block>

        <Block title="화면 모드">
          <VStack gap={3} hAlign="start">
            <RadioList
              label="화면 모드"
              isLabelHidden
              orientation="horizontal"
              value={data.theme}
              onChange={(v) => {
                void (async () => {
                  try {
                    const {message} = await settingsTheme(v);
                    setThemeMode(v as ThemeMode);  // 새 화면도 바로 바뀐다
                    setNotice({status: "success", title: message});
                    await reload();
                  } catch (e) {
                    onFail(e);
                  }
                })();
              }}
            >
              {data.themes.map((t) => (
                <RadioListItem key={t.id} value={t.id} label={t.label} />
              ))}
            </RadioList>
            <Text size="sm" color="secondary">
              고르면 바로 저장됩니다.
            </Text>
          </VStack>
        </Block>

        <Block
          title="텔레그램 알림"
          description="재고·가격 변동을 텔레그램으로 받습니다. 봇 토큰은 BotFather 에서 받습니다."
        >
          <VStack gap={4} hAlign="start">
            <VStack width={FIELD}>
              <TextInput
                label="봇 토큰"
                type="password"
                value={token}
                onChange={setToken}
                description={
                  data.telegram.has_token
                    ? "저장되어 있습니다. 비워 두면 그대로 둡니다."
                    : "아직 저장된 토큰이 없습니다."
                }
              />
            </VStack>

            <HStack gap={3} vAlign="end" wrap="wrap">
              <VStack width={260}>
                <TextInput
                  label="대화 ID (chat id)"
                  value={chatId}
                  onChange={setChatId}
                  description="모르면 '대화 찾기' 를 누르세요"
                />
              </VStack>
              <Button
                label="대화 찾기"
                variant="secondary"
                clickAction={async () => {
                  try {
                    const res = await settingsTelegram("find_chat", {token, chat_id: chatId});
                    setChats(res.chats);
                    setNotice({status: "success", title: res.message});
                    // 서버가 첫 대화를 chat_id 로 넣어 두므로 화면도 맞춘다
                    await reload();
                  } catch (e) {
                    onFail(e);
                  }
                }}
              />
            </HStack>

            {chats !== null && chats.length > 0 ? (
              <VStack gap={2} hAlign="start">
                <Text size="sm" color="secondary">
                  찾은 대화 — 누르면 대화 ID 로 넣습니다
                </Text>
                <HStack gap={2} wrap="wrap">
                  {chats.map((c) => (
                    <Token
                      key={c.id}
                      label={`${c.title} (${c.id})`}
                      size="sm"
                      color={c.id === chatId ? "blue" : "gray"}
                      onClick={() => setChatId(c.id)}
                    />
                  ))}
                </HStack>
              </VStack>
            ) : null}

            <Divider />

            <CheckboxList
              label="받을 알림"
              value={topics}
              onChange={setTopics}
            >
              {data.topics.map((t) => (
                <CheckboxListItem key={t.id} value={t.id} label={t.label} />
              ))}
            </CheckboxList>

            <RadioList label="보내는 방식" orientation="horizontal" value={frequency} onChange={setFrequency}>
              {data.frequencies.map((f) => (
                <RadioListItem key={f.id} value={f.id} label={f.label} />
              ))}
            </RadioList>

            <HStack gap={3} vAlign="start" wrap="wrap">
              <VStack width={140}>
                <TextInput label="보낼 시작 시각" value={sendFrom} onChange={setSendFrom} placeholder="00:00" />
              </VStack>
              <VStack width={140}>
                <TextInput label="보낼 끝 시각" value={sendTo} onChange={setSendTo} placeholder="00:00" />
              </VStack>
              <Text size="sm" color="secondary">
                시작과 끝이 같으면 하루 종일 보냅니다
              </Text>
            </HStack>

            <RadioList
              label="시간대 밖에 생긴 알림"
              orientation="horizontal"
              value={outside}
              onChange={(v) => setOutside(v === "drop" ? "drop" : "hold")}
            >
              <RadioListItem value="hold" label="모아 두고 시간대가 되면 보내기" />
              <RadioListItem value="drop" label="버리기" />
            </RadioList>

            <Switch
              label="알림 켜기"
              value={tgEnabled}
              onChange={setTgEnabled}
              description="끄면 설정은 남고 보내지 않습니다"
            />

            {data.telegram.pending > 0 ? (
              <Text size="sm" color="secondary">
                보내기를 기다리는 알림 {data.telegram.pending}건 · 지금은{" "}
                {data.telegram.window_open ? "보낼 수 있는 시간대" : "시간대 밖"}
              </Text>
            ) : null}
            {data.telegram.last_result !== null ? (
              <Text size="sm" color="secondary">
                마지막 결과: {data.telegram.last_result}
              </Text>
            ) : null}

            <HStack gap={3} wrap="wrap">
              <Button
                label="저장"
                clickAction={async () => {
                  try {
                    const res = await settingsTelegram("save", {
                      token, chat_id: chatId, enabled: tgEnabled, topics,
                      frequency, send_from: sendFrom, send_to: sendTo, outside,
                    });
                    setNotice({status: "success", title: res.message});
                    await reload();
                  } catch (e) {
                    onFail(e);
                  }
                }}
              />
              <Button
                label="테스트 보내기"
                variant="secondary"
                clickAction={async () => {
                  try {
                    const res = await settingsTelegram("test", {
                      token, chat_id: chatId, enabled: tgEnabled, topics,
                      frequency, send_from: sendFrom, send_to: sendTo, outside,
                    });
                    setNotice({status: "success", title: res.message});
                    await reload();
                  } catch (e) {
                    onFail(e);
                  }
                }}
              />
              <Button
                label="연결 해제"
                variant="destructive"
                isDisabled={!data.telegram.has_token}
                clickAction={async () => {
                  try {
                    const res = await settingsTelegram("clear", {});
                    setNotice({status: "success", title: res.message});
                    setChats(null);
                    await reload();
                  } catch (e) {
                    onFail(e);
                  }
                }}
              />
            </HStack>
          </VStack>
        </Block>

        <Block title="카테고리" description="상품 등록에 쓰는 쿠팡 카테고리 목록입니다.">
          <HStack gap={3} vAlign="center" wrap="wrap">
            <Text size="sm">
              {data.categories.count.toLocaleString("ko-KR")}개 (등록 가능한 최하위{" "}
              {data.categories.leaves.toLocaleString("ko-KR")}개)
            </Text>
            <Badge
              variant={data.categories.full ? "success" : "warning"}
              label={data.categories.full ? "전체" : "표본"}
            />
            {!data.categories.full ? (
              <Text size="sm" color="secondary">
                기존 설정 화면에서 전체 목록을 불러올 수 있습니다
              </Text>
            ) : null}
          </HStack>
        </Block>

        <Block
          title="로그인 화면 꾸미기"
          description="레이아웃과 문구는 아직 기존 설정 화면에만 있습니다."
        >
          <Link href="/settings#login-page" label="기존 설정 화면에서 열기">
            기존 설정 화면에서 열기
          </Link>
        </Block>
      </VStack>
    </Section>
  );
}
