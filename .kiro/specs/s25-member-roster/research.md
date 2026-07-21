# Gap Analysis — s25-member-roster

> 요구사항(requirements.md)과 기존 코드베이스 간 구현 격차 분석. 설계 단계 의사결정을 위한 정보 제공 문서이며 최종 구현 선택을 확정하지 않는다.
>
> 조사 시점 상태: requirements 생성됨(미승인). 계약 공백 **S1**(멤버 목록 조회 GET 부재) 정식 해소가 목표.

## 분석 요약 (Analysis Summary)

- **본질은 신규 아키텍처가 아니라 "seam 재사용 + 1개 결정적 divergence"**: s23 `assignable-users` 엔드포인트가 라우팅·게이팅·Page 봉투·결정적 순서·narrow 읽기 모델·통합 테스트 하네스까지 거의 완전한 템플릿을 제공한다. 백엔드는 이 패턴의 **확장**으로 성립한다.
- **결정적 divergence(Req 1.5)**: assignable-users는 "활성 + 비-멤버"로 **필터링**한다. 로스터는 반대로 **비활성·삭제 상태 멤버까지 전부 포함**해야 한다. 템플릿을 무비판 복사하면 이 기능이 존재해야 할 이유(기존 멤버 전량 노출)를 스스로 깬다. → 쿼리는 소프트삭제 필터를 적용하지 **않는** inner-join이어야 한다.
- **읽기 모델 공백(Missing)**: 기존 `MemberRead`(id/workspace_id/user_id/role, **이름·이메일 없음**)도, `AssignableUserRead`(id/name/email, **role 없음**)도 로스터 요구(Req 1.2: user_id·이름·이메일·role)를 만족하지 못한다. `User`⋈`WorkspaceMember.role` 조인을 담는 **신규 narrow 읽기 모델**이 필요하다.
- **프론트 최대 난점은 조회가 아니라 단일 소스화(Req 4)**: 어댑터·로드 훅은 `useAssignableUsers` 미러링으로 저위험이다. 진짜 설계 결정은 서버 로스터와 `useMemberActions` 세션 뮤테이션 델타를 **하나의 목록으로 재조정(reconcile)**하는 소유권 모델과, 이름 캡처 우회(`nameById`) 제거(Req 3.7)다.
- **접근 통제·anti-enumeration·401/403·admin override는 전량 재사용**: `require_ws_role(Role.OWNER)` 게이트가 editor/viewer/비-멤버/미존재 워크스페이스를 게이트 단계에서 403으로 통일 처리하고, `has_at_least`의 admin 단락으로 INV-3를 무료로 만족한다. 재구현 불필요.

---

## 1. 현재 상태 조사 (Current State Investigation)

### 1.1 백엔드 재사용 자산

| 자산 | 위치 | 재사용 포인트 |
|---|---|---|
| **템플릿 엔드포인트** | `backend/app/workspace/router.py:145-165` `GET /workspaces/{id}/assignable-users`, `response_model=Page[AssignableUserRead]` | 라우팅·게이팅·Page 봉투·limit/offset·delegate 구조 그대로 미러 |
| **owner 게이트** | `backend/app/workspace/dependencies.py` `require_ws_role(Role.OWNER)` (s01 core `app/common/permissions.py` 위임 어댑터, path param `{id}`→`workspace_id` 브리지) | `Depends(require_ws_role(Role.OWNER))` 그대로 사용 |
| **admin override(INV-3)** | `app/common/permissions.py` `WorkspaceRoleResolver.has_at_least` — `if ctx.is_admin: return True` | 게이트에 내장, 별도 코드 불필요 |
| **anti-enumeration** | 게이트가 존재검사보다 **먼저** 실행 → 비-멤버·미존재 WS 모두 `_forbidden()` 403 | 별도 존재검사 금지(404 노출 금지) |
| **단일 401 세션** | `app/common/auth.py` `get_current_user` → `AuthContext{user_id, is_admin}`; SESSION_USER_KEY="user_id" 미러링 | `AuthContext`만 소비 |
| **Page 봉투 / 읽기 모델 베이스** | `backend/app/schemas/base.py` `Page[T]{items,total}`, `ORMReadModel(from_attributes=True)` | 선언 필드만 직렬화 → narrow 자동 |
| **조인 패턴 선례** | `repository.py` `WorkspaceRepository.list_for_user` = `select(Workspace, WorkspaceMember.role).join(...)` + 별도 `func.count()` | 반전하여 `select(User, WorkspaceMember.role).join(...).where(ws_id).order_by(User.id)` |
| **(entity, role)→읽기모델 주입 idiom** | `service.py` `WorkspaceService._to_read(ws, role)` = `model_validate(...).model_copy(update={"role": ...})` | 로스터 행 조립에 미러 |
| **조립 seam** | `backend/app/main.py` `create_app()` 이미 `workspace_router` include (`API_V1_PREFIX="/api/1.0"`) | 신규 라우터 파일·마이그레이션 불필요, `router.py`에 라우트 추가만 |

**데이터 모델(노출 가부 판정용)** — `backend/app/models/user.py` `User`: 노출 가능 `id·name·email(nullable)` / **은닉 필수** `login_id·password_hash·is_admin·is_active·is_deleted·created_at·updated_at`(Req 2.6). `backend/app/models/workspace.py` `WorkspaceMember{id, workspace_id, user_id, role}` — 타임스탬프 없음, unique `(workspace_id,user_id)`. INV-4(물리삭제 없음)로 멤버십↔user FK dangling 없음 → Req 1.5(비활성·삭제 멤버 포함) 조인이 안전.

**MemberRole 이중 타입 주의**: API 문자열 `app/workspace/schemas.py:47` `MemberRole(str,Enum)` vs 게이팅 계층 `app/common/permissions.py:29` `Role(IntEnum)`. 로스터 응답 role은 `MemberRole`, 게이트 인자는 `Role`.

### 1.2 프론트 재사용 자산

| 자산 | 위치 | 재사용 포인트 |
|---|---|---|
| **소비 대상 화면** | `frontend/src/features/workspace/components/MemberManagementPanel.tsx` — 내부 `MemberManagementContent({workspaceId})` | 렌더 소스 교체 지점 |
| **현재 멤버 소스(문제 지점)** | 동 파일: `useMemberActions().members`(=`MemberRead[]`, 이름·이메일 없음) + 로컬 `nameById` Map(add 시점 이름 캡처 우회) | Req 3.7로 우회 제거 대상 |
| **뮤테이션 훅** | `hooks/useMemberActions.ts` — `members`는 뮤테이션 응답만으로 채워짐(add append/changeRole replace/remove filter) | Req 4 재조정 입력 |
| **템플릿 어댑터** | `api/assignableUserApi.ts` `listAssignable(wsId,{limit,offset}): Promise<Page<AssignableUser>>` (query string 조립, `apiClient.get`) | 로스터 GET 어댑터 미러 |
| **템플릿 로드 훅** | `hooks/useAssignableUsers.ts` — `{status:"loading"\|"ready"\|"error", users, total, error, reload}`; null 가드(`status = wsId===null?"ready":"loading"`), `loadingRef`/`mountedRef`, `[workspaceId]` 재fetch | `useWorkspaceMembers` 미러(Req 3.1·3.3·3.6) |
| **공용 apiClient** | `shared/api/client.ts` — baseURL(`config.ts`), `credentials:"include"`, 전역 401 인터셉터, `get<T>(path)` | 그대로 소비 |
| **owner 게이팅** | 화면: `useMembershipRoleSource().roleFor(wsId)` + `<RequireRole minimum={Role.OWNER} currentRole=…>` (s18/s24) — `useCurrentWorkspace().role`은 하드코딩 null이라 사용 금지 | 이미 패널에 존재, 재사용 |
| **Page<T> / 어댑터 규약** | `shared/types/page.ts` `Page<T>{items,total}`; feature `api/*.ts`는 얇은 free-function+단일 named object, 타입은 `./types`(백엔드 미러) | `memberApi`에 `list` 추가가 자연스러움 |

### 1.3 확인된 부재 (greenfield)

- `useWorkspaceMembers`/`listMembers`/roster 로더 — **전무**(grep 무결과).
- `memberApi`(`api/memberApi.ts`)는 add/changeRole/remove만 — **GET/list 없음**.
- 백엔드 멤버십→user 조인 리스트 리포지토리 메서드 — **없음**(list_for_user는 user→workspace 방향).
- 이름·이메일·role을 함께 담는 읽기 모델 — **없음**.

---

## 2. 요구사항-자산 매핑 (Requirement-to-Asset Map)

태그: **Reuse**(그대로 재사용) · **Extend**(기존 패턴 확장/신규 추가) · **Missing**(부재, 신설 필요) · **Constraint**(기존 아키텍처 제약) · **Research**(설계 단계 조사 필요)

| 요구 | 자산/판정 |
|---|---|
| 1.1 owner 멤버 집합 반환 | **Extend** — 템플릿 라우트+서비스 미러 |
| 1.2 각 항목 user_id·이름·이메일·role(이메일 null 허용) | **Missing** — 신규 읽기 모델(`User` id/name/email ⋈ `WorkspaceMember.role`). `MemberRead`/`AssignableUserRead` 둘 다 부적합 |
| 1.3 요청자 owner 포함 전체 멤버십 | **Reuse** — inner-join이 owner 행 포함(제외 로직 없음) |
| 1.4 페이지 초과 시에도 전체 집합+전체 개수 노출 | **Research** — 전체 로스터 노출 정책(대형 default limit vs 클라이언트 페이지네이션 루프 vs limit 無). Page.total은 재사용 |
| 1.5 비활성·삭제 멤버도 role과 함께 포함 | **Constraint/divergence** — assignable의 활성 필터를 **적용 금지**. 소프트삭제 필터 없는 inner-join. INV-4로 FK 안전 |
| 1.6 결정적·안정 순서 반복 일관 | **Reuse** — `order_by(User.id)` + 동일필터 `func.count()` 선례 |
| 2.1 무세션 → 401 | **Reuse** — `get_current_user` 단일 401 |
| 2.2 editor/viewer → 403 | **Reuse** — OWNER 게이트가 자동 403 |
| 2.3 비-멤버 → 403 | **Reuse** — `resolve`→None→`_forbidden()` |
| 2.4 미존재 WS → 403(404 금지) | **Reuse** — 게이트 선행, 존재검사 없음 |
| 2.5 admin override 허용(INV-3) | **Reuse** — `has_at_least` admin 단락 |
| 2.6 login_id·password·상태플래그·타임스탬프 비노출 | **Reuse** — `ORMReadModel` 선언필드만 직렬화 |
| 3.1 마운트/WS 변경 시 서버 조회 | **Extend** — `useAssignableUsers`의 `[workspaceId]` effect 미러 |
| 3.2 재로그인 새 세션 서버 시드 | **Extend** — 마운트 시 서버 fetch가 로컬 이력 무관 시드 |
| 3.3 로딩 상태 | **Reuse** — `status:"loading"` |
| 3.4 실패 오류 상태 | **Reuse** — `status:"error"` + `toApiError` |
| 3.5 성공·빈 로스터 → 빈 상태 | **Reuse** — `items:[]`,`total:0` |
| 3.6 WS 미선택 시 조회 안 함·안정 비로딩 | **Reuse** — null 가드(`status="ready"`, load no-op) |
| 3.7 이름=서버 값, add 시점 캡처 우회 미의존 | **Missing→해소** — 읽기 모델 name → `nameById` 제거 |
| 4.1 세션 뮤테이션 로스터에 일관 반영(중복없이 add·제거 제외·역할반영) | **Research/Missing** — 재조정 로직 신설 |
| 4.2 단일 목록 통합(분리 금지) | **Research** — 단일 소스 소유권 모델 |
| 4.3 재로드 시 서버 현재상태 재동기화 | **Extend** — `reload()` 미러 |

---

## 3. 구현 접근 옵션 (Implementation Approach Options)

### Option A — 기존 workspace feature 내 확장 (BE·FE 모두) ✅ 권장

- **백엔드**: `router.py`에 `GET /workspaces/{id}/members` 추가(뮤테이션 POST와 동일 경로·다른 메서드 → 충돌 없음), `MembershipRepository.list_members`(inact/deleted 미필터 inner-join+count) 신설, 신규 `MemberRosterRead` 읽기 모델, `MembershipService.list_members` 추가. 신규 라우터 파일·마이그레이션 불필요.
- **프론트**: `memberApi.list(id,{limit,offset}): Promise<Page<MemberRosterRow>>` 추가, `useWorkspaceMembers`(=`useAssignableUsers` 클론) 신설, `MemberManagementContent`가 이를 렌더 소스로 채택하고 `nameById` 제거.
- **Trade-offs**: ✅ 검증된 assignable 패턴·테스트 하네스 최대 재사용, 파일 최소 신설, 규약 일관 · ✅ 격리 테스트 용이(리포지토리·서비스·라우터 각 계층 선례 존재) · ❌ `router.py`/`memberApi.ts` 크기 증가(경미) · ❌ Req 4 재조정을 패널에 얹으면 패널 복잡도 상승(→ 훅으로 캡슐화 권장).

### Option B — 독립 member-roster 모듈 신설 (BE 신규 router 파일 / FE `memberRosterApi`+전용 훅)

- **Trade-offs**: ✅ 관심사 분리 명시 · ❌ assignable/workspace feature에 이미 동종 패턴이 있어 **과분리**. 조립 seam·타입·테스트 하네스를 중복 구성해야 하고 규약 일관성이 오히려 저하. 이 규모(단일 GET+narrow 모델)에는 비용 대비 이득 낮음.

### Option C — 하이브리드(BE 확장 + FE 단일소스 재조정 계층 신설)

- **조합**: 백엔드는 Option A(확장). 프론트는 어댑터·로드 훅은 미러(확장)하되, **Req 4 단일 소스화만 별도 재조정 계층**으로 분리 — 예: `useWorkspaceMembers`가 서버 로스터를 시드하고 `useMemberActions` 델타를 병합하는 파생 셀렉터(또는 로드 훅이 뮤테이션 결과를 흡수하는 단일 소유 훅).
- **Trade-offs**: ✅ 로드(단순)와 재조정(복잡)을 계층 분리해 패널 비대화 방지, 테스트 국소화 · ❌ 두 훅의 상태 소유 경계를 명확히 하지 않으면 "분리된 두 목록"(Req 4.2 금지) 재발 위험 → 소유권 계약을 설계에서 못박아야 함.

> **권장**: 백엔드 = **Option A**. 프론트 = **A 기반, Req 4는 C의 재조정 계층 아이디어 채택**. 즉 조회/상태는 `useAssignableUsers` 미러로 저위험 확보하고, 단일 소스화는 소유권을 한 훅에 못박아(서버 시드 → 세션 델타 병합) 패널은 "읽기 전용 소비자"로 유지.

---

## 4. 노력·리스크 (Effort & Risk)

| 영역 | Effort | Risk | 근거 |
|---|---|---|---|
| 백엔드(라우트+리포+읽기모델+서비스+테스트) | **S** (1–3일) | **Low–Medium** | assignable 패턴 전량 재사용; 리스크는 Req 1.5 비필터 divergence와 Req 1.4 전체노출 페이지네이션 정책 결정뿐 |
| 프론트 어댑터+로드 훅 | **S** | **Low** | `useAssignableUsers` 직접 미러(계약 동일) |
| 프론트 단일 소스화(Req 4) + 패널 리팩터(`nameById` 제거) | **M** (3–7일) | **Medium** | 서버 시드↔세션 델타 재조정 소유권·순서·중복/제거 반영이 실난점. 회귀(뮤테이션 후 표시 일관성) 테스트 필요 |
| **합계** | **M** | **Medium** | 백엔드는 예측가능, 프론트 재조정이 리스크·노력 집중 |

---

## 5. 설계 단계 이월 사항 (Research Needed / 권장)

1. **전체 로스터 노출 정책(Req 1.4)**: default limit 정책과 "전체 멤버 조회 보장" 방식 — 큰 단일 페이지 vs 프론트의 total 기반 페이지 루프 vs limit 무제한. FE가 "전체 표시"를 어떻게 보장할지 확정.
2. **단일 소스 소유권 모델(Req 4.1·4.2)**: 서버 로스터와 `useMemberActions` 델타 병합의 소유 훅·병합 규칙(중복 없는 add / 제거 제외 / 역할 변경 반영)과 병합 후 순서 안정성. "분리된 두 목록" 금지 계약을 설계에 명문화.
3. **읽기 모델 필드 네이밍(Req 1.2)**: `user_id` vs `id` — 백엔드는 `User.id`이지만 멤버십/프론트는 `user_id`로 키잉. 응답 필드명을 `user_id`로 노출할지, 프론트 매핑을 둘지 확정(뮤테이션 `MemberRead.user_id`와 정합).
4. **비활성·삭제 멤버 포함 쿼리(Req 1.5) 확정**: inner-join에 소프트삭제 필터 미적용을 명시하고, 이메일 null·이름 표시(비활성 멤버) 렌더 규칙을 설계에 기술. 통합 테스트에 "비활성 멤버가 role과 함께 로스터에 존재" 케이스 포함.
5. **테스트 하네스 재사용**: `tests/workspace/test_assignable_users_integration.py`의 게이팅 매트릭스(owner/admin→200, editor/viewer/비-멤버→403, 무세션→401)·narrow 봉투 leak 단언·pagination items/total 정합을 로스터용으로 복제하되 Req 1.5 divergence 케이스를 추가.

---

## 다음 단계 (Next Steps)

- 본 격차 분석 검토 후, `requirements.md` 승인(현재 미승인) → `/kiro-spec-design s25-member-roster`로 설계 문서 생성.
- 설계 시 §3 권장안(BE=Option A / FE=A+C 재조정 계층)과 §5 이월 5개 항목을 입력으로 사용.

---

## 6. 설계 종합 결정 (Design Synthesis — 설계 단계 확정)

> `/kiro-spec-design` 실행 중 discovery 종합(generalization / build-vs-adopt / simplification) 결과. §5 이월 5개 항목을 여기서 확정한다.

### 6.1 Generalization

- **읽기 모델을 `AssignableUserRead` 확장이 아니라 신규 join 프로젝션으로 분리**: assignable(`User` 단일 엔티티, id/name/email)과 roster(`User ⋈ WorkspaceMember.role`, user_id/name/email/role)는 노출 필드·키·소스가 달라 하나의 모델로 일반화하면 오히려 leak 표면과 optional 필드가 늘어난다. 두 모델을 분리 유지하고 로스터는 4-필드 narrow BaseModel(`MemberRosterRead`)로 못박는다.
- **로더 훅은 `useAssignableUsers` 형태를 일반화 재사용**: null 가드·in-flight 가드·`[workspaceId]` effect·`reload()`·`toApiError` 정규화가 동일 계약이므로 `useWorkspaceMembers` 는 items 타입·필드명만 바꾼 미러다(인터페이스 일반화, 구현 복제 최소).

### 6.2 Build vs. Adopt

- **접근 통제·anti-enumeration·401/403·admin override = 전량 Adopt**: `require_ws_role(Role.OWNER)` 게이트가 editor/viewer/비-멤버/미존재 WS 를 403 으로 통일하고 `has_at_least` admin 단락으로 INV-3 를 무료 충족한다. 재구현 금지.
- **Page 봉투·narrow 직렬화 = Adopt**: s01 `Page[T]`·선언 필드 전용 직렬화로 Req 2.6(민감 필드 비노출)을 스키마 형태만으로 보장한다(별도 화이트리스트 불필요).
- **결정적 순서·total = Adopt(반전 적용)**: `order_by(User.id)` + 동일 필터 `func.count()` 선례를 그대로 쓰되 필터를 "workspace_id 소속 전량"으로 반전한다.

### 6.3 Simplification (§5 이월 확정)

1. **전체 로스터 노출(Req 1.4)**: 백엔드는 `Page{items,total}` 유지(limit 기본 50). 프론트는 `useAssignableUsers` 와 동일하게 **첫 페이지(limit=50) + `total`** 노출로 단순화하고, 페이지네이션 루프는 이 spec 밖으로 미룬다(현재 폐쇄형 환경 멤버 규모 가정). `total`>표시 수인 경우를 대비해 total 을 인터페이스에 노출해 후속 확장 여지만 남긴다.
2. **단일 소스 소유권(Req 4.1·4.2) — reload-after-mutation 채택**: 서버 로스터(`useWorkspaceMembers.members`)를 **유일 표시원**으로 삼고, 뮤테이션(add/changeRole/remove) 성공/실패 후 로스터를 `reload()` 하여 서버 진실로 재동기화한다. `useMemberActions.members` 로컬 델타는 표시에 **사용하지 않는다**. 근거: 새 세션에서 `useMemberActions.members` 는 빈 배열로 시작하므로 "기존 로스터 멤버 제거"를 기록하지 못해(빈 배열 filter=무기록) 델타 병합으로는 Req 4.1(제거 반영)을 만족할 수 없다. reload 는 서버가 add(중복 없음)·remove(제외)·role 변경을 권위 있게 반영하므로 세 조건을 자명하게 충족하고 "두 목록 분리"(Req 4.2 금지)를 원천 차단한다. 낙관적 델타 병합은 removal-of-preexisting 갭·순서 재조정 복잡도로 기각.
3. **읽기 모델 필드명(Req 1.2) = `user_id`**: `MemberRead.user_id`·프론트 키잉과 정합. 로스터 행은 `(User, role)` join 프로젝션이므로 `model_validate(user)`(id→user_id 리네임 모호)를 쓰지 않고 서비스가 `MemberRosterRead(user_id=user.id, name=…, email=…, role=MemberRole(role))` 로 **명시 생성**한다.
4. **비활성·삭제 멤버 포함(Req 1.5) = 소프트삭제 필터 미적용 inner-join**: `select(User, WorkspaceMember.role).join(user_id).where(workspace_id)` — `is_active`/`is_deleted` 필터를 적용하지 않는다. INV-4 로 멤버십↔user FK dangling 이 없어 inner-join 이 안전하며 비활성·삭제 멤버도 role 과 함께 노출된다. `nameById` 우회 제거(Req 3.7)는 로스터의 name 필드가 대체.
5. **테스트 하네스 재사용 + divergence 케이스**: `test_assignable_users_integration.py` 의 게이팅 매트릭스·narrow leak·pagination 단언을 로스터용으로 복제하되 "비활성·삭제 멤버가 role 과 함께 로스터에 존재", "owner 자신 포함", 4-필드(user_id/name/email/role) narrow 를 추가한다.

### 6.4 Boundary 재확인

- **소유**: `GET /workspaces/{id}/members` 라우트, `MembershipRepository.list_members`, `MemberRosterRead` 스키마, `MembershipService.list_members`, 프론트 `memberApi.list`·`useWorkspaceMembers`·`MemberManagementPanel` 표시원 전환.
- **비소유(재사용만)**: 멤버 뮤테이션 동작(`useMemberActions`·`memberApi.add/changeRole/remove`·백엔드 멤버 CRUD), 게이트(`require_ws_role`), self-role 에코(`MembershipRoleSource`), assignable 조회. 이 spec 은 뮤테이션 로직을 재구현하지 않고 표시원만 서버 로스터로 이동한다.
