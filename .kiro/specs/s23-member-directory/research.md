# Gap Analysis — s23-member-directory

> 요구사항(requirements.md)과 기존 코드베이스 사이의 구현 격차를 분석해 설계 단계 의사결정을 돕는다.
> 본 문서는 **정보와 선택지**를 제공할 뿐, 최종 구현 결정을 내리지 않는다.

## 분석 요약 (Analysis Summary)

- **본질**: 신규 기능이 아니라 **의도된 anti-enumeration 설계의 owner 범위 완화**다. 프로젝트는
  일반 사용자 열거 수단을 의도적으로 부재시켰고(계약 공백 S1: `GET /workspaces/{id}/members` 없음,
  사용자 목록은 admin 전용 `GET /admin/users` 뿐), s23 은 이 경계를 owner(+admin override)로만
  좁게 재개방한다.
- **백엔드 핵심 격차 1개**: "배정 가능 사용자"(admin 아님·활성·비삭제·비-멤버)를 반환하는
  **신규 owner-gated 조회 엔드포인트**가 필요하다. 소유 게이트(`require_ws_role(OWNER)`+admin
  override)·페이지네이션(`Page[T]`·limit/offset)·narrow 스키마 패턴은 모두 기존 자산 재사용.
- **신규 요소는 사실상 하나**: `user` ↔ `workspace_member` **교차 도메인 anti-join** 쿼리
  (기존 어떤 리포지토리도 `is_deleted`/`is_active` 필터를 쿼리 레벨에서 하지 않음). 이를 뒷받침하는
  복합 인덱스 `ix_user_is_deleted_is_active` 는 이미 존재한다.
- **프론트 핵심 격차 1개**: `MemberManagementContent` 의 raw `user_id` 숫자 입력을 **선택 UI** 로
  교체. 추가 뮤테이션(`useMemberActions().add`)·게이팅(`RequireRole`)·오류표시(`ErrorMessage`)·
  `Page<T>` 는 그대로 재사용하고, **배정 가능 목록 조회 훅/API 만 신설**한다.
- **권장 접근**: 백엔드·프론트 모두 **하이브리드(Option C)** — 기존 패턴/컴포넌트는 확장·재사용하되,
  "배정 가능 열거"라는 별도 책임(전용 엔드포인트·전용 조회 훅·선택 컴포넌트)만 신규 생성.

---

## 1. 현재 상태 조사 (Current State Investigation)

### 1.1 백엔드 — 워크스페이스/멤버십 도메인 (`backend/app/workspace/`)

| 파일 | 책임 |
|---|---|
| `router.py` | 워크스페이스 CRUD + 멤버 추가/변경/제거 8개 엔드포인트 HTTP 결선. 서비스 provider factory 소유. |
| `admin_router.py` | admin 전용 `POST /admin/workspaces/{id}/owner`(소유권 변경). `require_admin` 게이트. |
| `dependencies.py` | `require_ws_role(minimum)` 얇은 어댑터 — 경로 파라미터 `{id}`→`workspace_id` 변환, s01 공용 resolver 위임. |
| `schemas.py` | `WorkspaceCreate/Update/Read`, `MemberRole`, `MemberCreate/Update/Read`, `OwnerChangeRequest`. |
| `service.py` | `WorkspaceService`, `MembershipService`(add/change_role/remove/change_owner). 도메인 규칙만, 인증 게이팅 없음. |
| `repository.py` | `WorkspaceRepository`, `MembershipRepository`(get·get_role·add·set_role·remove·remove_all·user_exists). **list_members 없음.** |

의존 방향: router → service(생성자 주입 repo) → repository → `app.models`.

### 1.2 소유 게이트 · admin override (`backend/app/common/permissions.py`)

```python
class WorkspaceRoleResolver:
    def has_at_least(self, db, ctx, workspace_id, minimum) -> bool:
        if ctx.is_admin:            # INV-3 admin bypass — DB 조회 없이 통과
            return True
        role = self.resolve(db, ctx, workspace_id)
        return role is not None and role >= minimum

def require_ws_role(minimum: Role) -> Callable[..., AuthContext]:
    # 403 DomainError(FORBIDDEN) if not satisfied; 401 은 get_current_user 에서
```

- **admin override 단일 소스**: `ctx.is_admin` 가 `has_at_least` 를 멤버십 조회 전에 `True` 로
  단락. Req 2.2("admin 은 owner 멤버가 아니어도 허용") 를 **추가 구현 없이** 충족.
- **Role 이원화**: `Role`(IntEnum, VIEWER<EDITOR<OWNER, 게이팅용) vs `MemberRole`(str Enum,
  직렬화용). 신규 엔드포인트 게이트는 `require_ws_role(Role.OWNER)` 를 그대로 쓴다.

### 1.3 사용자 계정 모델 (`backend/app/models/user.py`, 공용/s01 — feature 가 수정 금지)

| 필드 | 타입 | 비고 |
|---|---|---|
| `id` | BigInteger PK | |
| `login_id` | String(255) UNIQUE NOT NULL | **노출 금지**(Req 1.2) |
| `password_hash` | String(255) | 절대 노출 금지 |
| `name` | String(255) NOT NULL | **노출 대상** |
| `email` | String(255) **nullable** | **노출 대상, null 허용**(Req 1.3) |
| `is_admin` / `is_active` / `is_deleted` | Boolean | **필터 기준**, 값 자체는 노출 금지 |
| `created_at` / `updated_at` | DateTime | 노출 금지 |

복합 인덱스 `Index("ix_user_is_deleted_is_active", "is_deleted", "is_active")` 존재 → 배정 가능
필터를 인덱스로 지원. 물리 삭제 없음(INV-4).

### 1.4 기존 사용자 열거 패턴 — `GET /admin/users` (admin 전용, 참조용)

```python
# admin_account/repository.py
def list_paginated(self, db, limit, offset):
    total = db.scalar(select(func.count()).select_from(User)) or 0
    items = list(db.scalars(select(User).order_by(User.id).limit(limit).offset(offset)))
    return items, total   # 필터 없음 — 삭제·비활성 포함 (admin 관리 목적)
```

- 스키마 `UserRead(TimestampedRead)` 는 `login_id`·상태 flag 를 모두 노출 → **직접 재사용 불가**.
- 페이지네이션 관례(전 코드베이스 통일): `Query(50, ge=1)`/`Query(0, ge=0)` → service →
  repo `(items, total)` → `Page[T]` 래핑, `ORDER BY <table>.id`. 커서 방식 없음.

### 1.5 anti-enumeration 선례

- `auth/service.py`: 미존재·비밀번호 불일치·비활성·삭제 실패를 **단일 401** 로 통일(계정 열거 방지).
- `require_admin` 단일 게이트; feature 는 자체 admin 게이트 재정의 금지.
- 함의: 배정 가능 목록은 (a) narrow 스키마(id/name/email 만), (b) 쿼리 레벨 상태 필터,
  (c) **멤버 열거 자체를 노출하지 않는** 구조가 필요하다.

### 1.6 프론트 — 멤버 관리 UI (`frontend/src/features/workspace/`)

- **교체 지점**: `components/MemberManagementPanel.tsx` 의 `MemberManagementContent` 내
  `<input id="member-add-user-id" type="number">` + `handleAdd`(raw user_id 파싱). 이 숫자 입력이
  선택 UI 교체 대상.
- **유지 재사용**:
  - 추가 뮤테이션 `useMemberActions().add(workspaceId, { user_id, role })` → `memberApi.add`
    → `POST /workspaces/{id}/members`. **계약 불변, 그대로 사용.**
  - 게이팅 `<RequireRole minimum={Role.OWNER} currentRole={roleFor(id)}>` (s16/s18 seam).
  - 오류 인라인 표시 `<ErrorMessage error={...} />` (`shared/ui`), `ApiError`(`code:"forbidden"` 등).
  - `Page<T>`(`shared/types/page`), `apiClient`(전역 401 인터셉터·base URL `/api/1.0` 포함).
- **API 계층**: `api/memberApi.ts`(add/changeRole/remove, **list 없음**), `api/adminApi.ts`
  (`listUsers()`→`GET /admin/users`, admin 전용), `api/types.ts`(백엔드 스키마 미러).
- **테스트 관례**: Vitest + Testing Library, `vi.mock("@/shared/api/client")`(워크스페이스 feature 는
  MSW 미사용). 컴포넌트 테스트는 게이트가 읽는 leaf 훅만 목킹하고 `RequireRole`/`ErrorMessage` 는
  실제로 통과시킨다.

---

## 2. 요구사항 실현 가능성 · Requirement-to-Asset Map

태그: **[재사용]** 기존 자산 그대로 · **[확장]** 기존 파일/패턴 확장 · **[신규]** 신규 생성 ·
**[Missing]** 현재 부재 · **[Constraint]** 아키텍처 제약 · **[Unknown]** 설계 단계 연구 필요.

| 요구사항 | 기술 필요 | 매핑 자산 / 격차 |
|---|---|---|
| **R1.1** 배정 가능 필터(admin 아님·활성·비삭제·비-멤버) | 교차 도메인 anti-join 쿼리 | **[Missing]** 신규 repo 쿼리(`user` ↔ `workspace_member`). 상태 필터 쿼리 선례 없음. 인덱스는 존재. |
| **R1.2** id·name·email **만** 노출 | narrow 응답 스키마 | **[신규]** `ORMReadModel` 상속 신규 스키마(선언 필드만 직렬화 → 누출 없음). `UserRead` 재사용 불가. |
| **R1.3** email null → 빈 값, 제외 안 함 | nullable 처리 | **[재사용]** 모델·스키마 `email: str \| None`. 프론트 렌더에서 빈 문자열. |
| **R1.4** 빈 목록 = 오류 아님 | 빈 `Page` 반환 | **[재사용]** `Page[T](items=[], total=0)`. |
| **R1.5** 결정적 순서 + 페이지 조회 | limit/offset·ORDER BY id | **[재사용]** 코드베이스 통일 페이지네이션 관례. |
| **R2.1** 비-owner 403 | owner 게이트 | **[재사용]** `require_ws_role(Role.OWNER)`. |
| **R2.2** admin override 허용 | is_admin 단락 | **[재사용]** `WorkspaceRoleResolver.has_at_least` 의 `ctx.is_admin`. |
| **R2.3** 미인증 401 | 인증 의존성 | **[재사용]** `get_current_user`. |
| **R2.4** 서버 게이트가 유일 경계 | — | **[재사용]** 기존 게이팅 규약(클라 게이팅은 편의). |
| **R3.1** 목록을 name·email 로 표시 | 조회 훅 + 표시 | **[신규]** `useAssignableUsers` 훅 + 선택 컴포넌트. |
| **R3.2** raw user_id 입력 → 선택 방식 교체 | UI 교체 | **[확장]** `MemberManagementContent` 폼 교체. |
| **R3.3** 선택 사용자+role 추가 요청 | 기존 뮤테이션 | **[재사용]** `useMemberActions().add`(계약 불변). |
| **R3.4** 성공 시 목록에서 제거/갱신 | 낙관 제거 or refetch | **[신규]** 훅에 목록 반영 로직(로컬 필터 또는 refetch). |
| **R3.5** 배정 가능 0명 안내·추가 비활성 | 빈 상태 | **[신규]** 컴포넌트 빈 상태(재사용 가능: `shared/ui/EmptyState`). |
| **R3.6** 로딩 중 상태·추가 방지 | 로딩 상태 | **[신규]** 훅 `loading` + 재사용 `Spinner`. |
| **R4.1** 조회 실패(403/401/기타) 인라인 표시 | 오류 표면화 | **[재사용]** `ErrorMessage` + `ApiError`. |
| **R4.2** 추가 실패(404/409/403) 표시·상태 롤백 | 비낙관 뮤테이션 | **[재사용]** `useMemberActions`(실패 시 상태 무변경). |
| **R4.3** stale 409 → 표시 + 목록 갱신 | refetch 트리거 | **[신규]** 409 후 배정 가능 목록 refetch 결선. |

### 복잡도 신호
- 단순 CRUD/조회가 대부분(기존 패턴). **유일한 알고리즘적 신규**: 교차 도메인 anti-join +
  상태 필터. 외부 통합 없음. 보안 경계(narrow 노출·owner 게이트)가 정확성 핵심.

---

## 3. 구현 접근 선택지 (Options)

### 3.1 백엔드

#### Option A — 기존 워크스페이스 멤버 라우터/서비스에 조회 추가
- `workspace/router.py` 에 조회 라우트 1개, `MembershipService`/`MembershipRepository` 에
  배정 가능 조회 메서드 추가, 신규 narrow 스키마를 `workspace/schemas.py` 에 추가.
- ✅ 파일 최소 신설, 기존 provider·게이트·조립 지점 재사용. 워크스페이스 스코프와 자연 정합.
- ✅ `require_ws_role` 이 이미 `{id}` 경로 처리 → 게이트 즉시 적용.
- ❌ `MembershipRepository` 가 `User` 도 쿼리하게 되어 책임이 다소 넓어짐(멤버십 ↔ 사용자 교차).
- ❌ "멤버 라우터에 배정-가능-사용자 조회"라는 의미 혼선 여지(멤버 목록 아님을 명명으로 분리 필요).

#### Option B — 독립 member-directory 패키지 신설
- `backend/app/member_directory/`(router·service·repository·schemas) 신규 + `main.py` 등록.
- ✅ "배정 가능 열거"라는 별도 책임 명확 분리, S1(멤버 목록) 과 개념적 격리.
- ❌ 게이트·provider·조립 보일러플레이트 중복, 워크스페이스 스코프 자산을 다시 배선.
- ❌ 소규모 기능 대비 과설계 위험.

#### Option C — 하이브리드 (권장)
- **전용 엔드포인트** `GET /workspaces/{id}/assignable-users` 를 `workspace/router.py` 에 두되,
  조회 로직은 **별도 얇은 read 전용 서비스/리포 메서드**(예: `AssignableUserRepository` 또는
  `MembershipRepository.list_assignable_users`)로 분리하고, 응답은 **전용 narrow 스키마**
  (`AssignableUserRead` = id/name/email)로 고정.
- ✅ 게이트·조립·페이지네이션은 재사용(Option A 장점), 명명·스키마·쿼리 책임은 분리(Option B 장점).
- ✅ "assignable-users" 경로가 구조적으로 **비-멤버만** 반환 → S1(권위 멤버 목록) 재개방 회피.
- ❌ 조회 메서드 위치(멤버십 repo vs 신규 repo) 결정 필요 — 설계 단계 판단 사항.

**Trade-off 요약**: 전용 경로(assignable-users) + 재사용 게이트/페이지네이션이 요구사항의
"멤버 열거 노출 금지" 제약과 최소 노출 원칙을 가장 곧게 만족.

### 3.2 프론트

#### Option A — `MemberManagementPanel` 확장 + 배정 목록 훅 신설
- `MemberManagementContent` 의 숫자 입력을 선택 UI 로 교체, 신규 `useAssignableUsers` 훅과
  `memberApi`(또는 신규 `directoryApi`) 에 조회 함수 추가, 신규 미러 타입 `AssignableUser`.
- ✅ 게이팅·오류표시·추가 뮤테이션·`Page<T>` 재사용, 변경 표면 최소.
- ✅ 기존 테스트 관례(`vi.mock` apiClient)로 커버 가능.
- ❌ 패널 파일이 다소 커짐 → 선택 UI 를 하위 컴포넌트(`AssignableUserSelect`)로 분리 권장.

#### Option B — 멤버 관리 화면 전체 재작성
- 과함. 기존 D-1 role seam·S1 열거 한계 주석·비낙관 뮤테이션 계약을 재검증해야 하는 회귀 위험.
- ❌ 비권장.

**권장(프론트)**: **Option A + 선택 UI 하위 컴포넌트 분리**. 조회는 신규 훅으로 격리하고,
추가 성공/409 시 목록 갱신(로컬 필터 또는 refetch) 을 훅이 소유.

---

## 4. 노력 · 리스크 (Effort & Risk)

| 영역 | Effort | Risk | 근거 |
|---|---|---|---|
| 백엔드 | **S–M (2–4일)** | **Medium** | 게이트·페이지네이션·스키마 패턴 재사용으로 대부분 정형. 유일 신규는 교차 도메인 anti-join + 상태 필터 쿼리와 **narrow 노출 정확성**(보안 경계) — 실수 시 계정 필드/멤버 열거 누출 위험이라 검증 부담. |
| 프론트 | **M (3–5일)** | **Low–Medium** | 추가 뮤테이션·게이팅·오류표시 재사용. 신규는 조회 훅·선택 UI·로딩/빈/오류/stale-409 상태기계. 관례 확립된 테스트로 커버 용이하나 상태 전이 케이스가 다수. |
| **전체** | **M** | **Medium** | 아키텍처 변경 없음, 익숙한 스택. 리스크는 전적으로 **보안 경계(최소 노출·owner 게이트·anti-enumeration)** 정확성에 집중. |

---

## 5. 설계 단계 권고 (Recommendations for Design Phase)

### 선호 접근
- **백엔드 Option C**: `GET /workspaces/{id}/assignable-users`, `require_ws_role(Role.OWNER)`,
  전용 `AssignableUserRead(id/name/email)` narrow 스키마, `Page[AssignableUserRead]` 응답.
- **프론트 Option A(+분리)**: 신규 `useAssignableUsers` 훅 + `AssignableUserSelect` 컴포넌트로
  `MemberManagementContent` 의 raw user_id 입력 교체. 추가/409 후 목록 갱신은 훅 소유.

### 핵심 설계 결정 (Key Decisions)
1. **엔드포인트 명명/형태**: 전용 `assignable-users` 경로(권장) vs `members?assignable=true`.
   요구사항이 "권위 있는 전체 멤버 목록 신설 금지"(Out of scope)를 명시하므로, **비-멤버만**
   반환하는 전용 경로가 S1 재개방을 구조적으로 차단.
2. **anti-join 쿼리 위치**: `MembershipRepository.list_assignable_users` vs 신규 read 전용 repo.
   `user` + `workspace_member` 를 함께 조회하므로 어느 패키지가 소유할지 명시.
   조건: `is_admin=false AND is_active=true AND is_deleted=false AND NOT EXISTS(workspace_member
   WHERE workspace_id=:id AND user_id=user.id)`, `ORDER BY user.id`, limit/offset.
3. **narrow 스키마 누출 방지**: `ORMReadModel`(from_attributes) + 선언 필드(id/name/email)만 →
   `login_id`·상태 flag·타임스탬프·`password_hash` 원천 차단. 별도 화이트리스트 불필요.
4. **email null 표현**: 백엔드 `email: str | None` 유지, 프론트에서 빈 문자열로 표시(사용자 제외 금지).
5. **결정적 순서 + 페이지네이션**: `ORDER BY user.id`, `Query(50, ge=1)`/`Query(0, ge=0)`,
   `Page[T]` 관례 준수(다수 사용자 환경 R1.5).
6. **프론트 목록 갱신 정책**: 추가 성공 시 로컬 필터 제거(R3.4) vs 전체 refetch. stale-409(R4.3)
   는 refetch 로 통일하는 편이 단순. 훅이 단일 소유.
7. **게이팅 재사용 확인**: 프론트 선택 UI 도 기존 `<RequireRole minimum={Role.OWNER}>` 하위에
   두어 role 직접 비교 금지 규칙 유지. 서버 403 은 항상 `ErrorMessage` 로 표시(R4.1·R2.4).

### 설계 단계로 이월할 연구 항목 (Research Needed)
- **[Unknown]** anti-join 을 SQLAlchemy 로 표현하는 최적 형태(`NOT EXISTS` 상관 서브쿼리 vs
  `outerjoin ... IS NULL`)와 `ix_user_is_deleted_is_active` 인덱스 활용/실행계획 확인.
- **[Unknown]** `total` 계산 시 동일 필터를 count 에도 적용해야 함(페이지 total 이 배정 가능 총수와
  일치) — 기존 `list_paginated` 는 무필터 count 라 그대로 복제하면 안 됨.
- **[Unknown]** 프론트 선택 UI 형태(드롭다운/검색 콤보박스/리스트). 요구사항은 상세 형태를
  수용 기준에서 제외했으므로 최소 구현(결정적 목록 + role 선택)으로 충분한지 설계에서 확정.
- **[Constraint]** 신규 의존성 추가 금지(email-validator 등) — `email` 은 계속 `str | None`.
- **[Constraint]** `app/common/*`·`app/models/*` 수정 금지 — 신규 스키마/쿼리는 feature 패키지에.

### 다음 단계
- 본 격차 분석을 반영해 `/kiro-spec-design s23-member-directory` 로 기술 설계를 생성한다.

---

## 6. 설계 종합 (Synthesis Outcomes — design phase)

> 설계 단계에서 discovery 결과에 3개 렌즈(일반화·Build vs Adopt·단순화)를 적용한 결과와,
> §5 의 미해결 결정 항목을 확정한 기록.

### 6.1 일반화 (Generalization)
- 네 요구사항은 모두 **"owner 범위 배정 가능 사용자 열거 + 선택 기반 추가"** 라는 단일 능력의
  변형이다. 별도 일반화 대상 없음. 응답 형태를 `Page[AssignableUserRead]` 로 고정하면 추후
  검색어/정렬(현 spec out of scope)이 붙어도 **인터페이스 형태 변경 없이** 확장 가능 — 인터페이스만
  일반화하고 구현은 현 요구(결정적 목록)로 최소화한다.

### 6.2 Build vs Adopt
- **Adopt(재사용)**: owner 게이트(`app.workspace.dependencies.require_ws_role`)·admin override
  (`AuthContext.is_admin`)·페이지네이션 관례(`Query(50, ge=1)`/`Query(0, ge=0)`·`Page[T]`)·
  `ORMReadModel`(from_attributes narrow 직렬화)·프론트 `RequireRole`·`ErrorMessage`·`EmptyState`·
  `Spinner`·`RoleSelect`·`useMemberActions`(뮤테이션, 비낙관·실패 시 무변경)·`apiClient`(전역 401).
- **Build(신규, 4개 최소)**: (a) 교차 도메인 anti-join repo 쿼리, (b) `AssignableUserRead` narrow
  스키마, (c) 프론트 `useAssignableUsers` 조회 훅 + `assignableUserApi` 어댑터, (d) `AssignableUserSelect`
  선택 컴포넌트. 외부 라이브러리 도입 없음(제약: `email` 은 `str | None` 유지, email-validator 등 금지).
- anti-join 은 **상관 `NOT EXISTS` 서브쿼리**(SQLAlchemy `.exists()` + `~`)로 표현 — `outerjoin ... IS NULL`
  대비 의미가 곧고 `ix_user_is_deleted_is_active` 인덱스와 상태 필터가 함께 걸린다.

### 6.3 단순화 (Simplification)
- **백엔드 패키지 신설 안 함**(§3.1 Option B 기각): `member_directory` 신규 패키지·전용 provider·
  조립 배선은 소규모 기능 대비 과설계. Option C 를 **워크스페이스 패키지 내부**로 실현.
- **repo 위치 확정**: anti-join 을 `MembershipRepository.list_assignable_users` 에 둔다. 본질이
  "이 워크스페이스의 **멤버가 아닌** 사용자" 판정이라 멤버 관계를 이미 소유한 리포지토리와 응집.
  별도 `AssignableUserRepository` 신설 안 함(단일 구현·인디렉션 제거). `User` import 는 이미 존재
  (`user_exists`)해 신규 의존 없음.
- **service 위치**: `MembershipService.list_assignable_users` 추가 — 기존 provider
  `get_membership_service` 재사용, 신규 provider 배선 0.
- **프론트 목록 갱신 단일 경로**: 추가 시도(성공/실패 무관) **완료 후 항상 `assignable.reload()`**.
  - 성공(R3.4): 추가된 사용자는 멤버가 되어 anti-join 에서 제외 → 재-fetch 로 목록에서 사라짐.
  - stale-409(R4.3): 재-fetch 로 목록 교정 + `useMemberActions.error` 가 409 표시.
  - 기타 실패(404/403, R4.2): 로컬 멤버 상태 무변경(useMemberActions 가 성공 시에만 append) +
    재-fetch 는 서버 진실 재확인이라 부분 반영 없음.
  이 단일 정책이 R3.4·R4.2·R4.3 를 한 코드 경로로 만족 → `useMemberActions` 계약 변경 불필요
  (await 후 reload 만; add 는 항상 void 로 resolve).

### 6.4 §5 미해결 항목 확정
1. **엔드포인트**: `GET /workspaces/{id}/assignable-users`(전용 경로, `members?assignable=` 아님).
   비-멤버만 반환 → S1(권위 멤버 목록) 재개방을 구조적으로 차단.
2. **anti-join 위치**: `MembershipRepository`(위 6.3).
3. **count 필터 드리프트 방지**: 페이지 `total` 은 **동일 필터를 적용한** `select(func.count())` 로
   계산. 기존 `list_paginated` 의 무필터 count 복제 금지(§5 Unknown 해소). 필터 절을 내부 헬퍼로
   단일화해 items/count 간 드리프트 차단.
4. **narrow 노출**: `AssignableUserRead(ORMReadModel)` = `id`/`name`/`email` 선언 필드만 →
   `login_id`·상태 flag·타임스탬프·`password_hash` 원천 비직렬화(화이트리스트 불필요).
5. **선택 UI 최소 형태**: 결정적 목록 + 역할 선택으로 충분(검색/정렬 out of scope). `<select>` 기반
   `AssignableUserSelect` + 재사용 `RoleSelect`. `loadMore`(추가 페이지)는 이 spec 수용 기준 밖 —
   훅은 첫 페이지(limit 기본 50) fetch + `reload()` 만 소유(인터페이스는 페이지 확장 여지 유지).
6. **게이트 어댑터**: `app.workspace.dependencies.require_ws_role`(경로 `{id}`) 사용 — `common` 직접
   사용 금지(path param 이름 불일치).
