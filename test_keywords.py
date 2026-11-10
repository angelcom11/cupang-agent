"""실시간 검색어: 메뉴, 1~10위 목록, 내 상품 연관검색어, 실연동 + 모의 데이터 경고, 공급자 실패."""
import app as A
import keywords


def test_mock_trending_is_ranked_1_to_10_and_changes_over_time():
    p = keywords.MockKeywordProvider()
    rows = p.trending(now=1_000_000)
    assert [r["rank"] for r in rows] == list(range(1, 11)) and len({r["keyword"] for r in rows}) == 10
    assert all(r["change"] in ("up", "down", "same", "new") for r in rows)
    assert all((r["delta"] > 0) == (r["change"] in ("up", "down")) for r in rows)
    assert rows == p.trending(now=1_000_000 + 5)                      # 같은 1분 안에서는 같은 순위
    orders = {tuple(r["keyword"] for r in p.trending(now=1_000_000 + 60 * k)) for k in range(30)}
    assert len(orders) > 1                                           # 시간이 지나면 순위가 바뀐다


def test_related_keywords_for_product_names():
    p = keywords.MockKeywordProvider()
    assert "보온보냉 텀블러" in p.related("스테인리스 텀블러 500ml")
    words = p.related("대나무 도마 화이트 2P")                        # 사전에 없는 상품: 이름에서 만든다
    assert words and all(w.startswith("대나무 도마 ") for w in words) and len(words) <= keywords.RELATED_N
    assert p.related("") == []
    assert keywords.search_url("무선 이어폰") == "https://www.coupang.com/np/search?q=%EB%AC%B4%EC%84%A0%20%EC%9D%B4%EC%96%B4%ED%8F%B0"


def test_product_rows_dedupe_and_survive_provider_error():
    class Broken:
        def related(self, name):
            raise RuntimeError("boom")
    items = [{"name": "텀블러", "on_sale": 1, "featured": 0}, {"name": "텀블러", "on_sale": 1, "featured": 0},
             {"name": "랜턴", "on_sale": 0, "featured": 1}]
    rows = keywords.product_rows(keywords.MockKeywordProvider(), items)
    assert [r["name"] for r in rows] == ["텀블러", "랜턴"] and rows[1]["featured"] and not rows[1]["on_sale"]
    assert all(k["url"].startswith(keywords.SEARCH_URL) for r in rows for k in r["keywords"])
    assert [r["keywords"] for r in keywords.product_rows(Broken(), items)] == [[], []]


def test_keywords_page_menu_and_api():
    A.sync.run_once()
    c = A.app.test_client()
    html = c.get("/keywords").get_data(as_text=True)
    assert 'href="/keywords" class="on"' in html and "실시간 검색어" in html
    assert html.split('id="kw-body"')[1].split("</tbody>")[0].count("<tr") == 10
    names = {i["name"] for i in A.store.items()}
    assert names and all(n in html for n in names)
    assert "모의 데이터" in html and 'class="flash danger">⚠' not in html      # 모의 모드: 안내만, 경고 줄은 없음
    assert 'href="/keywords" class=""' in c.get("/").get_data(as_text=True)     # 다른 화면에도 메뉴가 있다
    d = c.get("/api/keywords").get_json()
    assert [r["rank"] for r in d["trending"]] == list(range(1, 11)) and d["mock"] and not d["mock_on_live"]
    assert {p["name"] for p in d["products"]} == names and all(p["keywords"] for p in d["products"])


def test_warns_when_live_shop_but_mock_keywords(monkeypatch):
    monkeypatch.setattr(A.client, "mode", "live", raising=False)
    html = A.app.test_client().get("/keywords").get_data(as_text=True)
    assert 'class="flash danger">⚠' in html and "모의(가짜) 데이터" in html


def test_page_still_renders_when_trending_fails(monkeypatch):
    def boom():
        raise RuntimeError("시간 초과")
    monkeypatch.setattr(A.keyword_provider, "trending", boom)
    r = A.app.test_client().get("/keywords")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "검색어 순위를 불러오지 못했습니다: 시간 초과" in html and "검색어 순위가 없습니다" in html
    assert A.app.test_client().get("/api/keywords").get_json()["trending"] == []
