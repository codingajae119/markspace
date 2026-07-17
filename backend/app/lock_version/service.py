"""LockVersionService — 편집 잠금 생명주기·저장 오케스트레이션
(design.md §Components and Interfaces #LockVersionService).

start_edit·save·cancel_edit·force_unlock·list_versions 5개 유스케이스의 충돌·멱등·보유자
판정 규칙을 소유한다. 저장은 버전 생성·`current_version_id` 갱신·잠금 해제를 단일 트랜잭션
으로 원자 처리한다(REQ-2). 모든 동작은 문서 status 를 검사하지 않는다(§4.3).

이후 task 에서 구현한다(현재는 스캐폴드).
"""
