# Brief: s09-lock-version

## Problem
동시 편집 충돌을 실시간 병합(CRDT) 대신 단순 편집 잠금으로 방지하고, 저장 시마다 버전 스냅샷을
무한 보관해야 한다(rollback은 없음). "다른 사용자 편집 중" 표시가 필요하다.

## Current State
s07-document-core의 문서 엔티티·lock 필드(lock_user_id·lock_acquired_at)·document_version 스키마 존재.
잠금 획득/해제 흐름과 버전 저장 동작 미구현.

## Desired Outcome
- editor+ "편집 시작" → 문서 잠금(REQ-5.1).
- 타인 잠금 시 편집 시작 차단 + UI "다른 사용자 편집 중"(5.2).
- "저장" → 새 document_version 생성·current_version 갱신·잠금 해제(5.3).
- 저장 없이 취소/이탈 → 잠금 해제·변경분 폐기(5.4).
- lock 자동 타임아웃 없음(5.5). owner/admin 강제 해제(변경분 폐기, 5.6).
- 각 저장 = 새 버전, 무한 보관, rollback 없음(5.7).

## Approach
s07 문서 엔티티의 lock 필드·버전 스키마를 사용해 잠금/버전 서비스 구현. 잠금 보유자 단일성(INV-9)
enforce. 잠금 상태와 삭제 상태는 독립(§4.3) — 삭제된/잠긴 문서 충돌 없음.

## Scope
- **In**: 편집 잠금 획득/해제/강제해제, 저장 시 버전 생성·current 갱신, 편집 취소 폐기, 편집중 표시.
- **Out**: 문서 CRUD·이동(s07), 휴지통/보관(s10), 버전이 참조하던 이미지 아카이브(8.7는 s12).

## Boundary Candidates
- 편집 잠금 생명주기
- 저장 → 버전 스냅샷

## Out of Boundary
- 과거 버전 rollback(도입 안 함)
- 참조 소멸 이미지 아카이브(8.7)는 s12-attachment 소유

## Upstream / Downstream
- **Upstream**: s01(스키마), s07(문서 엔티티·lock 필드), s08(게이트 통과)
- **Downstream**: s12-attachment(저장 시 참조 소멸 판정에 버전 필요), s11 체크포인트

## Existing Spec Touchpoints
- **Extends**: 없음(신규). s07의 lock 필드·version 스키마를 소비.
- **Adjacent**: s10-trash(같은 L4, 잠금↔삭제 독립)

## Constraints
INV-9(잠금 최대 1인), 타임아웃 없음, rollback 없음, 무한 보관, 잠금·삭제 독립(§4.3). 한국어.
