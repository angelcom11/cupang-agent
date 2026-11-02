"""등록 이력: 쿠팡 '상품 상태변경이력'을 읽어 승인·반려 상태와 반려 사유를 표시."""
import app as A
import reg_status


class FakeClient:
    mode = "live"

    def __init__(self):
        self.calls = []

    def get_status_history(self, spid, max_items=50):
        self.calls.append(spid)
        if spid == "999":
            raise RuntimeError("404: 상품을 찾을 수 없습니다")
        rows = [{"createdAt": "2026-11-02T10:00:00", "status": "임시저장", "createdBy": "판매자", "comment": "판매자 임시저장"},
                {"createdAt": "2026-11-02T10:01:00", "status": "승인요청", "createdBy": "판매자", "comment": "판매자 승인요청"}]
        if spid == "111":
            rows.append({"createdAt": "2026-11-02T11:00:00", "status": "승인반려", "createdBy": "박**",
                         "comment": "대표이미지 기준 위반: 흰 배경이 아닙니다"})
        else:
            rows.append({"createdAt": "2026-11-02T11:00:00", "status": "승인완료", "createdBy": "쿠팡 셀러 시스템",
                         "comment": "승인완료 - Items 생성 완료"})
        return rows[::-1]


def test_summarize_picks_latest_and_reject_reason():
    s = reg_status.summarize(FakeClient().get_status_history("111"))
    assert s["status"] == "승인반려" and "흰 배경" in s["reason"] and s["at"] == "2026-11-02 11:00:00"
    assert reg_status.summarize(FakeClient().get_status_history("222"))["reason"] == ""
    real = [{"statusName": "승인반려", "comment": "[free 블랙]: 도서산간배송 출고지에 등록된 택배사만 선택할 수 있습니다.",
             "createdBy": "쿠팡 셀러 시스템", "createdAt": "2026-11-02T17:15:21"}]   # 실제 API 응답 모양
    s = reg_status.summarize(real)
    assert s["status"] == "승인반려" and "도서산간배송" in s["reason"]


def test_refresh_shows_reason_on_page_and_skips_other_mode(monkeypatch):
    A.store.delete_registrations(None)
    fake = FakeClient()
    monkeypatch.setattr(A, "client", fake)
    A.store.log_registration("반려될 상품", True, "등록 완료 sellerProductId=111", {}, mode="live", seller_product_id="111")
    A.store.log_registration("승인될 상품", True, "등록 완료 sellerProductId=222", {})            # 이전 버전 이력 (결과 문구에서 ID)
    A.store.log_registration("모의 상품", True, "[모의] 등록 완료 sellerProductId=333", {})      # 모의 이력은 실제 쿠팡에 묻지 않음
    A.store.log_registration("없는 상품", True, "등록 완료 sellerProductId=999", {}, mode="live", seller_product_id="999")
    A.store.log_registration("실패", False, "필수 항목 누락", {}, mode="live")
    c = A.app.test_client()
    r = c.post("/register/history/status", follow_redirects=True).get_data(as_text=True)
    assert sorted(fake.calls) == ["111", "222", "999"]
    assert "쿠팡 상태 2건 확인 · 새 반려 1건 · 실패 1건" in r
    assert "반려 사유" in r and "대표이미지 기준 위반" in r and "승인완료" in r and "상태변경 이력 3건" in r
    assert "404: 상품을 찾을 수 없습니다" in r
    assert any("쿠팡 승인반려: 반려될 상품" in a["message"] for a in A.store.alerts())
    fake.calls.clear()
    c.post("/register/history/status")
    assert sorted(fake.calls) == ["111", "999"]                       # 승인완료는 자동 확인에서 빠짐
    ok_id = next(r["id"] for r in A.store.registrations() if r["name"] == "승인될 상품")
    fake.calls.clear()
    c.post("/register/history/status", data={"reg_id": [str(ok_id)]})  # 고르면 승인완료도 다시 확인
    assert fake.calls == ["222"]
    log = c.get("/register/history/export.log").get_data(as_text=True)
    assert "쿠팡 상태: 승인반려" in log and "반려 사유: 대표이미지 기준 위반" in log
    A.store.delete_registrations(None)


def test_mock_client_history():
    from mock_backend import MockCoupangClient
    m = MockCoupangClient()
    spid = m.create_product({"sellerProductName": "x", "requested": False, "items": []})["data"]
    assert [h["status"] for h in m.get_status_history(spid)] == ["임시저장"]
    statuses = {reg_status.summarize(m.get_status_history(n))["status"] for n in range(1300000300, 1300000306)}
    assert statuses == {"승인완료", "승인반려"}
