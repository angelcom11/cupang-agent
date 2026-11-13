"""대시보드 최근 알림: 선택 삭제, 모두 지우기, 로그 파일 저장."""
import os, tempfile

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import app as A  # noqa: E402


def test_delete_selected_all_and_export():
    A.store.delete_alerts(None)
    for i in range(3):
        A.store.alert("warn", "stock", f"재고 부족({i}개): 상품{i}")
    ids = [a["id"] for a in A.store.alerts()]
    c = A.app.test_client()
    html = c.get("/classic/").get_data(as_text=True)
    assert html.count('name="alert_id"') == 3 and "로그 저장" in html
    r = c.get("/alerts/export.log")
    body = r.data.decode("utf-8")
    assert "attachment; filename=wing-alerts-" in r.headers["Content-Disposition"] and ".log" in r.headers["Content-Disposition"]
    assert body.count("[WARN] [stock]") == 3 and body.index("상품0") < body.index("상품2")   # 오래된 것부터
    r = c.post("/alerts/delete", data={"scope": "selected", "alert_id": [str(ids[0])]}, follow_redirects=True)
    assert "알림 1건을 지웠습니다" in r.get_data(as_text=True) and len(A.store.alerts()) == 2
    r = c.post("/alerts/delete", data={"scope": "selected"}, follow_redirects=True)
    assert "지울 알림을 선택하세요" in r.get_data(as_text=True) and len(A.store.alerts()) == 2
    r = c.post("/alerts/delete", data={"scope": "all"}, follow_redirects=True)
    assert "알림 2건을 지웠습니다" in r.get_data(as_text=True) and A.store.alerts() == []
    assert "알림이 없습니다" in r.get_data(as_text=True)


def test_registration_history_delete_and_export():
    A.store.delete_registrations(None)
    A.store.log_registration("성공 상품", True, "등록 완료 sellerProductId=1", {"a": 1})
    A.store.log_registration("실패 상품", False, "카테고리 누락", {"displayCategoryCode": None})
    A.store.log_registration("세번째", True, "등록 완료 sellerProductId=3", {})
    ids = [r["id"] for r in A.store.registrations()]
    c = A.app.test_client()
    html = c.get("/register").get_data(as_text=True)
    assert html.count('name="reg_id"') == 3 and "export.log" in html
    r = c.get("/register/history/export.log")
    body = r.data.decode("utf-8")
    assert "filename=wing-register-" in r.headers["Content-Disposition"]
    assert "[OK] 성공 상품" in body and "[FAIL] 실패 상품 | 카테고리 누락" in body
    assert body.index("성공 상품") < body.index("세번째")          # 오래된 것부터
    assert body.count("payload:") == 1                           # 실패 건만 보낸 내용 기록
    r = c.post("/register/history/delete", data={"scope": "selected", "reg_id": [str(ids[0])]}, follow_redirects=True)
    assert "등록 이력 1건을 지웠습니다" in r.get_data(as_text=True) and len(A.store.registrations()) == 2
    r = c.post("/register/history/delete", data={"scope": "selected"}, follow_redirects=True)
    assert "지울 등록 이력을 선택하세요" in r.get_data(as_text=True) and len(A.store.registrations()) == 2
    r = c.post("/register/history/delete", data={"scope": "all"}, follow_redirects=True)
    assert "등록 이력 2건을 지웠습니다" in r.get_data(as_text=True) and A.store.registrations() == []
