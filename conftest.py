"""테스트 공통: 실제 설정·DB 대신 임시 폴더를 쓰고, 기존 화면 테스트는 로그인 없이 돌린다.
로그인 동작 자체는 test_auth.py 가 WING_LOGIN_REQUIRED 를 켜고 확인한다."""
import os
import tempfile

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_login_by_default():
    import app as A
    A.app.config["WING_LOGIN_REQUIRED"] = False
    yield
    A.app.config["WING_LOGIN_REQUIRED"] = False
