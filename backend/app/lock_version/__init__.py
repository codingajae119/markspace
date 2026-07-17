"""lock_version feature 모듈 (s09-lock-version).

문서 **편집 잠금**(시작·저장·취소·강제 해제) 생명주기와 **저장 시 버전 생성**
(`document_version` append + `current_version_id` 갱신 + 잠금 해제의 원자적 처리)
동작을 소유한다. 잠금 판정 근거는 `document.lock_user_id` 단일 컬럼(INV-9)이며,
잠금·버전 동작은 문서 status 와 독립이다(§4.3).

s01 계약(document·document_version 모델, lock 필드·`document_version` 스키마,
권한 resolver `require_ws_role`, 세션 인증, 에러 모델, Base Schemas, 라우터 조립 지점)과
s07 문서→workspace_id 어댑터(`ws_role_for_document`)를 재사용하며 어떤 계약 엔티티도
재정의하지 않는다. 새 마이그레이션·새 외부 의존성을 추가하지 않는다
(design.md §Boundary Commitments).
"""
