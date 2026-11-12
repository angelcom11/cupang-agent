"""실시간 검색어 화면(내 상품 연관검색어): 출처별(구글·네이버·다음·쿠팡) 파싱, 캐시, 차단 처리, 화면·API.

네이버·다음·구글 응답은 2026-11-10 에 직접 호출해서 받은 모양 그대로다. 쿠팡은 서버에서 403 이라 응답 모양을 확인하지 못했다 —
그래서 쿠팡은 '차단 알림'과 '모양을 모를 때의 관대한 해석'만 시험한다 (실제 응답에서 맞는지는 시험하지 않았다).
테스트는 인터넷에 묻지 않는다 (conftest: WING_KEYWORDS=mock, 실제 공급자는 가짜 get 을 받는다)."""
import json

import pytest
import requests

import app as A
import keywords

NAVER = '{"query":["텀블러"],"answer":[],"intend":[],"items":[[["텀블러","0"],["스텐텀블러","0"],["텀블러탈퇴","0"],["보온보냉텀블러","0"]]]}'
DAUM = '{"q":"텀블러","subkeys":["텀블러","텀블러 세척방법","텀블러 추천","스타벅스 텀블러"],"highlighted":[]}'
GOOGLE = '["텀블러",["텀블러","텀블러 세척법","텀블러 추천","텀블러 브랜드"],[],{}]'


class Resp:
    def __init__(self, body="", status=200):
        self.content, self.status_code = body.encode("utf-8"), status


class Net:
    """가짜 requests.get: 주소(호스트)로 응답을 고르고, 부른 횟수와 머리글을 기록한다."""

    def __init__(self, **by_host):
        self.by_host, self.calls = by_host, []

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        for host, resp in self.by_host.items():
            if host in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp() if callable(resp) else resp
        raise AssertionError("예상하지 못한 주소: " + url)

    def count(self, host):
        return sum(host in c[0] for c in self.calls)


def live(**by_host):
    net = Net(**by_host)
    return keywords.LiveKeywordProvider(get=net), net


# ---------- 연관검색어 (자동완성) ----------
def test_related_parses_naver_daum_google_and_drops_the_query_itself():
    assert keywords.base_keyword("스테인리스 텀블러 500ml") == "스테인리스 텀블러"
    # 검색어와 같은 항목(공백·대소문자 무시)은 빼고, 최대 8개
    assert live(naver=Resp(NAVER))[0].related("텀블러 500ml", "naver") == ["스텐텀블러", "텀블러탈퇴", "보온보냉텀블러"]
    assert live(daum=Resp(DAUM))[0].related("텀블러", "daum") == ["텀블러 세척방법", "텀블러 추천", "스타벅스 텀블러"]
    assert live(google=Resp(GOOGLE))[0].related("텀블러", "google") == ["텀블러 세척법", "텀블러 추천", "텀블러 브랜드"]
    many = json.dumps(["텀블러", [f"텀블러 {i}" for i in range(20)], [], {}], ensure_ascii=False)
    assert len(live(google=Resp(many))[0].related("텀블러", "google")) == keywords.RELATED_N


def test_requests_send_only_the_base_keyword_with_an_honest_user_agent():
    p, net = live(naver=Resp(NAVER))
    p.related("스테인리스 텀블러 500ml 화이트", "naver")
    url, params, headers = net.calls[0]
    assert params["q"] == "스테인리스 텀블러"                       # 상품 이름 전체·색·용량은 나가지 않는다
    assert headers["User-Agent"] == keywords.USER_AGENT and "Mozilla" not in headers["User-Agent"]


def test_related_is_cached_and_a_blocked_source_is_not_hammered():
    p, net = live(naver=Resp(NAVER))
    p.related("텀블러 500ml", "naver"); p.related("텀블러 500ml", "naver")
    assert net.count("naver") == 1
    blocked, bnet = live(coupang=Resp("Access Denied", 403))
    with pytest.raises(keywords.SourceError, match="HTTP 403"):
        blocked.related("텀블러", "coupang")
    with pytest.raises(keywords.SourceError, match="HTTP 403"):
        blocked.related("랜턴", "coupang")                        # 다른 상품도 다시 두드리지 않고 같은 이유를 낸다
    assert bnet.count("coupang") == 1


def test_a_timeout_on_one_product_does_not_shut_the_whole_source():
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append(params["q"])
        if params["q"] == "블루투스 이어폰":
            raise requests.ReadTimeout("느림")
        return Resp(DAUM)
    p = keywords.LiveKeywordProvider(get=get)
    with pytest.raises(keywords.SourceError, match="연결하지 못했습니다"):
        p.related("무선 블루투스 이어폰", "daum")
    assert p.related("스테인리스 텀블러", "daum")                    # 다른 상품은 정상 조회 (출처 전체는 막히지 않음)
    with pytest.raises(keywords.SourceError, match="연결하지 못했습니다"):
        p.related("무선 블루투스 이어폰", "daum")                    # 같은 상품의 실패는 잠깐 기억해 다시 두드리지 않는다
    assert calls.count("블루투스 이어폰") == 1


def test_network_errors_and_bad_payloads_become_source_errors():
    p, _ = live(naver=requests.ConnectTimeout("t"))
    with pytest.raises(keywords.SourceError, match="연결하지 못했습니다"):
        p.related("텀블러", "naver")
    p, _ = live(daum=Resp("<html>404</html>"))
    with pytest.raises(keywords.SourceError, match="해석하지 못했습니다"):
        p.related("텀블러", "daum")
    p, _ = live(google=Resp("x", 500))
    with pytest.raises(keywords.SourceError, match="HTTP 500"):
        p.related("텀블러", "google")
    with pytest.raises(keywords.SourceError):
        live()[0].related("텀블러", "bing")
    assert live()[0].related("", "naver") == []


def test_coupang_tolerant_parse_and_unknown_shape():   # 응답 모양은 가정이다 (서버에서 403 이라 확인 못 함)
    ok, _ = live(coupang=Resp(json.dumps({"keyword": "텀블러", "list": [{"keyword": "텀블러 500ml"}, {"keyword": "텀블러 세트"}]}, ensure_ascii=False)))
    assert ok.related("텀블러", "coupang") == ["텀블러 500ml", "텀블러 세트"]
    odd, _ = live(coupang=Resp('{"a": 1}'))
    with pytest.raises(keywords.SourceError, match="찾지 못했습니다"):
        odd.related("텀블러", "coupang")


def test_no_ranking_api_is_left():
    """순위 화면은 없앴다: 공급자·화면 어디에도 trending 이 남아 있지 않다."""
    for provider in (keywords.LiveKeywordProvider(get=Net()), keywords.MockKeywordProvider()):
        assert not hasattr(provider, "trending")
    assert not hasattr(keywords, "trending_rows") and not hasattr(keywords, "TREND_NOTE")


# ---------- 상품별 연관검색어 ----------
def test_product_rows_dedupe_isolate_failures_and_report_common_error():
    items = [{"name": "스테인리스 텀블러 500ml", "on_sale": 1, "featured": 0}, {"name": "스테인리스 텀블러 500ml", "on_sale": 1, "featured": 0},
             {"name": "캠핑용 LED 랜턴", "on_sale": 0, "featured": 1}]
    p = keywords.MockKeywordProvider()
    rows, err = keywords.product_rows(p, items, "naver")
    assert [r["name"] for r in rows] == ["스테인리스 텀블러 500ml", "캠핑용 LED 랜턴"] and err is None
    assert rows[1]["featured"] and not rows[1]["on_sale"] and rows[0]["query"] == "스테인리스 텀블러"
    assert all(k["url"].startswith("https://search.naver.com/") for r in rows for k in r["keywords"])

    class Half:
        name = "x"
        query = staticmethod(keywords.base_keyword)

        def related(self, name, source):
            if "랜턴" in name:
                raise RuntimeError("boom")
            return ["a"]
    rows, err = keywords.product_rows(Half(), items, "daum")
    assert rows[0]["keywords"] and rows[1]["error"] and rows[1]["keywords"] == [] and err is None

    blocked, _ = live(coupang=Resp("no", 403))
    rows, err = keywords.product_rows(blocked, items, "coupang")
    assert err and "403" in err and all(r["keywords"] == [] and r["error"] for r in rows)


# ---------- 화면 · API ----------
def test_page_has_menu_and_four_source_tabs_and_no_ranking():
    c = A.app.test_client()
    html = c.get("/keywords").get_data(as_text=True)
    assert 'href="/keywords" class="on"' in html and "내 상품 연관검색어" in html
    for sid, label in (("google", "구글"), ("naver", "네이버"), ("daum", "다음"), ("coupang", "쿠팡")):
        assert f'data-src="{sid}"' in html and label in html
    assert html.index('data-src="google"') < html.index('data-src="coupang"')   # 실제로 나오는 구글이 맨 앞
    assert 'id="kw-table"' not in html and "1위" not in html and "LIVE" not in html   # 순위 칸·자동 갱신 표시는 없다
    assert 'href="/keywords" class=""' in c.get("/").get_data(as_text=True)         # 다른 화면에도 메뉴가 있다
    assert "모의(가짜) 검색어를 보여 주는 중" in html                              # 테스트는 모의 공급자


def test_api_with_live_provider_per_source(monkeypatch):
    A.sync.run_once()
    net = Net(**{"google.com/complete": Resp(GOOGLE), "naver": Resp(NAVER), "daum": Resp(DAUM), "coupang": Resp("Access Denied", 403)})
    monkeypatch.setattr(A, "keyword_provider", keywords.LiveKeywordProvider(get=net))
    c = A.app.test_client()
    names = {i["name"] for i in A.store.items()}
    for src, host in (("google", "https://www.google.com/"), ("naver", "https://search.naver.com/"), ("daum", "https://search.daum.net/")):
        d = c.get(f"/api/keywords?source={src}").get_json()
        assert d["source"] == src and not d["mock"] and d["related_error"] is None
        assert "trending" not in d and "trend_note" not in d
        assert {p["name"] for p in d["products"]} == names and all(p["keywords"] for p in d["products"])
        assert all(k["url"].startswith(host) for p in d["products"] for k in p["keywords"])
    k = c.get("/api/keywords?source=coupang").get_json()             # 쿠팡: 자동완성 접속 거부
    assert "403" in k["related_error"] and all(p["keywords"] == [] and p["error"] for p in k["products"])
    assert net.count("coupang") == 1                                 # 막힌 출처는 상품마다 다시 두드리지 않는다
    assert c.get("/api/keywords?source=nope").get_json()["source"] == "google"   # 모르는 출처는 기본(구글)


def test_page_still_works_when_a_source_breaks(monkeypatch):
    A.sync.run_once()
    monkeypatch.setattr(A, "keyword_provider", keywords.LiveKeywordProvider(get=Net(**{"google.com/complete": requests.ConnectTimeout("t")})))
    c = A.app.test_client()
    assert c.get("/keywords").status_code == 200
    d = c.get("/api/keywords?source=google").get_json()
    assert "연결하지 못했습니다" in d["related_error"] and d["products"] and all(p["keywords"] == [] for p in d["products"])


def test_mock_provider_gives_related_words_for_every_source():
    p = keywords.MockKeywordProvider()
    words = p.related("대나무 도마 화이트 2P", "naver")
    assert words and all(w.startswith("대나무 도마 ") for w in words) and len(words) <= keywords.RELATED_N
    assert words == p.related("대나무 도마 화이트 2P", "coupang") and p.related("", "google") == []


# ---------- 등록 화면 검색어 추천 ----------
COUPANG_SUG = '{"keyword":"텀블러","autoComplete":[{"keyword":"텀블러 추천"},{"keyword":"쿠팡 텀블러"}]}'


def test_suggest_merges_sources_and_ranks_by_how_many_sources_agree():
    """여러 출처에 함께 나온 검색어가 위로. 같으면 자동완성 상위가 앞선다."""
    p, _ = live(naver=Resp(NAVER), daum=Resp(DAUM), google=Resp(GOOGLE), coupang=Resp(COUPANG_SUG))
    out, errors = keywords.suggest_tags(p, "텀블러")
    assert errors == {}
    words = [s["keyword"] for s in out]
    # '텀블러 추천'은 다음·구글·쿠팡 세 곳에 나온다 → 1등
    assert words[0] == "텀블러 추천"
    assert sorted(out[0]["sources"]) == sorted(["다음", "구글", "쿠팡"])
    # 한 곳에서만 나온 말도 빠지지 않는다
    assert "스텐텀블러" in words and "스타벅스 텀블러" in words


def test_suggest_drops_the_query_itself_and_what_is_already_chosen():
    p, _ = live(google=Resp(GOOGLE))
    out, _ = keywords.suggest_tags(p, "텀블러", sources=["google"])
    assert "텀블러" not in [s["keyword"] for s in out]                 # 상품명으로 이미 검색된다
    # 이미 넣어 둔 검색어는 띄어쓰기·대소문자만 달라도 다시 추천하지 않는다
    out2, _ = keywords.suggest_tags(p, "텀블러", sources=["google"], exclude=["텀블러추천"])
    assert "텀블러 추천" not in [s["keyword"] for s in out2]


def test_suggest_never_exceeds_the_twenty_tag_limit():
    many = json.dumps(["텀블러", [f"텀블러 {i}" for i in range(40)], [], {}], ensure_ascii=False)
    p, _ = live(google=Resp(many))
    assert keywords.MAX_TAGS == 20
    assert len(keywords.suggest_tags(p, "텀블러", sources=["google"])[0]) <= keywords.MAX_TAGS
    assert keywords.suggest_tags(p, "텀블러", sources=["google"], limit=0)[0] == []


def test_suggest_keeps_working_when_one_source_fails():
    p, _ = live(google=Resp(GOOGLE), naver=Resp("", 503), daum=Resp(DAUM), coupang=Resp(COUPANG_SUG))
    out, errors = keywords.suggest_tags(p, "텀블러")
    assert out, "한 출처가 죽어도 나머지 추천은 나와야 한다"
    assert "네이버" in errors and "구글" not in errors


def test_suggest_api_reports_room_left_and_refuses_an_empty_name(monkeypatch):
    c = A.app.test_client()
    assert c.get("/api/keyword-suggest?name=").status_code == 400
    p, _ = live(google=Resp(GOOGLE), naver=Resp(NAVER), daum=Resp(DAUM), coupang=Resp(COUPANG_SUG))
    monkeypatch.setattr(A, "keyword_provider", p)
    data = c.get("/api/keyword-suggest?name=텀블러 500ml&exclude=가,나").get_json()
    assert data["query"] == "텀블러" and data["limit"] == 20
    assert data["room"] == 18 and len(data["suggestions"]) <= 18   # 이미 쓴 2개만큼 적게 추천한다
    assert all(s["keyword"] not in ("가", "나") for s in data["suggestions"])


def test_register_page_offers_the_suggest_button():
    page = A.app.test_client().get("/register").get_data(as_text=True)
    assert 'id="sug-go"' in page and 'id="sug-list"' in page
    assert "/api/keyword-suggest" in A.app.test_client().get("/static/register.js").get_data(as_text=True)


def test_suggest_reads_the_product_name_field_that_the_form_actually_has():
    """추천은 노출상품명 칸을 읽는다. 칸 이름이 바뀌면 추천이 조용히 멎으므로 여기서 잡는다."""
    page = A.app.test_client().get("/register").get_data(as_text=True)
    js = A.app.test_client().get("/static/register.js").get_data(as_text=True)
    assert 'name="display_name"' in page          # JS 가 f.display_name 으로 읽는 칸
    assert "f?.display_name?.value" in js
    assert "document.forms[0]" not in js          # form 이 여럿이고 id 도 중복이라 쓰면 안 된다
