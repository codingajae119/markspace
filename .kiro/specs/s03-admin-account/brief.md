# Brief: s03-admin-account

## Problem
폐쇄형 서비스에는 회원 가입이 없고 단일 admin이 계정을 수동 관리한다. 사용자 생성·삭제(flag)·비활동·
재활성화·비밀번호 재설정 경로가 필요하다.

## Current State
s01의 user 스키마·에러·권한 계약 존재. admin은 DB 수동 설정(앱상 생성 기능 없음). 계정 생명주기
동작 미구현.

## Desired Outcome
- admin이 신규 user 생성(REQ-2.2).
- 사용자 삭제 = `is_deleted=true`만(물리 삭제 없음, 2.3).
- 비활동 처리 = `is_active=false`(로그인 금지, 2.4).
- 삭제 flag 되돌림 → 재활성화(2.5).
- 비밀번호 분실 재설정은 admin만(1.6).
- `is_deleted=true` 사용자도 작성자·버전 히스토리에 이름 보존(2.3 표시 요건은 하위 spec에서 소비).

## Approach
s01 권한 resolver의 admin 판별을 사용해 admin 전용 라우터/서비스로 계정 생명주기 구현. 모든 삭제는
flag 전환(INV-4). is_active/is_deleted는 별개 상태로 관리.

## Scope
- **In**: 사용자 생성·삭제(flag)·비활동·재활성화, admin 비밀번호 재설정.
- **Out**: 로그인/세션(s02), 워크스페이스 소유권 변경(s05, workspace 자원 필요), 문서 데이터(s07+).

## Boundary Candidates
- 계정 생명주기(생성/삭제/비활동/재활성화)
- admin 비밀번호 재설정

## Out of Boundary
- 워크스페이스 소유권 변경(2.7)은 s05가 소유(workspace 멤버십 자원 필요)
- admin의 문서/데이터 접근(INV-3)은 s01 권한 resolver로 전 계층 공통 처리

## Upstream / Downstream
- **Upstream**: s01-contract-foundation(user 스키마·권한 resolver·에러 계약)
- **Downstream**: s02가 소비할 계정 상태를 생성, s04 체크포인트

## Existing Spec Touchpoints
- **Extends**: 없음(신규)
- **Adjacent**: s02-auth(같은 user 테이블, 인증 담당)

## Constraints
단일 admin(2.1), 물리 삭제 없음(INV-4), admin 접근 무제약(INV-3)은 s01 resolver로. 산출물 한국어.
