"""문서 라우터 — `DocumentRouter` (design.md §Components and Interfaces #DocumentRouter).

문서 6개 엔드포인트(s01 카탈로그 행 18~23)를 노출한다: `POST/GET /workspaces/{id}/documents`,
`GET/PATCH/DELETE /documents/{id}`, `POST /documents/{id}/move`. 조회·목록은
`require_ws_role(VIEWER)`, 생성·수정·이동·삭제는 `require_ws_role(EDITOR)` 로 게이팅하고
(admin bypass), `/workspaces/{id}/*` 는 경로 id=workspace_id, `/documents/{id}` 는 문서→WS
어댑터로 workspace_id 를 주입한다. DELETE 는 `DocumentStateEngine.trash_document` 를 호출한다.
라우터는 스키마 검증·게이트·서비스/엔진 위임만 담당한다.

`DocumentRouter` 의 실제 엔드포인트 구현과 s01 조립 지점 등록은 후속 task 4.1~4.2 의 소유다.
이 모듈은 현재 import 가능한 골격이다.
"""
