# Brief: s17-fe-auth

## Problem
폐쇄형 서비스 사용자가 UI에서 로그인/로그아웃하고 본인 비밀번호를 변경할 수 있어야 한다. 세션 상태는
공통 레이어(s16)가 소유하며, 이 spec은 그 위에 인증 화면·플로우를 얹는다. 비활동·삭제 계정 로그인 거부,
비번변경 실패는 백엔드 계약의 에러를 그대로 사용자에게 표면화한다.

## Current State
s16 공통 레이어(라우터 셸·API 클라이언트·401 인터셉터·세션 컨텍스트) 확보 가정. 소비 API:
`POST /auth/login`(AuthUserRead), `POST /auth/logout`(204), `GET /auth/me`(AuthUserRead),
`POST /auth/password`(204). 백엔드 s02-auth 동작 완료.

## Desired Outcome
- 로그인 화면: login_id/password 제출 → 세션 생성, `returnTo` 있으면 그 경로로 복귀, 없으면 기본 홈(1.1).
- 비활동(1.2)·삭제(1.3) 계정, 자격 불일치 시 백엔드 에러 메시지 표면화(단일 401/에러 계약 준수).
- 로그아웃: 세션 종료 후 로그인 화면으로(1.4).
- 본인 비밀번호 변경 화면: 현재/새 비밀번호 제출(1.5).
- self sign-up 없음(1.7) — 회원가입 UI 미제공. 분실 재설정 UI 없음(admin 소관, s18).

## Approach
s16 세션 컨텍스트·API 클라이언트를 소비해 인증 화면만 구현. 로그인 성공 시 세션 컨텍스트 갱신,
`returnTo` 복귀는 s16 보호 라우트 규약을 따른다. 401·에러 표면화는 공통 계약을 재사용.

## Scope
- **In**: 로그인 화면·플로우, 로그아웃 액션, 본인 비밀번호 변경 화면, 세션 컨텍스트 연동(로그인/로그아웃 반영).
- **Out**: 라우팅 셸·401 인터셉터·세션 컨텍스트 자체(s16 소유), 사용자 생성/삭제/재설정 admin 콘솔(s18),
  WS 권한(s18).

## Boundary Candidates
- 로그인 화면·세션 진입/복귀
- 본인 비밀번호 변경
- 로그아웃

## Out of Boundary
- 세션 컨텍스트·401·라우팅 프레임(s16)
- admin 계정 관리·비번 재설정(s18)

## Upstream / Downstream
- **Upstream**: s16-fe-foundation(세션 컨텍스트·API 클라이언트·401·라우팅), s01(user·세션·에러 계약)
- **Downstream**: 없음(다른 프론트 spec은 s16의 세션 컨텍스트를 소비, s17 화면에 직접 의존 안 함)

## Existing Spec Touchpoints
- **Extends**: 없음(신규)
- **Adjacent**: s18-fe-workspace(admin 콘솔에서 계정 관리 — 같은 user 도메인, 다른 화면)

## Constraints
백엔드 s02 계약 준수(세션·에러). 단일 401 처리는 s16 경유. 검증 기준 s01 계약. 산출물 한국어.
