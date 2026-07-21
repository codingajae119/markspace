"""테스트 공용 지원 헬퍼.

라우트 계약을 검사하는 스위트는 앱을 버전 네임스페이스(`/api/1.0`) 하위로 조립한 뒤에도
**논리 경로**(`/auth/login`·`/documents/{id}` 등)를 기준으로 대조하는 것이 s01 카탈로그
단일 소스와 정합한다. 전송 prefix 는 조립 지점의 관심사이지 계약의 일부가 아니기 때문이다.

:func:`logical_openapi_paths` 는 `app.openapi()["paths"]` 에서 전송 prefix 를 벗긴 논리 경로를
키로 하는 dict 를 돌려준다. prefix 없이 조립된 bare 라우터 미니 앱(단위 라우터 테스트)에는
벗길 prefix 가 없어 원본을 그대로 돌려준다(무해).
"""

from __future__ import annotations

from app.main import API_V1_PREFIX

__all__ = ["logical_openapi_paths"]


def logical_openapi_paths(app: object) -> dict:
    """`app.openapi()["paths"]` 를 전송 prefix(`/api/1.0`)를 벗긴 논리 경로 키로 반환한다.

    값(메서드→오퍼레이션 매핑)은 원본을 그대로 유지하므로 기존 계약 단언
    (`path in paths`·`method in paths[path]`·`path not in paths`)을 변경 없이 재사용할 수 있다.
    """
    paths = app.openapi()["paths"]  # type: ignore[attr-defined]
    logical: dict = {}
    for path, methods in paths.items():
        if isinstance(path, str) and path.startswith(API_V1_PREFIX):
            path = path[len(API_V1_PREFIX):] or "/"
        logical[path] = methods
    return logical
