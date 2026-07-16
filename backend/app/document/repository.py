"""문서 데이터 접근 계층 — `DocumentRepository`
(design.md §Components and Interfaces #DocumentRepository).

document·document_version 질의와 계층/상태 조회의 단일 데이터 접근점이다. s01 document·
document_version 모델과 `get_db` 세션을 사용하며 문서는 INV-4 대상이라 물리 삭제 없이 상태
전환만 수행한다. 계층 질의(자식·active 하위·형제·부모), 상태 질의(WS active 목록·trashed
열거), 현재 버전 본문 로드, 삽입·부분 갱신·묶음 상태 일괄 전이·부모/정렬 갱신을 제공한다.

`DocumentRepository` 의 실제 구현은 후속 task 1.2 의 소유다. 이 모듈은 현재 import 가능한
골격이며, 상태 규칙(무엇을 묶음으로 볼지·복구 위치)은 엔진이 결정하고 여기서는 질의·쓰기만 담당한다.
"""
