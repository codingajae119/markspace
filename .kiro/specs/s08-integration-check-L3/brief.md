# Brief: s08-integration-check-L3

## Problem
계층 3(document-core)이 완성된 시점에, 문서 도메인이 권한 경계(s05)·계정/세션(L1)과 결합해 공유
계약과 정합하는지, 그리고 bundle 전이 엔진의 불변식(INV-10~12)이 실제 API 결합에서 성립하는지
누적 검증해야 한다. 이 코어가 회귀하면 이후 모든 상위 계층(잠금·휴지통·첨부·공유)이 오염된다.

## Current State
s07-document-core 구현 완료 가정. L2 체크포인트(s06) 통과 상태.

## Desired Outcome (누적: 계약 ⊕ auth ⊕ admin ⊕ workspace ⊕ document-core)
- **계약 정합**: document·document_version 스키마, 문서 API, status 전이 계약이 s01 단일 소스와 일치.
- **cross-spec 시나리오(이번 계층 신규 경계 = 문서 도메인, + 아래 계층 결합)**:
  - editor+ 문서·하위문서 생성, viewer 읽기전용 거부(권한 경계 결합, INV-2).
  - 같은 WS 이동/재정렬 성공, 자기/후손 이동 거부(INV-5), 타 WS 이동 거부(INV-6).
  - admin이 비멤버 WS 문서 접근(INV-3).
  - **bundle 엔진 결합**: 삭제 캐스케이드가 active 하위만 포착(6.2), 먼저 삭제된 자식 비흡수(6.4,
    INV-11), 복구 위치가 부모 상태로 결정(6.5.1/6.5.2), sort_order 원위치/append 복원(6.7),
    완전삭제 묶음 원자성(INV-10), 묶음별 독립성(INV-12).
  - 작성자 표시: `is_deleted` 사용자(L1) 이름이 문서 작성자로 보존.

## Approach
mock 없이 s05·s07 + 아래 계층 실제 결합 integration/e2e. bundle 엔진은 API 경유 시나리오로 불변식
검증. 검증 기준은 s01 단일 소스. feature 미구현.

## Scope
- **In**: 계약 대조 + 문서 도메인·bundle 엔진·권한 결합 시나리오 테스트.
- **Out**: 편집 잠금/버전 흐름(L4), 휴지통 UX/타이머(L4), 첨부·공유(L5·L6).

## Boundary Candidates
- 문서 CRUD·계층·이동 결합 스위트(권한 게이팅 포함)
- bundle 전이 엔진 불변식 스위트(INV-10~12, 6.5 복구 규칙)

## Out of Boundary
- feature 구현, 잠금/버전/휴지통/첨부/공유(후속 체크포인트)

## Upstream / Downstream
- **Upstream**: s01~s06, s07
- **Downstream**: 게이트 G-1 — 통과해야 L4(s09-lock-version, s10-trash) impl 착수 가능

## Existing Spec Touchpoints
- **Extends**: 없음(검증 전용)
- **Adjacent**: s07(주 검증 대상)

## Constraints
mock 금지. 기준은 s01 단일 소스. 누적 대상 = 계약+auth+admin+workspace+document-core. 재검증 트리거. 한국어.
