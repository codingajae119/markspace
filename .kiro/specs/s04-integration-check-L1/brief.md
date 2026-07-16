# Brief: s04-integration-check-L1

## Problem
계층 1(auth + admin-account)이 완성된 시점에, 계정 생명주기(s03)와 로그인 경계(s02)가 공유 계약과
정합하는지, 두 spec의 경계(계정 상태 ↔ 로그인 허용)가 실제 결합에서 성립하는지 검증해야 한다.
이 검증 없이 상위 계층 impl을 시작하면 계정 상태 회귀가 이후 전 계층으로 전파된다.

## Current State
s02-auth, s03-admin-account 구현 완료 가정. 개별 spec 단위 검증만 존재하고 결합 검증은 없음.

## Desired Outcome (누적 검증 대상: 계약 ⊕ s02-auth ⊕ s03-admin-account)
- **계약 정합**: user 스키마·세션/인증 API·에러 모델이 s01 단일 소스와 일치.
- **cross-spec 시나리오(이번 계층 신규 경계 = 계정상태↔로그인)**:
  - admin이 사용자 생성 → 그 사용자가 로그인 성공.
  - admin이 비활동(`is_active=false`) → 자격 증명이 맞아도 로그인 거부(1.2).
  - admin이 삭제(`is_deleted=true`) → 로그인 거부(1.3).
  - admin이 삭제 flag 되돌림(재활성화) → 다시 로그인 성공(2.5).
  - admin 비밀번호 재설정 → 새 비밀번호로 로그인 성공(1.6).
  - 사용자 본인 비밀번호 변경 → 새 비밀번호로 로그인, 이전 비밀번호 거부(1.5).
  - 물리 삭제 없음(INV-4): 삭제 사용자 레코드·이름 보존 확인.

## Approach
mock 없이 실제 s02·s03 구현을 결합한 integration/e2e 테스트로 구성. 검증 기준은 개별 design이 아니라
`s01-contract-foundation` 단일 소스. feature 로직은 구현하지 않는다.

## Scope
- **In**: 계약 대조(스키마/API/에러) + 위 cross-spec 시나리오의 integration/e2e 테스트.
- **Out**: 새로운 feature 동작 구현, 상위 계층(workspace 이상) 관심사.

## Boundary Candidates
- 계약 대조 스위트(계정·세션 스키마/API/에러)
- 계정상태 ↔ 로그인 결합 시나리오 스위트

## Out of Boundary
- feature 로직 구현 일체
- workspace/문서 등 상위 계층 결합(후속 체크포인트 담당)

## Upstream / Downstream
- **Upstream**: s01-contract-foundation, s02-auth, s03-admin-account
- **Downstream**: 게이트 G-1 — 통과해야 L2(s05-workspace) impl 착수 가능

## Existing Spec Touchpoints
- **Extends**: 없음(검증 전용 spec, feature 미구현)
- **Adjacent**: s02, s03(검증 대상)

## Constraints
mock 금지(실제 구현 결합). 검증 기준은 s01 단일 소스. upstream(s01~s03) 수정 시 이 체크포인트 및
이후 모든 체크포인트를 누적 재실행(재검증 트리거). 산출물 한국어.
