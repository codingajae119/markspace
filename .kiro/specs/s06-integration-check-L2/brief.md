# Brief: s06-integration-check-L2

## Problem
계층 2(workspace)가 완성된 시점에, 권한 경계·admin override·소유권 흐름이 아래 계층(auth·admin-account)
결합까지 포함해 공유 계약과 정합하는지 누적 검증해야 한다.

## Current State
s05-workspace 구현 완료 가정. L1 체크포인트(s04) 통과 상태.

## Desired Outcome (누적: 계약 ⊕ auth ⊕ admin-account ⊕ workspace)
- **계약 정합**: workspace·workspace_member 스키마, 워크스페이스/멤버십 API, 권한 resolver 계약이
  s01 단일 소스와 일치.
- **cross-spec 시나리오(이번 계층 신규 경계 = 권한·멤버십, + 아래 계층 결합)**:
  - owner가 WS 생성 → 전체 사용자 목록에서 멤버 추가(role 지정) → role별 권한 경계 검증
    (viewer 읽기전용 INV-2 / editor 문서권한 / owner 관리권한).
  - admin이 비멤버 WS에 접근 성공(INV-3, 2.6).
  - admin이 소유권 변경(2.7) → 새 owner 권한 반영.
  - 유일 owner를 admin이 비활동/삭제(s03) → editor·viewer 활동 무영향(3.7).
  - 삭제/비활동 사용자(L1)의 멤버십 상호작용: 로그인 거부되나 멤버십·이름 보존.
  - owner/admin이 is_shareable·retention_days 설정 반영.

## Approach
mock 없이 s02·s03·s05 실제 결합 integration/e2e. 검증 기준은 s01 단일 소스. feature 미구현.

## Scope
- **In**: 계약 대조 + 권한·멤버십·admin override·소유권 시나리오(아래 계층 결합 포함) 테스트.
- **Out**: feature 로직, 문서 도메인(L3 이상).

## Boundary Candidates
- 권한 경계 결합 스위트(role × 자원)
- admin override·소유권 시나리오 스위트
- 계정상태(L1) ↔ 멤버십 결합 스위트

## Out of Boundary
- feature 구현, 문서/버전/휴지통/공유/첨부(후속 체크포인트)

## Upstream / Downstream
- **Upstream**: s01~s03, s04, s05
- **Downstream**: 게이트 G-1 — 통과해야 L3(s07-document-core) impl 착수 가능

## Existing Spec Touchpoints
- **Extends**: 없음(검증 전용)
- **Adjacent**: s05(주 검증 대상), s02·s03(누적 결합)

## Constraints
mock 금지. 기준은 s01 단일 소스. 누적 대상 = 계약+auth+admin+workspace. 재검증 트리거 적용. 한국어.
