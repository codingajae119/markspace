# Research & Design Decisions — s18-fe-workspace

## Summary
- **Feature**: `s18-fe-workspace`
- **Discovery Scope**: New Feature (프론트 Wave-2 도메인 화면군, s16 공통 레이어 소비)
- **Key Findings**:
  - 백엔드 계약(s01 카탈로그 행 10~17)에는 **멤버 목록 조회 엔드포인트가 없다**(add/patch/delete 뮤테이션만).
    owner의 멤버 전체 열거는 계약이 지원하지 않으므로 발명 없이 뮤테이션 응답 기반 로컬 상태로 처리한다(S1).
  - `WorkspaceRead`에는 **현재 사용자 role 필드가 없다**. 비-admin의 현재 WS role 정확 조달 경로가 계약에 없어,
    admin은 세션 `is_admin`(INV-3)으로 게이팅하고 비-admin은 best-effort + 서버 403 권위로 처리한다(S2).
  - 사용자 디렉터리는 `GET /admin/users`(admin 전용)만 존재. 비-admin owner의 멤버 추가는 `user_id` 직접 입력을
    전제로 설계한다(S3). 세 seam 모두 cross-spec review·백엔드 후속에서 조정.

## Research Log

### 백엔드 워크스페이스·멤버 API 실제 시그니처
- **Context**: "API 형태를 발명하지 말고 계약·라우터에서 읽으라"는 지시에 따라 소비 대상 엔드포인트를 확정.
- **Sources Consulted**: `backend/app/workspace/router.py`·`admin_router.py`·`schemas.py`,
  `backend/app/admin_account/router.py`·`schemas.py`, `s01-contract-foundation/design.md` 카탈로그(행 5~17).
- **Findings**:
  - 워크스페이스: `POST /workspaces`(인증, 생성자 owner화)·`GET /workspaces`(인증, `Page[WorkspaceRead]`)·
    `GET /workspaces/{id}`(viewer)·`PATCH /workspaces/{id}`(owner)·`DELETE /workspaces/{id}`(owner, empty-only
    409)·멤버 `POST/PATCH/DELETE .../members[/{uid}]`(owner). **GET members 없음.**
  - admin 계정: `POST/GET /admin/users`·`PATCH /admin/users/{id}`·`POST /admin/users/{id}/password`(전부 admin).
  - admin 소유권: `POST /admin/workspaces/{id}/owner`(admin, `OwnerChangeRequest.new_owner_user_id`).
  - `WorkspaceRead` = id·created_at·updated_at·name·is_shareable·trash_retention_days (role 없음).
  - `MemberRead` = id·workspace_id·user_id·role(MemberRole 문자열). `UserRead`는 민감 필드 미노출.
- **Implications**: 어댑터(`workspaceApi`/`memberApi`/`adminApi`)는 이 경로·스키마와 정확히 일치. 멤버 열거·현재
  role은 계약 공백으로 seam 처리. 미러 타입에 role 필드를 얹지 않는다.

### s16 공통 레이어 소비 계약
- **Context**: owner/admin 게이팅과 서버 결선을 s16 유틸로만 수행해야 함(중복 구현 금지).
- **Sources Consulted**: `s16-fe-foundation/design.md`·`requirements.md`.
- **Findings**: `apiClient`(get/post/patch/del)·`useSession()`(status·user.is_admin·settings·refresh)·
  `Role`(VIEWER<EDITOR<OWNER)·`hasWorkspaceRole({currentRole,isAdmin,minimum})`·`<RequireRole minimum
  currentRole fallback>`·UI 프리미티브·보호 라우트 프레임·`ApiError`/`ErrorMessage` 제공. `RequireRole`은
  isAdmin을 `useSession`에서 취득.
- **Implications**: owner 패널은 `<RequireRole minimum=OWNER currentRole=주입>`; admin 화면군은 **s16 소유
  `RequireAdmin`**(세션 `is_admin`, WS role 아님, 재구현 금지). 현재 WS 앰비언트 컨텍스트
  (`CurrentWorkspaceProvider`·`useCurrentWorkspace()`·`CurrentWorkspaceContextValue`)·공용 `Page<T>`
  (`{items,total}`)·`WorkspaceRead` 미러·라우트 등록 메커니즘(`RouteModule[]`)도 **s16이 단일 소유**하며 이 spec은
  소비만 한다. 현재 role 값은 이 spec의 단일 role 소스가 s16 컨텍스트의 role 주입 seam에 공급한다.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| feature 폴더 + s16 소비 (선택) | 워크스페이스 도메인을 `src/features/workspace`에 캡슐화, 교차 관심사는 s16 소비(현재 WS 컨텍스트 포함) | steering 정렬, 경계 단순, 상향 노출 없음 | s16 role 주입 seam에 role 소스만 공급 | roadmap "교차관심 단일 소유 정정"과 일치 |
| 각 화면이 직접 fetch/게이팅 | 패널마다 fetch·역할 비교 | 단기 빠름 | 401·에러·역할 비교 드리프트, steering 위반 | 기각 |
| 전역 상태 라이브러리 도입 | Redux 등으로 현재 WS·목록 관리 | 대규모 확장 | s16이 Context로 충분 판단, 과설계 | 기각(s16 결정 계승) |

## Design Decisions

### Decision: 멤버 열거를 뮤테이션 응답 기반 로컬 상태로 처리(S1)
- **Context**: 계약에 GET 멤버 엔드포인트가 없어 owner가 기존 멤버 전체를 열거할 방법이 없음.
- **Alternatives Considered**:
  1. GET `/workspaces/{id}/members` 엔드포인트를 발명 — 지시(발명 금지) 위반. 기각.
  2. 뮤테이션 응답(`MemberRead`)으로 확인된 멤버만 로컬 상태로 관리하고 열거 한계를 UI에 명시 — 선택.
- **Selected Approach**: `useMemberActions`가 add/changeRole/remove 응답으로 로컬 멤버 상태를 갱신하고, 패널은
  "권위 있는 전체 멤버 열거가 아님"을 사용자에게 드러낸다.
- **Rationale**: 계약 범위를 넘지 않으면서 owner 조작(추가·변경·제거)은 완전히 지원.
- **Trade-offs**: 초기 진입 시 기존 멤버 목록을 보여주지 못함. 백엔드 GET 멤버 추가 시 해소(revalidation trigger).
- **Follow-up**: cross-spec review에서 백엔드 멤버 조회 엔드포인트 필요성 제기.

### Decision: 현재 WS role best-effort 조달(S2)
- **Context**: `WorkspaceRead`에 role이 없어 비-admin의 현재 role을 계약으로 확정 불가.
- **Alternatives Considered**:
  1. role 조회 엔드포인트 발명 — 기각.
  2. admin=`is_admin` 게이팅, 비-admin=조달 가능한 신호(생성 owner화·멤버 뮤테이션 role 에코)로 채우고 부재 시
     `null`, 서버 403 권위 — 선택.
- **Selected Approach**: s16 `CurrentWorkspaceContextValue.role: Role | null`(형태·기본값 null은 s16 소유)의
  값을 이 spec의 **단일 role 소스**(`MembershipRoleSource`)가 조달해 s16 provider의 role 주입 seam에 공급한다.
  admin은 게이팅이 `is_admin`으로 통과하여 role 값이 불필요; 비-admin은 부분 조달, 확정 불가 시 `null`(owner
  전용 UI 은닉). role 파생 로직은 이 단일 소스에만 존재한다(산발 금지).
- **Rationale**: 클라이언트 게이팅은 편의이고 서버가 최종 강제(s16 계약)이므로 false-negative는 안전. 컨텍스트
  형태는 s16이 단일 소유하되 값 조달만 s18 멤버십 경로가 담당하여 소유 경계가 명확.
- **Trade-offs**: 비-admin owner가 일부 상황에서 owner UI를 못 볼 수 있음(서버는 여전히 허용). 백엔드 role 노출 시 해소.
- **Follow-up**: 백엔드가 `WorkspaceRead`에 role 또는 멤버십 조회를 추가하면 정확 조달로 승격.

### Decision: admin 게이팅은 세션 is_admin 단일 출처(WS role 아님)
- **Context**: admin 콘솔·소유권 변경은 WS role 위계가 아니라 admin 전용 경로(`require_admin`).
- **Selected Approach**: **s16 소유 `RequireAdmin`**(`@/shared/auth`, `useSession().user.is_admin`, 재구현
  금지)을 소비해 admin 화면군을 감싼다. owner 전용 UI만 `RequireRole`(WS role) 사용. 둘을 혼동하지 않음.
- **Rationale**: 카탈로그상 행 5~9는 admin 전용, 행 13~17은 owner. INV-1(WS 단위 role)·INV-3(admin override)
  구분과 정합.
- **Trade-offs**: 게이팅 경로가 둘로 나뉘지만 각자 단일 출처라 드리프트 없음.

### Decision: 현재 WS 선택 지속·목록 로드는 s16 소유(이 spec 재구현 금지)
- **Context**: 후속 spec이 소비할 현재 WS가 reload 후에도 유지되어야 함. cross-spec review에서 현재 WS 앰비언트
  컨텍스트를 s16이 단일 소유하도록 정정됨.
- **Selected Approach**: 목록 로드(`GET /workspaces`)·현재 WS 선택 localStorage 영속·복원은 **s16
  `CurrentWorkspaceProvider`**가 소유한다. 이 spec 스위처는 `useCurrentWorkspace()`를 소비하고
  `selectWorkspace(String(id))`로 전환을 위임하며, 지속/복원 로직을 재구현하지 않는다.
- **Rationale**: 교차 관심사(현재 WS 컨텍스트)는 공통 레이어 단일 소유(steering)이며, s18은 관리 화면과 role
  값 조달만 담당하여 형제 spec 의존을 s16 단일 upstream으로 수렴시킨다.
- **Trade-offs**: 다중 탭 동기화 등 세부 정책은 s16 결정에 따름(이 spec 범위 밖).

## Risks & Mitigations
- **계약 공백(멤버 열거·현재 role)** — seam으로 명시, 발명 금지, 서버 403 권위, 백엔드 후속 시 revalidation.
- **현재 WS 컨텍스트 형태 변경이 하위 spec에 파급** — 컨텍스트 계약은 **s16이 단일 소유**하며 형태 변경 시
  s16이 s18/s19/s20/s22 재검증을 트리거한다. 이 spec은 그 계약에 바인딩하고 role 값만 조달한다.
- **owner/admin 게이팅 우회 시도** — 클라이언트 게이팅은 보안 경계 아님을 계약화, 서버 403/require_admin이 최종 강제.
- **s17와 동일 wave 병렬 생성으로 세션 write 경계 혼선** — 세션 변화 반영은 s16 `refresh()`만 소비, write는 s17 소유.

## References
- `s16-fe-foundation/design.md`·`requirements.md` — 공통 레이어 소비 계약(apiClient·useSession·게이팅·라우터 셸).
- `s01-contract-foundation/design.md` — API 카탈로그(행 5~17)·ErrorResponse·권한 resolver INV-1·2·3.
- `backend/app/workspace/router.py`·`admin_router.py`·`schemas.py` — 워크스페이스·멤버·소유권 실제 시그니처.
- `backend/app/admin_account/router.py`·`schemas.py` — admin 계정 실제 시그니처.
- steering `tech.md`·`structure.md`·`roadmap.md` — Frontend 결정·feature 소비·계층 순서.
