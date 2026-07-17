"""LockVersionRepository — lock 필드·`document_version` 단일 데이터 접근점
(design.md §Components and Interfaces #LockVersionRepository).

일반/행 잠금(`FOR UPDATE`) 문서 로드, lock 필드 r/w(acquire·clear), 버전 insert·current
갱신, 버전 목록 조회를 소유한다. 충돌·멱등·보유자 판정은 Service 소유이며 여기서는 질의·
쓰기만 수행한다. 문서·버전 물리 삭제 없음(INV-4), status 무검사·무변경(§4.3).

이후 task 에서 구현한다(현재는 스캐폴드).
"""
