"""테스트 전역 지원 — 조립 앱 대상 클라이언트의 전송 prefix(`/api/1.0`) 자동 부착.

앱은 모든 라우터를 버전 네임스페이스(`app.main.API_V1_PREFIX = "/api/1.0"`) 하위에 조립한다.
그러나 통합 테스트는 라우터의 **논리 경로**(`/auth/login`·`/documents` 등)로 요청을 표현하는
것이 읽기 쉽고, 전송 prefix 는 프론트 `apiConfig.baseUrl` 처럼 한 곳에서 책임지는 것이 옳다.

그래서 이 autouse fixture 는 `TestClient.request` 를 감싸, **붙인 경로가 대상 앱의 실제 버전
라우트와 매칭될 때만** 앱-상대 URL(`/...`) 앞에 `/api/1.0` 을 붙인다:

- `/auth/login` → `/api/1.0/auth/login` 이 실 라우트와 매칭 → prefix 부착(통합/조립 클라이언트).
- 단위 라우터 테스트의 **bare 라우터 미니 앱**(prefix 없음) → 버전 라우트가 없어 미부착.
- 의존성/배선 테스트가 조립 앱에 **임시로 붙인 루트 프로브**(`/_probe/{id}`·`/_boom` 등)
  → `/api/1.0/_probe/...` 가 어떤 실 라우트와도 매칭되지 않아 미부착(프로브 경로 그대로 유지).

매칭 판정은 `app.openapi()["paths"]` 의 버전 경로 템플릿(`/api/1.0/documents/{id}`)을 정규식으로
바꿔 후보 경로와 대조한다. starlette 는 `include_router` 를 sub-app 으로 마운트해 최상위
`app.routes[].path` 가 완전 경로를 드러내지 않으므로, 권위 소스인 openapi 를 쓴다.
이미 `/api/1.0` 으로 시작하는 URL·절대 URL·비문자열 URL 은 건드리지 않는다(멱등·안전).
"""

from __future__ import annotations

import re
import weakref

import pytest
from starlette.testclient import TestClient

from app.main import API_V1_PREFIX

# 감싸기 전 원본 request(스타렛 TestClient 구현)를 모듈 로드 시 1회 포획한다.
_ORIG_REQUEST = TestClient.request

# 앱별 버전 라우트 매처(정규식 목록) 캐시. 앱이 GC 되면 항목도 자동 소멸(약참조).
_MATCHER_CACHE: "weakref.WeakKeyDictionary[object, list]" = weakref.WeakKeyDictionary()


def _versioned_route_matchers(app: object) -> list:
    """대상 앱의 버전 경로 템플릿(`/api/1.0/...`)을 정규식 매처 목록으로 돌려준다(캐시).

    비어 있으면 비버전 앱(bare 라우터 미니 앱 등)이다. 경로 파라미터(`{id}`)는 한 세그먼트
    (`[^/]+`)로 바꿔 실제 라우팅과 동일한 세그먼트 경계로 매칭한다.
    """
    if app is None:
        return []
    try:
        cached = _MATCHER_CACHE.get(app)
    except TypeError:  # 약참조 불가 객체
        cached = None
    if cached is not None:
        return cached

    matchers: list = []
    openapi = getattr(app, "openapi", None)
    if callable(openapi):
        try:
            for tmpl in openapi().get("paths", {}):
                if isinstance(tmpl, str) and tmpl.startswith(API_V1_PREFIX):
                    regex = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", tmpl) + "$"
                    matchers.append(re.compile(regex))
        except Exception:  # openapi 생성 불가한 앱은 비버전으로 간주(안전)
            matchers = []

    try:
        _MATCHER_CACHE[app] = matchers
    except TypeError:
        pass
    return matchers


def _prefixed_request(self: TestClient, method, url, *args, **kwargs):
    """앱-상대 URL 이고 `/api/1.0`+경로가 실 버전 라우트와 매칭되면 prefix 를 붙여 위임한다."""
    if isinstance(url, str) and url.startswith("/") and not url.startswith(API_V1_PREFIX):
        path_only = url.split("?", 1)[0].split("#", 1)[0]
        candidate = f"{API_V1_PREFIX}{path_only}"
        matchers = _versioned_route_matchers(getattr(self, "app", None))
        if any(rx.match(candidate) for rx in matchers):
            url = f"{API_V1_PREFIX}{url}"
    return _ORIG_REQUEST(self, method, url, *args, **kwargs)


@pytest.fixture(autouse=True)
def _prefix_versioned_testclient(monkeypatch):
    """모든 테스트에서 조립 앱 대상 TestClient 요청에 전송 prefix 를 자동 부착한다."""
    monkeypatch.setattr(TestClient, "request", _prefixed_request)
