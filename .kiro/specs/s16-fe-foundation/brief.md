# Brief: s16-fe-foundation

## Problem
프론트엔드 전체가 공유하는 교차 관심사 레이어가 필요하다. 라우팅 셸, 공용 API 클라이언트,
전역 401 인터셉터, 권한(역할) 게이팅 유틸, Toast UI Editor 래핑을 **단일 소유 공통 레이어**로
확립해야 한다. 이 레이어가 없으면 후속 feature마다 401 처리·역할 비교·API base URL이 흩어져
드리프트가 발생한다. 백엔드 계층을 미러링하는 프론트 spec의 L0(upstream)이다.

## Current State
백엔드 전체 시스템 GO(s01~s15). `frontend/` 디렉터리는 아직 없음(신규 스캐폴드). 소비 대상 계약은
s01(에러 응답 모델·세션 인증 의존성·API 카탈로그·권한 resolver INV-1·2·3)에 단일 소스로 존재.
세션 확인 엔드포인트 `GET /auth/me`(AuthUserRead), 사용자 설정 `GET/PATCH /me/settings`가 부트스트랩에 사용됨.

## Desired Outcome
- React + Vite + Tailwind CSS 4 SPA 스캐폴드(`frontend/`), TypeScript strict.
- 단일 설정 파일(`src/config.ts` 또는 Vite env 1개)로 API base URL 통일(하드코딩 상수 금지).
- 공통 레이어(`src/app`·`src/shared`) 단일 소유: 라우터 정의, 공용 API 클라이언트, 전역 401 인터셉터,
  권한 게이팅 유틸, 공용 UI 프리미티브, Toast UI Editor 래퍼(편집=WYSIWYG+markdown 토글, 읽기=viewer mode 통일).
- **보호 라우트**: 세션 없으면 `returnTo` 보존 후 로그인 리다이렉트 → 성공 시 복귀.
- **게스트 라우트**: `/share/:token` — 인증 가드 없는 읽기 전용 경로 등록(뷰는 s22 소유).
- **전역 401**: 공용 API 클라이언트가 가로채 `returnTo` 보존 후 로그인 리다이렉트(호출부 개별 처리 금지).
- 세션 부트스트랩: 앱 로드 시 `/auth/me`로 현재 세션·역할 확인, 컨텍스트로 노출.
- 권한 게이팅 유틸: 역할(owner/editor/viewer)·admin override(INV-3)에 따른 UI 노출 결정을 공통 유틸로 단일화.

## Approach
백엔드가 확립한 "단일 소유 레이어" 캡슐화 문법을 프론트에 적용. 라우팅·401·권한 게이팅을 공통 레이어에
한 번만 구현하고, feature는 이를 소비만 한다. Toast UI Editor는 편집/읽기 렌더 경로를 이원화하지 않도록
단일 래퍼로 감싼다.

## Scope
- **In**: FE 스캐폴드, 설정 단일화, 라우터 셸(보호/게스트 라우트 등록 지점), 공용 API 클라이언트+401 인터셉터,
  세션 컨텍스트(`/auth/me` 부트스트랩), 권한 게이팅 유틸, 공용 UI·Toast UI 래퍼, 전역 레이아웃/에러 경계.
- **Out**: 실제 로그인 화면·세션 폼(s17), WS/문서/편집/첨부/공유 화면(s18~s22). 각 feature 화면은
  이 레이어를 소비하되 여기서 구현하지 않는다.

## Boundary Candidates
- 앱 스캐폴드·설정 단일화
- 라우팅 셸(보호/게스트 라우트 프레임)
- 공용 API 클라이언트 + 전역 401 인터셉터
- 권한 게이팅 유틸 + 세션 컨텍스트
- 공용 UI + Toast UI Editor 래퍼

## Out of Boundary
- 로그인/비번변경 화면·플로우(s17)
- feature별 화면·데이터 훅(s18~s22)

## Upstream / Downstream
- **Upstream**: s01-contract-foundation(에러 모델·세션 의존성·API 카탈로그·권한 resolver·INV-1·2·3)
- **Downstream**: s17~s22 전부(이 공통 레이어를 소비)

## Existing Spec Touchpoints
- **Extends**: 없음(신규 프론트 L0)
- **Adjacent**: 없음(모든 후속 프론트 spec의 공통 upstream)

## Constraints
검증 기준은 s01 계약 단일 소스. 교차 관심사는 공통 레이어 단일 소유(feature 중복 구현 금지).
TypeScript strict 권장, 설정 단일화. 산출물 한국어.
