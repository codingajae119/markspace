"""LockVersionRouter — 잠금·버전 5개 엔드포인트 (카탈로그 행 24~28)
(design.md §Components and Interfaces #LockVersionRouter).

`POST /documents/{id}/lock`·`/save`·`/cancel`·`/force-unlock`·`GET /documents/{id}/versions`
를 노출한다. 모든 경로는 s07 문서→WS 어댑터(`ws_role_for_document`)로 게이팅되고 판정은
s01 resolver(`require_ws_role`)가 담당한다. 라우터는 스키마 검증·게이트·서비스 위임만 한다.

이후 task 에서 구현한다(현재는 스캐폴드).
"""
