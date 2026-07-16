# Brief: s02-auth

## Problem
폐쇄형 서비스 사용자가 자격 증명으로 로그인/로그아웃하고 본인 비밀번호를 변경할 수 있어야 한다.
비활동·삭제된 계정은 자격 증명이 맞아도 접근이 차단되어야 한다.

## Current State
s01의 user 스키마·세션 의존성·에러 모델 계약이 존재. 로그인/세션 발급/비밀번호 변경 동작은 미구현.

## Desired Outcome
- 올바른 login_id/password 제출 시 세션 생성·로그인(REQ-1.1).
- `is_active=false`(1.2), `is_deleted=true`(1.3) 계정은 로그인 거부.
- 로그아웃 시 세션 종료(1.4).
- 본인 현재/새 비밀번호 제출 시 변경(1.5).
- self sign-up 없음(1.7). 분실 재설정은 s03(admin)만.

## Approach
s01의 세션 인증 의존성·user 스키마·에러 계약을 재사용하여 인증 라우터/서비스를 구현. 비밀번호는
해시 검증. is_active/is_deleted 게이트를 로그인 경로에 적용.

## Scope
- **In**: 로그인/로그아웃, 세션 발급·종료, 본인 비밀번호 변경, 로그인 게이트(active/deleted).
- **Out**: 사용자 생성/삭제/비활동/재활성화·admin 비밀번호 재설정(s03), 워크스페이스 권한(s05).

## Boundary Candidates
- 인증(로그인/세션) 경로
- 본인 비밀번호 변경

## Out of Boundary
- 계정 생명주기(생성·삭제·flag 변경)는 s03 소유
- 권한/멤버십 판단은 s05

## Upstream / Downstream
- **Upstream**: s01-contract-foundation(user 스키마·세션·에러 계약)
- **Downstream**: 모든 인증 필요 라우터(s05 이상), s04 체크포인트

## Existing Spec Touchpoints
- **Extends**: 없음(신규)
- **Adjacent**: s03-admin-account(같은 user 테이블, 계정 생명주기 담당)

## Constraints
세션 방식·비밀번호 해시는 s01 계약 준수. 산출물 한국어.
