# Brief: s11-integration-check-L4

## Problem
계층 4(lock-version + trash)가 완성된 시점에, 편집 잠금·버전과 휴지통 흐름이 document-core 엔진 및
아래 계층(권한·계정) 결합까지 포함해 공유 계약과 정합하는지 누적 검증해야 한다. 특히 잠금↔삭제
독립성(§4.3)과 묶음별 독립 보관 타이머(INV-12)가 실제 결합에서 성립하는지 확인한다.

## Current State
s09-lock-version, s10-trash 구현 완료 가정. L3 체크포인트(s08) 통과 상태.

## Desired Outcome (누적: 계약 ⊕ auth ⊕ admin ⊕ workspace ⊕ document-core ⊕ lock-version ⊕ trash)
- **계약 정합**: document_version·lock 필드·휴지통 API가 s01 단일 소스와 일치.
- **cross-spec 시나리오(이번 계층 신규 경계 = 잠금/버전 + 휴지통, + 아래 결합)**:
  - 편집 시작→타인 차단(5.2)→저장 시 새 버전·잠금 해제(5.3), 취소 시 폐기·해제(5.4).
  - owner/admin 강제 해제(5.6), 타임아웃 없음(5.5), 저장 반복 시 버전 무한 누적·rollback 없음(5.7).
  - 잠금↔삭제 독립(§4.3): 잠긴 문서 trashed 가능, trashed 문서의 잠금 상태 충돌 없음.
  - 휴지통: editor+ WS 전체 열람·복구·완전삭제, viewer 거부(6.11); 복구 위치 규칙(6.5)이 엔진
    결합에서 성립; 완전삭제 묶음 원자성(6.9, INV-10); 보관 만료 자동 deleted가 묶음별 독립
    타이머로 동작(6.8, INV-12), 자식이 부모보다 먼저 만료되는 케이스(6.4.1) 수용 확인.
  - 권한/계정(아래 계층) 결합: role별 잠금·휴지통 접근 경계, admin override.

## Approach
mock 없이 s07·s09·s10 + 아래 계층 실제 결합 integration/e2e. 타이머는 시간 주입/경계 조건으로 검증.
검증 기준은 s01 단일 소스. feature 미구현.

## Scope
- **In**: 계약 대조 + 잠금/버전·휴지통·엔진·권한 결합 시나리오(아래 계층 포함) 테스트.
- **Out**: 첨부 보관 이동(L5), 공유 무효화(L6), feature 구현.

## Boundary Candidates
- 잠금/버전 결합 스위트
- 휴지통(복구 위치·완전삭제·보관 타이머) 결합 스위트
- 잠금↔삭제 독립성 스위트

## Out of Boundary
- feature 구현, 첨부/공유(후속 체크포인트)

## Upstream / Downstream
- **Upstream**: s01~s08, s09, s10
- **Downstream**: 게이트 G-1 — 통과해야 L5(s12-attachment) impl 착수 가능

## Existing Spec Touchpoints
- **Extends**: 없음(검증 전용)
- **Adjacent**: s09·s10(주 검증 대상)

## Constraints
mock 금지. 기준은 s01 단일 소스. 누적 대상 = 계약+auth+admin+workspace+document-core+lock-version+trash.
재검증 트리거. 한국어.
