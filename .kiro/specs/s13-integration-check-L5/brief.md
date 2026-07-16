# Brief: s13-integration-check-L5

## Problem
계층 5(attachment)가 완성된 시점에, 첨부·이미지 파일 생명주기가 아래 계층(문서 코어·버전·휴지통·
권한) 결합까지 포함해 공유 계약과 정합하는지 누적 검증해야 한다. 특히 완전삭제↔보관 이동(8.6)과
저장 참조 소멸↔보관 이동(8.7)의 계층 간 트리거가 실제 결합에서 성립하는지 확인한다.

## Current State
s12-attachment 구현 완료 가정. L4 체크포인트(s11) 통과 상태.

## Desired Outcome (누적: … ⊕ lock-version ⊕ trash ⊕ attachment)
- **계약 정합**: attachment 스키마·파일 API·저장 경로 규약이 s01 단일 소스와 일치.
- **cross-spec 시나리오(이번 계층 신규 경계 = 첨부 생명주기, + 아래 결합)**:
  - 이미지 붙여넣기→파일 저장·문서 참조(8.1), 파일 첨부(8.2), WS별 격리(8.3).
  - **완전삭제 결합(L4↔L5)**: s10 완전삭제/보관 만료 → 연결 첨부가 보관 폴더로 이동
    `is_archived=true`(8.6), 물리 삭제 없음(INV-4).
  - **저장 결합(L4↔L5)**: s09 저장으로 현재 버전에서 참조 소멸된 이미지 → 보관 이동(8.7).
  - 보관 폴더 격리(8.8)·비노출(8.10)·복원 불가(8.9, INV-7).
  - 권한 결합: editor+ 첨부, viewer 불가(INV-2); admin override.

## Approach
mock 없이 s09·s10·s12 + 아래 계층 실제 결합 integration/e2e. 파일시스템 부수효과(격리 경로·보관 이동)를
실제로 관찰. 검증 기준은 s01 단일 소스. feature 미구현.

## Scope
- **In**: 계약 대조 + 첨부 생명주기·완전삭제/저장 트리거·격리 결합 시나리오 테스트.
- **Out**: 공유 링크 경유 파일 접근(L6), feature 구현.

## Boundary Candidates
- 첨부 저장·격리 결합 스위트
- 완전삭제↔보관 이동(8.6), 저장 참조 소멸↔보관 이동(8.7) 트리거 스위트

## Out of Boundary
- feature 구현, 공유 링크(L6 체크포인트)

## Upstream / Downstream
- **Upstream**: s01~s11, s12
- **Downstream**: 게이트 G-1 — 통과해야 L6(s14-sharing) impl 착수 가능

## Existing Spec Touchpoints
- **Extends**: 없음(검증 전용)
- **Adjacent**: s12(주 검증 대상)

## Constraints
mock 금지. 기준은 s01 단일 소스. 누적 대상 = … +lock-version+trash+attachment. 재검증 트리거. 한국어.
