"""document feature 모듈 (s07-document-core).

계층적 markdown 문서 코어와 문서 3단계 상태(active → trashed → deleted) 전이를
지배하는 묶음(bundle) 비흡수 엔진을 소유한다. 문서 CRUD·계층·이동/재정렬(순환 방지·
동일 워크스페이스)·현재 버전 렌더/preview 를 제공하며, 삭제·복구·완전삭제·묶음 식별을
`DocumentStateEngine` 단일 구현에 캡슐화해 하위 spec(s10-trash·s14-sharing)이 규칙을
재구현하지 않고 primitive 를 호출해 소비하게 한다.

s01 계약(document·document_version·workspace 모델, 권한 resolver `require_ws_role`,
세션 인증, 에러 모델, Base Schemas, Settings, 라우터 조립 지점)과 s05 가 실동작시킨
`require_ws_role` 을 재사용하며 어떤 계약 엔티티도 재정의하지 않는다
(design.md §Boundary Commitments).
"""
