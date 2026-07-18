# Implementation Plan — s17-fe-auth

> 인증 화면·플로우 feature spec(프론트 Wave-2, `s16-fe-foundation` 소비). 모든 프론트 명령은 `frontend/`에서 실행.
> 산출물 언어 한국어, 코드 식별자는 영어. 컴포넌트 파일 PascalCase·훅 camelCase(`structure.md`). TypeScript strict,
> `any` 금지. **교차 관심사 재구현 금지**: 세션 컨텍스트(`useSession`·`refresh`)·공용 API 클라이언트(`apiClient`,
> `skipAuthRedirect` 옵션 포함)·전역 401 인터셉터·라우터 셸(보호/게스트 프레임·`ROUTES`·`resolveReturnTo`)·에러 표시
> (`ErrorMessage`·`ApiError`)·UI 프리미티브(`Button`·`Spinner`)는 모두 s16 소유이며 소비만 한다. `features/auth/*`는
> s16 `app`·`shared`만 import하고 다른 feature를 import하지 않는다. 백엔드 계약(`/auth/login` 401 단일·`/auth/logout`
> 204·`/auth/password` 두 갈래 422)은 `backend/app/auth/*`가 ground truth이며 형태를 발명하지 않는다.
> **핵심 결정**: 로그인 401(자격 거부)은 `skipAuthRedirect: true`로 전역 401 인터셉터를 우회해 인라인 표시하고,
> 세션 반영은 `refresh()` 단일 진입점으로만 수행한다.

- [x] 1. Foundation: auth feature 스캐폴드 · API 래퍼
- [x] 1.1 auth feature 폴더 스캐폴드 및 authApi 얇은 래퍼 구현 (P)
  - `frontend/src/features/auth/` 폴더 구조(api·hooks·components·pages) 생성. `api/authApi.ts`에 s16 `apiClient`를
    위임하는 `login`/`logout`/`changePassword`를 정의. 응답 사용자 타입은 s16 정본 `AuthUser`
    (`import type { AuthUser } from "@/app/session";`)를 재사용하고 로컬 재선언하지 않는다(drift 방지);
    요청 입력 타입(login/changePassword 본문)만 로컬 정의. `login`은 반드시
    `apiClient.post<AuthUser>("/auth/login", input, { skipAuthRedirect: true })`로, `logout`은
    `apiClient.post<void>("/auth/logout")`, `changePassword`는 `apiClient.post<void>("/auth/password", input)`로 호출.
    fetch·에러 파싱·base URL·credentials를 자체 구현하지 않고 s16에 위임. 다른 feature import 금지.
  - 관찰 가능 완료: `authApi.login`이 `skipAuthRedirect:true` 옵션과 `login_id`·`password` 본문으로 `/auth/login`을
    호출하고 `AuthUser`를 반환하며, `logout`/`changePassword`가 각각 `/auth/logout`·`/auth/password`를 기본 경로로
    호출함을 단위 테스트(apiClient 모킹)로 확인. `tsc --noEmit` strict 통과, `any` 미사용.
  - _Requirements: 1.2, 3.2, 4.2, 6.1, 6.4_
  - _Boundary: authApi_

- [x] 2. Core: 인증 플로우 훅
- [x] 2.1 useLogin 훅 구현 (로그인 → refresh → returnTo 복귀 · 실패 인라인) (P)
  - `hooks/useLogin.ts`: `submit(credentials)` 호출 시 `authApi.login` → 성공하면 `useSession().refresh()`로 세션
    확정 후 `resolveReturnTo(location.search)` 경로로 `navigate`(없으면 s16 기본 홈). 실패 시 `ApiError`를 `error`
    상태에 보관하고 네비게이션하지 않음. 재제출 시 직전 오류 해제. 진행 중 `submitting`으로 중복 제출 방지. 복귀 경로
    파싱은 s16 `resolveReturnTo`에만 위임(중복 구현 금지).
  - 관찰 가능 완료: 성공 시 `refresh()` 호출 후 `resolveReturnTo` 결과 경로로 네비게이션(returnTo 없으면 기본 홈),
    401 실패 시 `error` 세팅·네비게이션 없음, 재제출 시 `error` 초기화, 진행 중 `submitting=true`임을 단위 테스트
    (useSession·authApi·navigate 모킹)로 확인.
  - _Requirements: 1.2, 1.3, 1.4, 1.5, 2.1, 2.3, 2.5, 5.1_
  - _Boundary: useLogin_
  - _Depends: 1.1_
- [x] 2.2 useLogout 훅 구현 (로그아웃 → refresh → login 이동) (P)
  - `hooks/useLogout.ts`: `submit()` 호출 시 `authApi.logout` → `useSession().refresh()`로 미인증 전이 → `navigate
    (ROUTES.login)`. 진행 중 `submitting`으로 중복 실행 방지. 세션 반영은 `refresh()` 단일 진입점으로만 수행하고
    자체 세션 저장소를 만들지 않음.
  - 관찰 가능 완료: `logout()` → `refresh()` → `navigate(ROUTES.login)` 순서가 지켜지고 진행 중 `submitting=true`임을
    단위 테스트(모킹)로 확인.
  - _Requirements: 3.2, 3.3, 3.4, 5.1_
  - _Boundary: useLogout_
  - _Depends: 1.1_
- [x] 2.3 useChangePassword 훅 구현 (변경 제출 · 성공/두 갈래 422 상태) (P)
  - `hooks/useChangePassword.ts`: `submit({current_password,new_password})` 호출 시 `authApi.changePassword` →
    204면 `succeeded=true`·입력 정리 신호, 422(`unprocessable` 현재 불일치 / `validation_error` 정책 위반)면 `ApiError`를
    `error`에 세팅. 실패 유형을 프론트에서 분기하지 않고 `ApiError`를 그대로 노출. 대상은 항상 현재 사용자(타인 지정
    인자 없음).
  - 관찰 가능 완료: 204→`succeeded=true`·`error=null`, 422 unprocessable/validation_error→`error`에 해당 `ApiError`가
    담기고 `succeeded=false`임을 단위 테스트로 확인.
  - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6_
  - _Boundary: useChangePassword_
  - _Depends: 1.1_

- [x] 3. UI: 인증 화면·컴포넌트
- [x] 3.1 LoginForm · LoginPage 구현 (자격 입력 · 인라인 에러 · 로딩) (P)
  - `components/LoginForm.tsx`: `login_id`·`password` 입력과 제출 컨트롤. 제출 시 `useLogin().submit`, 진행 중 제출
    비활성 + `Spinner`, `error`를 s16 `ErrorMessage`로 인라인 표시(401 자격/비활동/삭제 공통 메시지·기타 4xx/5xx 동일
    유틸). `pages/LoginPage.tsx`: 게스트 접근 프레임 대상 element로 `LoginForm` 배치. 프레임/가드는 s16 소유(재정의
    금지). 프리미티브(`Button`·`Spinner`)·`ErrorMessage`는 s16 소비만.
  - 관찰 가능 완료: 로그인 화면이 `login_id`·`password` 입력·제출을 렌더하고, 제출 중 컨트롤이 비활성화되며, 401 실패
    시 `ErrorMessage`가 백엔드 메시지를 인라인 표시하고 리다이렉트가 발생하지 않음을 컴포넌트 테스트로 확인.
  - _Requirements: 1.1, 1.4, 2.1, 2.2, 2.4, 2.5_
  - _Boundary: LoginForm, LoginPage_
  - _Depends: 2.1_
- [x] 3.2 ChangePasswordPage 구현 (현재/새 비밀번호 · 성공/오류 표면화) (P)
  - `pages/ChangePasswordPage.tsx`: 보호 프레임 대상 element. 현재 비밀번호·새 비밀번호 입력(대상은 현재 사용자 고정,
    타인 지정 없음)과 제출. `useChangePassword` 소비: 성공 시 성공 표시 + 입력 초기화, `error`를 `ErrorMessage`로 표시
    (422 message·field_errors 모두). 새 비밀번호 8자 클라이언트 편의 검증은 선택적 안내이며 백엔드 422가 최종 강제.
  - 관찰 가능 완료: 성공(204) 시 성공 메시지 표시·입력 초기화, 현재 비밀번호 불일치(422 unprocessable) 시 message
    표시, 새 비밀번호 정책 위반(422 validation_error) 시 field_errors 표시됨을 컴포넌트 테스트로 확인.
  - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6_
  - _Boundary: ChangePasswordPage_
  - _Depends: 2.3_
- [x] 3.3 LogoutButton 구현 (트리거 · 진행 중 비활성) (P)
  - `components/LogoutButton.tsx`: `useLogout().submit`를 트리거하는 액션 컨트롤(s16 `Button` 소비). 진행 중 비활성.
    배치 위치(레이아웃/헤더)는 소비 화면이 결정하므로 재사용 가능한 단일 버튼 컴포넌트로 제공.
  - 관찰 가능 완료: 클릭 시 `useLogout().submit`가 호출되고 진행 중 버튼이 비활성화됨을 컴포넌트 테스트로 확인.
  - _Requirements: 3.1, 3.4_
  - _Boundary: LogoutButton_
  - _Depends: 2.2_

- [x] 4. Integration: 라우트 등록 결선
- [x] 4.1 authRoutes 등록 결선 (로그인=게스트 프레임 · 비밀번호 변경=보호 프레임)
  - `routes.tsx`: 로그인 페이지를 s16 게스트 접근 가능 프레임의 `ROUTES.login`에, 비밀번호 변경 페이지를 s16 보호
    프레임 하위 경로에 대응시키는 라우트 정의를 제공하고 s16 라우터 등록 지점에 결선. 경로 상수는 s16 `ROUTES` 사용
    (하드코딩 금지). 프레임/가드/`returnTo` 규약은 재정의하지 않음. 이는 여러 컴포넌트를 s16 프레임에 결합하는 명시적
    통합 작업.
  - 관찰 가능 완료: 미인증 상태에서 `ROUTES.login` 진입 시 로그인 화면이 게스트 프레임으로 렌더되고, 비밀번호 변경
    경로가 보호 프레임(미인증 시 로그인 리다이렉트) 하위로 등록되며, s16 프레임/가드 코드가 변경되지 않았음을 확인.
  - _Requirements: 1.1, 4.1, 6.1, 6.2, 6.3_
  - _Boundary: authRoutes (s16 라우터 등록 지점)_
  - _Depends: 3.1, 3.2_

- [x] 5. 검증: 플로우 통합/UI 테스트 및 타입/경계 확인
- [x] 5.1 인증 플로우 통합 테스트 (로그인 복귀 · 로그인 401 인라인 · 로그아웃 · 비번변경 422)
  - 로그인 성공 → 세션 authenticated 전이 → `returnTo` 복귀(없으면 기본 홈); 로그인 401 → 전역 401 리다이렉트 미발동·
    `ErrorMessage` 인라인 표시; 로그아웃 → 204 → unauthenticated → 로그인 경로 이동; 비밀번호 변경 → 현재 불일치 422
    message / 새 비밀번호 8자 미만 422 field_errors 표면화를 s16 세션·라우터·apiClient와 결합해(모킹 최소화) 검증.
  - 관찰 가능 완료: 위 4개 플로우 통합 테스트가 통과하고, 특히 로그인 401이 리다이렉트를 유발하지 않고 인라인
    표시됨(skipAuthRedirect 경로)을 명시적으로 확인.
  - _Requirements: 1.3, 2.1, 2.3, 3.3, 4.4, 4.5, 5.1_
  - _Boundary: useLogin, useLogout, useChangePassword, LoginForm, ChangePasswordPage_
  - _Depends: 4.1_
- [x] 5.2 미제공 범위·경계·타입 확인 (self sign-up/재설정 부재 · feature 격리 · strict)
  - self sign-up·비밀번호 분실 자가 재설정 진입점이 UI에 존재하지 않음을 확인. `features/auth/*`가 s16 `app`·`shared`
    만 import하고 다른 feature를 import하지 않음을 확인. `tsc --noEmit`(strict) 통과·`any` 미사용 확인.
  - 관찰 가능 완료: 회원가입/분실 재설정 링크·화면이 없음을 UI 테스트로 확인하고, import 경계 검사(다른 feature 참조
    0건)와 strict 타입체크가 통과함을 확인.
  - _Requirements: 6.2, 6.3, 6.4, 6.5_
  - _Boundary: (전체 feature/auth)_
  - _Depends: 4.1_

## Implementation Notes

- **s16 소비 경로 실측 정정(전 태스크)**: 정본 `AuthUser`는 배럴 부재로 `@/app/session/SessionProvider`에서 import(디자인 문서의 `@/app/session`는 미존재). `verbatimModuleSyntax:true`라 타입 전용은 `import type` 강제.
- **task 4.1 — s16 라우터 seam 수정(사용자 승인)**: s16 `createAppRoutes`가 `/login`·`/share/:token` 플레이스홀더를 배열 선두에 하드코딩하고 additive `guestRoutes`를 뒤에 append하는 구조라, append된 실제 `LoginPage`가 플레이스홀더에 가려져 렌더되지 않음을 probe로 확인. 사용자 승인 하에 `createAppRoutes`를 "동일 path의 additive guest 라우트가 built-in 플레이스홀더를 치환"하도록 최소 수정(가드/scope/returnTo/`ProtectedRoute`/`createAppRouter` 불변). 등록은 `main.tsx` `featureRouteModules = authRoutes` seam으로 결선. 기존 s16 router.test 4개 불변 통과 + 치환 테스트 1개 추가. 비밀번호 변경 경로는 s17 소유 상수 `CHANGE_PASSWORD_PATH="/settings/password"`(라우트 객체는 보호 레이아웃 하위 상대경로 `"settings/password"`). 이 seam은 s22(`/share/:token` 실제 뷰)도 동일하게 재사용.
- **컴포넌트 "초기화" 테스트 함정(task 3.2)**: 입력 클리어 같은 전이 동작 테스트는 먼저 비어있지 않은 값을 주입해 증명해야 함(정적 succeeded=true + 빈 입력은 no-op 통과 → mutation으로 적발됨). 후속 UI 테스트도 전이 전 상태를 명시적으로 세팅할 것.
