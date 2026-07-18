# Requirements Document

## Introduction

`s17-fe-auth`는 Notion-lite 프론트엔드의 **인증 화면·플로우 계층**을 소유한다. 폐쇄형 서비스 사용자가 UI에서
로그인/로그아웃하고 본인 비밀번호를 변경할 수 있게 하며, 로그인·로그아웃 결과를 공통 세션 컨텍스트에 반영한다.

이 spec은 세션 상태·라우팅·에러 처리를 **재구현하지 않는다**. 세션 컨텍스트·공용 API 클라이언트·전역 401
인터셉터·라우터 셸(보호/게스트 프레임, `returnTo` 보존/복귀)·공용 UI 프리미티브·에러 표시 유틸은 상위 공통
레이어 `s16-fe-foundation`이 단일 소유하며, 이 spec은 그것을 **소비만** 한다(Wave-2, s16 upstream). 각 인증
화면은 s16의 진입점(`useSession().refresh()`, `apiClient`, `buildLoginPath`/`resolveReturnTo`, `ROUTES`,
`ErrorMessage`, `Button`/`Spinner`)을 통해서만 공통 관심사에 접근한다.

검증 기준은 백엔드와 동일하게 `s01-contract-foundation`의 계약 단일 소스다. 소비 엔드포인트는 백엔드 s02-auth가
소유·구현하며 형태를 새로 발명하지 않는다:

- `POST /auth/login` — 요청 `LoginRequest`(`login_id`·`password`), 성공 200 `AuthUserRead`(`id`·`login_id`·
  `name`·`email`·`is_admin`). 실패는 미존재·비밀번호 불일치·비활동·삭제를 구분하지 않는 단일 401
  `unauthenticated`(계정 열거 방지, 메시지 "Invalid credentials").
- `POST /auth/logout` — 성공 204(세션 clear).
- `GET /auth/me` — 성공 200 `AuthUserRead`. (부트스트랩·`refresh()`는 s16 소유; s17은 `refresh()`만 호출.)
- `POST /auth/password` — 요청 `PasswordChangeRequest`(`current_password`·`new_password`, 최소 8자). 성공 204.
  실패는 현재 비밀번호 불일치 시 422 `unprocessable`(메시지 "Current password does not match"), 새 비밀번호
  정책(최소 길이) 위반 시 422 `validation_error`(`field_errors`).

오류 표면화는 공통 `ErrorResponse`(code·message·field_errors) 단일 계약을 재사용하며, 별도의 401/에러 경로를
추가하지 않는다. 산출물 언어는 한국어이고, 상위 근거로 `s16-fe-foundation`의 requirements.md·design.md,
`s01-contract-foundation`의 requirements.md·design.md, steering(`tech.md`·`structure.md`·`roadmap.md`),
백엔드 `backend/app/auth/router.py`·`backend/app/auth/service.py`·`backend/app/auth/schemas.py`를 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 로그인 화면과 플로우: `login_id`/`password` 제출 → 세션 확립 → `returnTo` 있으면 그 경로로 복귀, 없으면
    기본 홈으로 이동.
  - 로그인 실패 인라인 에러 표면화: 단일 401 `unauthenticated` 결과(자격 불일치·비활동·삭제 공통)를 로그인
    화면에서 인라인으로 표시. 세션 만료 리다이렉트가 아닌 폼 오류로 처리.
  - 로그아웃 액션: 세션 종료 후 로그인 화면으로 이동하고 세션 컨텍스트를 미인증으로 반영.
  - 본인 비밀번호 변경 화면: 현재/새 비밀번호 제출, 422(현재 비밀번호 불일치·새 비밀번호 정책 위반) 표면화.
  - 로그인/로그아웃 성공을 s16 세션 컨텍스트에 반영하기 위한 `refresh()` 호출 결선.
  - 인증 화면(로그인·비밀번호 변경)의 s16 라우터 프레임 등록(로그인=게스트 접근 가능 프레임, 비밀번호 변경=
    보호 프레임).
- **Out of scope (다른 spec 또는 상위 레이어가 소유)**:
  - 세션 컨텍스트 자체·`/auth/me` 부트스트랩·`is_admin`/설정 노출(s16 소유; s17은 `refresh()`·소비만).
  - 공용 API 클라이언트·전역 401 인터셉터·`returnTo` 보존/복귀 규약·라우터 셸·공용 UI 프리미티브·
    `ErrorMessage`(s16 소유).
  - self sign-up(회원가입) UI(REQ 6, 계약상 미제공)·비밀번호 분실 자가 재설정 UI(admin 소관, s18).
  - admin의 사용자 CRUD·비활동·삭제·재활성화·타인 비밀번호 재설정 콘솔(s18-fe-workspace).
  - 워크스페이스 권한 게이팅 데이터/화면(s18) 및 백엔드 인증 **동작**(s02-auth가 이미 소유·구현).
- **Adjacent expectations (이 spec이 상위 레이어에 기대하는 것)**:
  - s16이 `useSession()`(status·user·settings·`refresh()`), `apiClient`(`skipAuthRedirect` 옵션 포함),
    `ROUTES`·`buildLoginPath`·`resolveReturnTo`, `ErrorMessage`(ApiError 표시), 보호/게스트 라우트 프레임과
    등록 지점, `Button`/`Spinner` 프리미티브를 이미 제공한다.
  - 로그인 실패의 401은 s16 전역 401 인터셉터의 세션 만료 리다이렉트로 처리되지 않고, 호출부가
    `skipAuthRedirect`로 예외를 받아 인라인 표시할 수 있어야 한다(전역 401 경로와 이중화 금지).

## Requirements

### Requirement 1: 로그인 화면 및 세션 진입/복귀

**Objective:** As a 폐쇄형 서비스 사용자, I want UI에서 `login_id`/`password`로 로그인하고 진입하려던 위치로
복귀하기를, so that 보호 리소스에 접근하려다 로그인으로 리다이렉트된 뒤에도 흐름이 끊기지 않는다.

#### Acceptance Criteria

1. The system shall s16 게스트/공개 접근이 허용되는 로그인 경로(`ROUTES.login`)에 `login_id`·`password` 입력과
   제출 컨트롤을 가진 로그인 화면을 제공하고 s16 라우터 프레임에 등록한다.
2. When 사용자가 자격 증명을 제출하면, the system shall s16 공용 API 클라이언트로 `POST /auth/login`
   (본문 `login_id`·`password`)을 호출한다.
3. When 로그인이 성공(200 `AuthUserRead`)하면, the system shall s16 세션 컨텍스트를 재부트스트랩(`refresh()`)하여
   인증 상태를 확정한 뒤, 보존된 `returnTo` 경로로 복귀시키고 `returnTo`가 없으면 기본 홈 경로로 이동시킨다.
4. While 로그인 요청이 처리 중인 동안, the system shall 제출 컨트롤을 비활성화하고 진행 상태(로딩 인디케이터)를
   표시하여 중복 제출을 방지한다.
5. The system shall `returnTo` 경로의 해석을 s16 규약(`resolveReturnTo`)에만 위임하고, 복귀 경로 파싱/기본값
   결정 로직을 이 화면에서 중복 구현하지 않는다.

### Requirement 2: 로그인 실패 에러 표면화 (단일 401 계약)

**Objective:** As a 사용자, I want 로그인이 거부되면 그 사유를 로그인 화면에서 바로 확인하기를, so that 무엇을
고쳐야 하는지 알 수 있으면서도 세션 만료 리다이렉트 흐름과 혼동되지 않는다.

#### Acceptance Criteria

1. When `POST /auth/login`이 401 `unauthenticated`를 반환하면, the system shall 백엔드 공통 `ErrorResponse`의
   메시지를 로그인 화면에 인라인 오류로 표시하고, 다른 경로로 리다이렉트하지 않는다.
2. The system shall 자격 불일치·비활동 계정·삭제 계정을 구분하지 않는 단일 401 결과(계정 열거 방지)를 그대로
   수용하며, 프론트에서 사유별 분기 메시지를 발명하지 않는다.
3. While 로그인 화면에서 인증 실패 401을 처리하는 동안, the system shall s16 전역 401 인터셉터의 세션 만료
   리다이렉트가 이 실패에 발동하지 않도록 로그인 호출을 `skipAuthRedirect` 경로로 수행한다(전역 401 경로와
   이중화 금지, 리다이렉트 루프 방지).
4. When 401 이외의 오류(예: 422 요청 검증, 5xx)가 반환되면, the system shall 동일한 공통 에러 표시 유틸
   (`ErrorMessage`)로 오류를 표면화하고 별도 파싱 로직을 두지 않는다.
5. When 사용자가 실패 후 입력을 수정하여 다시 제출하면, the system shall 직전 오류 표시를 해제하고 새 요청
   결과에 따라 상태를 갱신한다.

### Requirement 3: 로그아웃 액션

**Objective:** As a 인증된 사용자, I want 로그아웃하여 세션을 종료하기를, so that 공용 환경에서 내 세션을 안전하게
닫고 로그인 화면으로 돌아간다.

#### Acceptance Criteria

1. The system shall 인증 영역에서 접근 가능한 로그아웃 액션(예: 버튼)을 제공한다.
2. When 사용자가 로그아웃을 실행하면, the system shall s16 공용 API 클라이언트로 `POST /auth/logout`을 호출한다.
3. When 로그아웃이 성공(204)하면, the system shall s16 세션 컨텍스트를 갱신(`refresh()`)하여 미인증 상태로
   전이시키고 로그인 경로(`ROUTES.login`)로 이동시킨다.
4. While 로그아웃 요청이 처리 중인 동안, the system shall 로그아웃 컨트롤을 비활성화하여 중복 실행을 방지한다.

### Requirement 4: 본인 비밀번호 변경 화면

**Objective:** As a 인증된 사용자, I want 본인 비밀번호를 UI에서 변경하기를, so that 현재 비밀번호 확인을 거쳐
안전하게 새 비밀번호로 교체한다.

#### Acceptance Criteria

1. The system shall 보호 라우트 프레임 하위에 현재 비밀번호·새 비밀번호 입력과 제출 컨트롤을 가진 본인 비밀번호
   변경 화면을 제공하고, 대상은 항상 현재 인증 사용자로 고정한다(타인 대상 지정 입력 미제공).
2. When 사용자가 제출하면, the system shall s16 공용 API 클라이언트로 `POST /auth/password`
   (본문 `current_password`·`new_password`)를 호출한다.
3. When 변경이 성공(204)하면, the system shall 성공 상태를 사용자에게 표시하고 입력 필드를 안전한 초기 상태로
   정리한다.
4. If 현재 비밀번호가 일치하지 않아 422 `unprocessable`가 반환되면, the system shall 백엔드 메시지를 공통 에러
   표시 유틸로 표면화하고 새 비밀번호를 적용하지 않는다.
5. If 새 비밀번호가 정책(최소 8자)을 위반하여 422 `validation_error`가 반환되면, the system shall
   `ErrorResponse.field_errors`를 공통 에러 표시 유틸로 표면화한다.
6. The system shall 새 비밀번호 최소 길이(8자)를 제출 전 클라이언트 편의 검증으로 안내할 수 있으나, 정책의
   최종 강제는 백엔드 계약(422)이 소유함을 전제하고 프론트 검증을 보안 경계로 취급하지 않는다.

### Requirement 5: 세션 컨텍스트 연동 (s16 소비)

**Objective:** As a 하위 프론트 feature 구현자, I want 로그인/로그아웃 결과가 공통 세션 컨텍스트에 일관되게
반영되기를, so that 다른 화면이 인증 상태를 중복 조회하지 않고 최신 세션을 소비한다.

#### Acceptance Criteria

1. When 로그인 또는 로그아웃이 성공하면, the system shall 세션 상태 반영을 s16 세션 컨텍스트의 `refresh()`
   진입점 호출로만 수행하고, 자체 세션 저장소·전역 상태를 신설하지 않는다.
2. The system shall 현재 사용자·`is_admin`·설정 등 세션 파생 데이터를 이 spec에서 별도로 조회·보관하지 않고
   `useSession()`을 통해서만 참조한다.
3. The system shall 인증 상태(로딩/인증됨/미인증) 판정과 보호 라우트 리다이렉트 규칙을 s16 라우터 셸에 위임하고,
   이 spec은 화면·플로우와 `refresh()`·네비게이션 결선만 담당한다.

### Requirement 6: 소비 경계 및 미제공 범위

**Objective:** As a 프로젝트 유지보수자, I want s17이 공통 관심사를 재구현하지 않고 인증 화면만 소유하기를,
so that 라우팅·401·세션·에러 처리가 단일 소유되어 드리프트가 방지되고 폐쇄형 정책이 유지된다.

#### Acceptance Criteria

1. The system shall 라우팅 정의·전역 401 처리·세션 컨텍스트·공용 API 클라이언트·에러 표시 유틸을 이 spec에서
   재구현하지 않고 s16 공통 레이어를 통해서만 소비한다.
2. The system shall self sign-up(회원가입) 화면을 제공하지 않는다(폐쇄형 서비스 정책, 계약상 미제공).
3. The system shall 비밀번호 분실 자가 재설정 화면을 제공하지 않으며, 타인 계정 비밀번호 재설정·계정 생명주기
   관리는 s18-fe-workspace(admin 콘솔) 범위임을 전제한다.
4. The system shall auth feature 폴더(`src/features/auth`) 내부에 자기 화면·훅·API 호출을 두고 다른 feature를
   직접 import 하지 않는다(교차 관심사는 공통 레이어 경유).
5. The system shall 클라이언트 측 처리를 UI 흐름·입력 편의로 한정하고, 인증·상태 게이트의 최종 강제는 백엔드
   계약이 소유함을 전제한다(클라이언트 검증은 보안 경계가 아님).
