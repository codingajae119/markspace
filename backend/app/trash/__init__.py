"""trash feature 모듈 (s10-trash).

워크스페이스 **휴지통** 단계 동작 — 묶음 목록 열람, 묶음 복구, 묶음 즉시 완전삭제,
그리고 묶음별 독립 보관 타이머에 따른 자동 영구삭제 배치 — 를 소유한다. 상태 전이·묶음
식별 규칙(비흡수·복구 위치·독립 타이머, INV-10·11·12)은 재구현하지 않고 s07
`DocumentStateEngine` primitive(`identify_bundles`·`get_bundle`·`restore_bundle`·
`purge_bundle`)를 **호출만** 하는 얇은 레이어다.

s01 계약(document·workspace 모델, Base Schemas, 권한 resolver `require_ws_role`, 세션
인증, 에러 모델, 단일 Settings, 라우터 조립 지점)과 s05 실동작 워크스페이스
`trash_retention_days`, s07 상태 엔진·`Bundle` DTO·문서→workspace_id 조회를 재사용하며
어떤 계약 엔티티도 재정의하지 않는다. 새 DB 마이그레이션을 추가하지 않는다
(design.md §Boundary Commitments). s12/s14 를 import 하지 않는다.
"""
