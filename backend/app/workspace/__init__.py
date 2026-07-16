"""workspace feature 모듈 (s05-workspace).

인증된 사용자가 협업 권한 단위인 워크스페이스를 생성·관리하고, 멤버십
(owner/editor/viewer)·`is_shareable`·`trash_retention_days` 설정·admin 소유권 변경을
소유한다. `workspace_member` 데이터를 채워 s01 권한 resolver 를 실동작시킨다. s01 계약
(workspace·workspace_member·user 모델, 권한 resolver, 세션 인증, 에러 모델, Base
Schemas, 라우터 조립 지점)을 재사용하며 어떤 계약 엔티티도 재정의하지 않는다
(design.md §Boundary Commitments).
"""
