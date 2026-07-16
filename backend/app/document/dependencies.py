"""문서 id → workspace_id 추출 어댑터 (design.md §Components and Interfaces #DocumentWsAdapter).

`/documents/{id}` 경로에서 문서의 workspace_id 를 추출해 s01 `require_ws_role` 판정에
주입한다(10.3·10.4). 문서 미존재 시 404, 존재 시 workspace_id 로 판정을 위임한다.
`/workspaces/{id}/*` 경로는 경로 {id} 를 직접 workspace_id 로 사용한다. resolver 위계 비교·
admin bypass 는 s01 소유이므로 재구현하지 않고, 실동작 데이터는 s05 가 채운다.

문서→WS 어댑터의 실제 구현은 후속 task 1.3 의 소유다. 이 모듈은 현재 import 가능한 골격이며,
경로/문서→workspace_id 매핑 주입만 소유한다.
"""
