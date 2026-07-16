# Brief: s01-contract-foundation

## Problem
전체 프로젝트가 공유하는 데이터 스키마·API 계약·공용 인터페이스가 각 feature spec에 흩어지면
계약 드리프트가 발생하고, 계층 경계를 넘는 불변식(INV-1~12)을 검증할 단일 기준이 사라진다.
contract-first로 이 단일 소스를 먼저 확정해야 한다.

## Current State
uv 프로젝트 스캐폴드(`pyproject.toml`, `main.py`)만 존재. DB 스키마·공용 Settings·에러 모델·권한
resolver·API 계약 카탈로그가 아직 없다. steering(tech/structure)에 설정 단일화·레이어드 구조·물리
삭제 없음 원칙이 정의되어 있다.

## Desired Outcome
- `docs/projects.md` §2 데이터 모델 전체가 MySQL 8 마이그레이션으로 적용된다(user, workspace,
  workspace_member, document, document_version, attachment, share_link).
- 모든 feature/체크포인트가 참조하는 **공유 계약 단일 소스**가 존재한다: API 엔드포인트 카탈로그,
  `{Resource}Create/Read/Update` Pydantic 스키마 규약, 공통 에러 응답 모델, 도메인 불변식(INV-1~12) 목록.
- 공용 런타임 인프라가 부팅된다: pydantic-settings 단일 `Settings`(config.yml + .env), 공통 에러 핸들러,
  세션 인증 의존성, 워크스페이스 단위 권한 resolver 인터페이스(admin bypass INV-3 포함) 스캐폴드.
- 앱이 부팅되고 마이그레이션이 적용되며 health/스키마 계약이 검증 가능하다.

## Approach
계약 + 공용 런타임 인프라를 함께 소유한다(선택된 접근). 스키마/OpenAPI 계약을 정의하고, 실제로
구현 가능한 공용 인프라(마이그레이션, Settings 로더, 에러 모델, 세션·권한 resolver 의존성)까지
s01에서 구현하여 spec 자체가 부팅·마이그레이션으로 검증되도록 한다. 이후 모든 feature는 동일
인프라·계약을 재사용한다.

## Scope
- **In**: 전체 DB 스키마 마이그레이션, API 계약 카탈로그(엔드포인트·요청/응답 스키마 규약), 공통 에러
  모델, pydantic-settings `Settings` 로더, 세션 인증 의존성, 권한 resolver 인터페이스(owner/editor/viewer
  + admin bypass), 불변식 INV-1~12 문서화, 앱 부트스트랩(FastAPI 앱·라우터 조립 지점·health).
- **Out**: 각 feature의 실제 비즈니스 로직(로그인 처리, 문서 CRUD, bundle 전이 등)은 계약의 시그니처만
  두고 구현은 각 feature spec에서.

## Boundary Candidates
- 데이터 스키마 계약(마이그레이션) — 단일 소스
- API 계약 카탈로그 + Pydantic 스키마 규약 — 단일 소스
- 공용 인프라: Settings / 에러 모델 / 세션 인증 / 권한 resolver

## Out of Boundary
- feature별 엔드포인트 동작 구현(behavior)
- 프론트엔드 화면(계약 소비는 각 feature에서)

## Upstream / Downstream
- **Upstream**: 없음(프로젝트 루트 계약)
- **Downstream**: 모든 feature spec(s02~s14)과 모든 체크포인트(s04~s15)가 이 단일 소스를 참조/검증 기준으로 사용

## Existing Spec Touchpoints
- **Extends**: 없음(신규)
- **Adjacent**: 없음(최하위 계약)

## Constraints
FastAPI + MySQL 8, uv 실행, 설정 단일화(config.yml + .env + 공용 Settings), 물리 삭제 없음(INV-4)을
스키마·쿼리 기본 전제로. 산출물 한국어.
