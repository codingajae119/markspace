# Research & Design Decisions — s17-fe-auth

## Summary
- **Feature**: `s17-fe-auth`
- **Discovery Scope**: Extension (Wave-2 프론트 feature — s16 공통 레이어 소비, 백엔드 s02-auth 계약 소비).
  greenfield 아님: 소비 대상 인터페이스가 s16 design.md·s01 계약·백엔드 라우터로 이미 고정되어 있어 통합 중심
  경량 discovery.
- **Key Findings**:
  - 로그인 실패의 401은 **인증 만료가 아니라 자격 증명 거부**이므로, s16 전역 401 인터셉터의 세션 만료 리다이렉트
    경로를 타면 안 된다. 로그인 호출은 `apiClient`의 `skipAuthRedirect: true`로 수행해 인터셉터를 우회하고 `ApiError`를
    받아 인라인 표시해야 한다. 이것이 "두 번째 401 경로 금지" 가드레일의 핵심 구현 결정이다.
  - 백엔드는 미존재·비밀번호 불일치·비활동·삭제를 **단일 401 `unauthenticated`("Invalid credentials")**로 통일한다
    (계정 열거 방지, `auth/service.py` `_unauthenticated`). 따라서 프론트는 사유별 분기 메시지를 발명하지 않고 백엔드
    메시지를 그대로 표시한다.
  - 세션 write(로그인/로그아웃)의 반영은 s16 `useSession().refresh()` 단일 진입점으로만 수행한다. s16이 부트스트랩·
    `is_admin`·설정·미인증 전이를 소유하므로 s17은 자체 세션 상태를 신설하지 않는다.
  - 비밀번호 변경 실패는 **두 갈래 422**다: 현재 비밀번호 불일치 → 422 `unprocessable`(단일 message), 새 비밀번호
    정책 위반 → 422 `validation_error`(`field_errors`). 두 경우 모두 s16 `ErrorMessage`가 message·field_errors를
    동시에 처리하므로 별도 파싱이 불필요하다.

## Research Log

### 로그인 401을 전역 401 인터셉터와 분리하는 방법
- **Context**: s16 전역 401 인터셉터는 어떤 API 401이든 가로채 `returnTo` 보존 후 로그인으로 리다이렉트한다
  (s16 design.md "전역 401 인터셉터" flow). 그러나 **로그인 화면에서의 401**은 자격 증명 거부이며, 이미 로그인
  경로에 있으므로 리다이렉트가 무의미하고, 인터셉터의 "이미 login 경로면 루프 방지 → 미인증 전이" 분기를 타면
  사용자에게 실패 사유가 전달되지 않는다.
- **Sources Consulted**: `s16-fe-foundation/design.md`(ApiClient 계약 `skipAuthRedirect?: boolean`, 401 인터셉터
  flowchart의 "부트스트랩 /auth/me 등 401 리다이렉트 제외"), `backend/app/auth/service.py`
  (`authenticate` → `_unauthenticated` 401), `backend/app/auth/router.py`(`/auth/login` 공개·인증 의존성 없음).
- **Findings**:
  - s16 `apiClient`는 `RequestOptions.skipAuthRedirect`를 이미 제공한다(부트스트랩 `/auth/me`용으로 설계됨).
    로그인 호출에 동일 옵션을 지정하면 인터셉터가 리다이렉트하지 않고 `ApiError`를 throw한다.
  - throw된 `ApiError`(status 401, code `unauthenticated`, message "Invalid credentials")를 폼이 catch하여
    `ErrorMessage`로 인라인 표시한다.
- **Implications**: 로그인 useCase는 반드시 `apiClient.post("/auth/login", body, { skipAuthRedirect: true })`로
  호출한다. 이 결정이 REQ 2.3(전역 401과 이중화 금지)을 만족한다. 로그아웃·비밀번호 변경은 보호 엔드포인트이므로
  세션 만료 시 전역 인터셉터가 정상 동작해야 하며 `skipAuthRedirect`를 쓰지 않는다.

### 세션 반영을 refresh()로 통일
- **Context**: 로그인 성공 시 세션 컨텍스트가 새 사용자로 갱신되어야 보호 라우트·`is_admin` 파생 UI가 올바르게
  동작한다. 로그아웃 성공 시 미인증으로 전이되어야 한다.
- **Sources Consulted**: `s16-fe-foundation/design.md`(SessionProvider "로그인/로그아웃 write는 s17이 `refresh()`
  호출", `useSession(): SessionState & { refresh: () => Promise<void> }`).
- **Findings**: s16은 세션 write API를 노출하지 않고 재부트스트랩(`refresh()`)만 노출한다. 로그인 후 `refresh()`는
  `/auth/me`(→`/me/settings`)를 다시 읽어 authenticated로 확정하고, 로그아웃 후 `refresh()`는 `/auth/me` 401을 받아
  unauthenticated로 확정한다.
- **Implications**: s17은 `refresh()` 완료 후 네비게이션을 수행한다(로그인=`resolveReturnTo`, 로그아웃=`ROUTES.login`).
  자체 세션 저장·전역 상태를 만들지 않는다(REQ 5.1·5.2).

### 비밀번호 변경 실패의 두 갈래 422
- **Context**: `POST /auth/password`는 정상 시 204지만 실패 유형이 둘이다.
- **Sources Consulted**: `backend/app/auth/service.py`(`change_password`: 현재 비밀번호 불일치→422 `unprocessable`
  "Current password does not match"), `backend/app/auth/schemas.py`(`PasswordChangeRequest.new_password`
  `Field(min_length=8)` → 스키마 위반 시 s01 전역 핸들러가 422 `validation_error`+`field_errors`).
- **Findings**: 두 실패 모두 HTTP 422이나 code·형태가 다르다(`unprocessable` message vs `validation_error`
  field_errors). s16 `ErrorMessage(error: ApiError)`는 message와 field_errors를 함께 렌더하도록 설계되어 있어
  두 경우를 단일 컴포넌트로 표면화할 수 있다.
- **Implications**: 비밀번호 변경 화면은 실패 유형을 프론트에서 분기하지 않고 `ApiError`를 그대로 `ErrorMessage`에
  전달한다. 새 비밀번호 최소 8자 클라이언트 편의 검증은 선택적 안내이며 백엔드 422가 최종 강제(REQ 4.6).

### 라우트 등록 seam (feature → s16 프레임)
- **Context**: 로그인·비밀번호 변경 화면을 s16 라우터 프레임에 얹어야 하는데, 의존 방향은 config → shared → app →
  features 단방향이라 s16 `app`이 s17 `features`를 정적 import하지 않는 것이 원칙이다.
- **Sources Consulted**: `s16-fe-foundation/design.md`(Router "하위 spec 화면은 이 프레임의 자식 라우트로 등록만
  한다", "등록 지점" 제공), `structure.md`(feature는 공통 레이어 소비, feature 간 직접 import 금지).
- **Findings**: 라우터는 앱 조립의 **합성 루트(composition root)**이며, 프레임 하위 element로 feature 페이지를
  참조하는 것은 s16이 제공하는 "등록 지점" 계약에 해당한다. s17은 페이지 컴포넌트(`LoginPage`·`ChangePasswordPage`)와
  경로 대응(로그인=게스트 접근 프레임의 `ROUTES.login`, 비밀번호 변경=보호 프레임)만 제공하고 가드·프레임 로직은
  건드리지 않는다.
- **Implications**: s17은 라우트 프레임/가드를 재정의하지 않고 등록 지점에 페이지를 연결한다(REQ 1.1·4.1·6.1).
  feature는 다른 feature를 import하지 않는다(REQ 6.4).

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| feature 폴더 + 얇은 훅/서비스 (채택) | `features/auth`에 화면·훅·`authApi` 얇은 래퍼를 두고 s16 공통 레이어 소비 | steering 정렬(feature 단위), 교차 관심사 단일 소유 유지, 테스트 용이 | 없음(프로젝트 표준) | `structure.md` "feature는 자기 화면·훅·API 호출을 자기 폴더 안에" |
| 화면에서 직접 fetch·상태 관리 | 컴포넌트가 fetch/에러 파싱/세션 갱신을 직접 수행 | 파일 수 감소 | 401·에러·세션 처리가 화면마다 산발 → s16 단일 소유 위반, 드리프트 | 기각 |
| 전용 상태관리 라이브러리 도입 | Redux 등으로 인증 상태 보관 | 대규모 앱 확장성 | s16 세션 컨텍스트와 이중 소스, 과설계 | 기각(세션은 s16 Context 단일 소스) |

## Design Decisions

### Decision: 로그인 호출은 `skipAuthRedirect`로 전역 401 인터셉터 우회
- **Context**: 로그인 401(자격 거부)이 세션 만료 리다이렉트와 혼동되면 안 됨(REQ 2.1·2.3).
- **Alternatives Considered**:
  1. 기본 호출 후 인터셉터의 "login 경로 루프 방지" 분기에 의존 — 실패 사유가 인라인으로 전달되지 않음.
  2. `skipAuthRedirect: true`로 호출하여 `ApiError`를 직접 catch — 인라인 표시 가능.
- **Selected Approach**: 옵션 2. `apiClient.post("/auth/login", body, { skipAuthRedirect: true })`.
- **Rationale**: s16이 이미 제공하는 옵션을 재사용해 전역 401 경로와 이중화하지 않고 인라인 오류를 표면화.
- **Trade-offs**: 로그인 호출부만 예외적으로 옵션을 지정(문서화 필요). 로그아웃·비밀번호 변경은 기본 경로 유지.
- **Follow-up**: 통합 테스트로 로그인 401이 리다이렉트를 유발하지 않고 인라인 표시됨을 검증.

### Decision: 세션 반영은 `refresh()` 단일 진입점
- **Context**: s16이 세션 write를 노출하지 않고 재부트스트랩만 노출.
- **Selected Approach**: 로그인/로그아웃 성공 후 `useSession().refresh()` → 완료 후 네비게이션.
- **Rationale**: 세션 단일 소스 유지(REQ 5), `is_admin`/설정 파생을 s17이 중복 관리하지 않음.
- **Trade-offs**: 로그인 성공 시 `/auth/me`(+`/me/settings`) 재요청 1회 발생 — 세션 일관성을 위한 의도적 비용.
- **Follow-up**: 로그아웃 후 `refresh()`가 401→미인증 전이를 확정하는지 통합 테스트.

## Risks & Mitigations
- 로그인 401을 기본 경로로 호출해 리다이렉트 루프/무표시 발생 위험 — `skipAuthRedirect` 명시 + 통합 테스트로 고정.
- 비밀번호 변경 두 갈래 422를 프론트에서 분기하려는 과설계 위험 — `ApiError`를 `ErrorMessage`에 그대로 위임.
- feature가 s16 내부 구현에 결합할 위험 — 계약 인터페이스(`useSession`·`apiClient`·`ROUTES`·`ErrorMessage`)만
  소비하고 내부 파일을 import하지 않도록 경계 고정.
- s16 미구현 상태에서 s17 착수 위험 — Wave 순서(G: s16 완료 후 s17)를 전제. 계약 형태는 s16 design.md로 고정됨.

## References
- `.kiro/specs/s16-fe-foundation/design.md` — ApiClient(`skipAuthRedirect`)·SessionProvider(`refresh`)·Router
  (`ROUTES`·`buildLoginPath`·`resolveReturnTo`)·ErrorMessage·UI 프리미티브 계약.
- `.kiro/specs/s16-fe-foundation/requirements.md` — 보호/게스트 프레임·returnTo·세션 부트스트랩·에러 표시 계약.
- `.kiro/specs/s01-contract-foundation/design.md` — `ErrorResponse`/`ErrorCode`(401 unauthenticated·422
  validation_error/unprocessable)·field_errors 계약.
- `backend/app/auth/router.py`·`service.py`·`schemas.py` — `/auth/login`·`/auth/logout`·`/auth/me`·`/auth/password`
  요청/응답·에러 형태 ground truth.
- steering `tech.md`(Frontend 설정 단일화)·`structure.md`(feature 폴더·공통 레이어 단일 소유·라우팅)·
  `roadmap.md`(FE 계층 순서 s16 → {s17,s18,s19}).
