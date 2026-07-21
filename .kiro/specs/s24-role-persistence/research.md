# Gap Analysis — s24-role-persistence

> 재로그인/새로고침 후에도 워크스페이스별 role(owner/editor/viewer)이 복원되도록, `GET /workspaces`
> 응답에 호출자 관점 role 을 실어 로드 시점에 프론트 role 신호를 시드하는 교차 변경(s05·s16·s18)에 대한
> 구현 격차 분석. 결정이 아니라 정보·옵션 제공이 목적이다.

## 1. 분석 요약 (Analysis Summary)

- **범위**: 백엔드 1개 응답 스키마 + 서비스/리포지토리 조회 확장(가산적), 프론트 로드-시드 경로 1개, 소비
  지점(배지·owner 게이팅) 재배선. 새 엔드포인트·새 마이그레이션·권한 모델 변경 없음.
- **핵심 발견 1 — 프론트 role 신호가 2갈래로 분기**: `useCurrentWorkspace().role`(provider-role, 현재
  `null` 하드코딩 → `useDocumentScope`·`useEditorScope` 가 이미 소비) 와 `MembershipRoleSource.roleFor()`
  (best-effort in-session Map → `MemberManagementPanel` owner 게이팅·`CurrentWorkspaceIndicator` 배지가
  소비). 요구가 명시한 결함(배지·owner 게이팅)은 **후자** 경로다. 어느 한 경로만 채우면 다른 경로는 여전히
  null 이다 → 설계의 핵심 결정점.
- **핵심 발견 2 — s16 seam 은 이미 예약됨**: `CurrentWorkspaceContextValue.role: Role | null` 타입이 이미
  존재한다(동결 계약). 값을 채우는 것은 **타입 형태 변경이 아니다**. 반면 공용 `WorkspaceRead`(shared) 에는
  `role` 필드가 없어 **가산적 확장이 필요**하다.
- **핵심 발견 3 — 백엔드는 순수 스키마 변경으로 불충분**: `WorkspaceRead.model_validate(workspace)` 의 ORM
  객체엔 `role` 속성이 없다(role 은 워크스페이스 속성이 아니라 **호출자 상대값**). 리포지토리/서비스가 role 을
  별도로 조달해야 하며, admin `list_all` 경로는 호출자 멤버십 LEFT JOIN(없으면 null, Req 1.3)이 필요하다.
- **권고**: 백엔드는 가산 확장(저효율·저위험), 프론트는 "provider-role 채우기 + MembershipRoleSource 시드"의
  **하이브리드(옵션 C)** 를 유력하게 검토. 격차·트레이드오프는 §5·§6 참조.

---

## 2. 현재 상태 조사 (Current State Investigation)

### 2.1 백엔드 (s05 workspace)

| 자산 | 위치 | 현재 동작 | s24 관련성 |
|---|---|---|---|
| `WorkspaceRead` | `backend/app/workspace/schemas.py:81` | `TimestampedRead` 상속, `name·is_shareable·trash_retention_days`. **role 없음**. `model_validate(ws)` 로 ORM 직렬화. | **가산 role 필드 추가 대상** |
| `MemberRole` | `schemas.py:47` | `str, Enum` (owner/editor/viewer). s01 `Role`(IntEnum)과 별개. | role 값 타입 재사용 |
| `WorkspaceService.list_workspaces` | `service.py:71` | `ctx.is_admin` → `list_all`, else `list_for_user`. 각 ws 를 `WorkspaceRead.model_validate` 로 매핑. **role 미조달**. | **role 주입 지점** |
| `WorkspaceRepository.list_for_user` | `repository.py:44` | member_scope 서브쿼리로 필터, `list[Workspace]` 반환. **role 미반환**(멤버 role 을 조회 안 함). | **(ws, role) 반환 확장 후보** |
| `WorkspaceRepository.list_all` | `repository.py:75` | 전체 Workspace, role 개념 없음. | 호출자 멤버십 LEFT JOIN 필요 |
| `MembershipRepository.get_role` | `repository.py:169` | `(ws_id, user_id)→role|None` 단건 조회 존재. | N+1 회피 위해 재사용 or 조인 |
| `AuthContext` | `common/auth.py:33` | `user_id: int`, `is_admin: bool`. | 호출자 식별 |
| `GET /workspaces` router | `router.py:80` | 인증 전용, `Page[WorkspaceRead]`. | 시그니처 무변경(응답만 확장) |

- **패턴/규약**: 세션은 메서드 인자 전달(생성자 주입 아님), 리포지토리 쓰기 메서드만 commit, `total` 은
  limit/offset 이전 전체 개수, items 는 `Workspace.id` 오름차순. role 조달은 이 규약과 충돌하지 않는다.
- **결정적 제약**: role 은 ORM `Workspace` 속성이 아니므로 `model_validate(ws)` 만으로는 채울 수 없다. 서비스가
  `WorkspaceRead.model_validate(ws)` 후 `role` 을 세팅하거나, `(ws, role)` 튜플을 받아 명시 구성해야 한다.

### 2.2 공통 레이어 (s16)

| 자산 | 위치 | 현재 동작 | s24 관련성 |
|---|---|---|---|
| `WorkspaceRead`(FE 미러) | `shared/types/workspace.ts:7` | 백엔드 미러, **role 없음**. | **가산 role 필드 미러** |
| `CurrentWorkspaceContextValue.role` | `app/workspace-context/types.ts:35` | `Role \| null` **타입 이미 존재**(동결). | 값만 채우면 됨(형태 무변경) |
| `CurrentWorkspaceProvider` | `app/workspace-context/CurrentWorkspaceProvider.tsx:145` | `role: null` **하드코딩**. `/workspaces` 로드 후 items 를 그대로 노출. | **role 파생 지점**(WorkspaceRead.role → context.role) |

- **의존 방향 제약(구조 스티어링·확인됨)**: `app/` 는 `features/workspace` 를 import 하지 않는다(예외: `AppHeaderNav`
  의 라우트 상수 1건). 따라서 s16 provider 가 `memberRoleToRole`(features 소유)을 직접 import 하면 방향 위반.
  → 번역을 `shared/` 로 이관하거나, 시드를 feature 레이어 브리지에 둬야 한다.

### 2.3 멤버십 role 시드 (s18)

| 자산 | 위치 | 현재 동작 | s24 관련성 |
|---|---|---|---|
| `MembershipRoleSource` / `MembershipRoleProvider` | `features/workspace/context/membershipRoleSource.tsx:71` | `Map<wsId, Role>` best-effort. `recordOwner`/`recordSelfRole` 로만 축적. **로드-시드 진입점 없음**. | **시드 메서드 추가 후보** |
| `memberRoleToRole` | `membershipRoleSource.tsx:49` | `MemberRole`(문자열)→`Role` 단일 번역 소스. | 시드 변환에 재사용(단일 소스 유지) |
| `MemberManagementPanel` | `components/MemberManagementPanel.tsx:55` | `roleFor(currentWorkspace.id)` → `<RequireRole minimum=OWNER currentRole=role>`. **role=null 시 owner 잠금(기능 결함)**. | 복원된 role 소비 |
| `CurrentWorkspaceIndicator` | `components/CurrentWorkspaceIndicator.tsx:68` | `roleSource?.roleFor(...)` → 없으면 "역할 미확인". | 복원된 role 소비 |
| provider-role 소비자 | `features/{document,editor}/hooks/useDocumentScope.ts`·`useEditorScope.ts` | 이미 `useCurrentWorkspace().role` 을 통과·소비(현재 항상 null). | **provider-role 채우면 자동 개선(파급)** |
| 조립 | `main.tsx:58,77` | `MembershipRoleProvider` 가 `CurrentWorkspaceProvider` **하위** 마운트. | 부모가 자식 훅 호출 불가 → 시드는 자식측 브리지에서 |

### 2.4 회귀/계약 가드

- **L2 계약 대조**(`tests/integration_L2/test_workspace_contract_conformance.py:481~526`): `WorkspaceRead` 필드
  **존재(superset)** 만 단언("must contain"), 정확 집합(exact-set) 아님 + "새 마이그레이션 무추가" 단언.
  → **가산 role 필드는 이 스위트를 깨지 않는다**(단, 새 마이그레이션 신설은 금지 — role 은 기존 컬럼 재사용이라
  마이그레이션 불필요).
- role 은 이미 `workspace_member.role` ENUM 에 존재 → **DB 스키마·마이그레이션 변경 없음**.

---

## 3. 요구사항 실현성 — Requirement→Asset 매핑

| Req | 기술 필요 | 대상 자산 | 격차 태그 |
|---|---|---|---|
| 1.1·1.4·1.5 | 목록 응답 각 항목에 호출자 role 포함(추가 요청 없이) | `list_workspaces`·`WorkspaceRead`·리포지토리 조인 | **Missing**(role 조달·필드) |
| 1.2 | role=멤버십 role 만, admin 상승 미반영 | 서비스가 `ctx.is_admin` 로 role 상승 금지 | Constraint(INV-3) |
| 1.3 | 비멤버(admin 전체 조회) 항목은 role null | `list_all` 호출자 멤버십 LEFT JOIN | **Missing**(admin 경로 role) |
| 1.2·1.5(응답) | 기존 필드 무변경 + 가산만 | `WorkspaceRead` optional `role` | **Missing**(FE·BE 미러) |
| 2.1·2.2·2.4 | 로드 시 role 시드·전환 시 반영 | provider-role 채우기 or MembershipRoleSource 시드 | **Missing**(시드 경로) |
| 2.5 | 문자열→등급 변환 단일 규칙 | `memberRoleToRole` 재사용 | Constraint(단일 소스·의존 방향) |
| 3.1·3.2·3.3 | 배지 정확·새로고침 후 유지 | `CurrentWorkspaceIndicator`(roleFor 소비) | **Missing**(신호 부재가 원인) |
| 4.1·4.2·4.3 | owner 게이팅 복원 | `MemberManagementPanel`(roleFor 소비) | **Missing**(기능 잠금 해소) |
| 4.4 | admin 은 세션 경로 유지, role 에 admin 미접합 | `RequireRole`/세션 `is_admin` | Constraint(INV-3) |
| 5.1·5.2·5.3 | 로드-시드 ⊕ in-session 공존, 서버값 우선, 미시드 WS 는 in-session | 시드=upsert(비목록 항목 보존) | **Unknown/설계**(병합 의미) |
| 5.4 | role 신호에 admin override 미접합 | 시드 경로가 멤버십 role 만 | Constraint(INV-3) |

- **복잡도 신호**: 단순 CRUD 아님. 워크플로(로드-시드 ⊕ in-session 병합 우선순위) + 교차 레이어 계약 + 의존
  방향 제약이 얽힌 **중간 복잡도**. 알고리즘·외부 통합은 없음.

---

## 4. 구현 접근 옵션 (Options)

> 백엔드는 사실상 단일 접근(가산 확장)이라 이견이 적다. 논쟁적 결정은 **프론트 시드 sink** 선택이다.

### 4.1 백엔드 (공통 전제 — 저위험)

- `WorkspaceRead` 에 `role: MemberRole | None = None` **가산 추가**(선택적·기본 None → 후방 호환).
- 서비스 `list_workspaces` 가 role 을 조달해 각 `WorkspaceRead` 에 주입. 조달 방식 2택:
  - **B-1 리포지토리 조인**: `list_for_user` 가 `(Workspace, role)` 반환(멤버 조인, 이미 member_scope 존재 →
    role 컬럼만 SELECT 추가). `list_all` 은 호출자 user_id 로 `WorkspaceMember` LEFT JOIN(없으면 null). N+1 없음.
  - **B-2 서비스 후조회**: 기존 리포지토리 유지, 서비스가 페이지 items 의 `id` 들에 대해 `get_role` 배치/개별
    조회. 리포지토리 계약 무변경이나 N+1 or 별도 배치 쿼리 필요.
  - → **B-1 권고**(단일 쿼리·계약 명확). `list_all` LEFT JOIN 은 admin 이 특정 WS 멤버일 때 실제 멤버십 role 을,
    비멤버면 null 을 정확히 산출(Req 1.2·1.3 동시 충족).

### 4.2 프론트 시드 sink — Option A: provider-role 채우기(s16 중심)

`CurrentWorkspaceProvider` 가 `WorkspaceRead.role`(문자열)→`Role` 변환 후 `value.role` 에 노출(현재 null 대체).

- **트레이드오프**:
  - ✅ s16 이 이미 예약한 seam(타입 형태 무변경). `useDocumentScope`·`useEditorScope` 소비자가 **자동 복원**(파급 이득).
  - ✅ 단일 권위 소스(서버 응답)로 role 일원화.
  - ❌ **배지·owner 게이팅은 여전히 미해결**: 두 컴포넌트는 `MembershipRoleSource.roleFor` 를 읽는다. 이들을
    `useCurrentWorkspace().role` 로 재배선해야 요구(Req 3·4)가 충족된다 → 소비 지점 변경 필요.
  - ❌ 의존 방향: 변환을 s16(app)에서 하려면 `memberRoleToRole`(features) 를 `shared/` 로 이관해야 함(단일 소스
    유지 위해). 그렇지 않으면 방향 위반.
  - ❌ in-session 축적(`recordOwner`/`recordSelfRole`)과의 공존(Req 5)이 애매해짐 — 두 신호원이 서로 다른 컨텍스트에
    분산.

### 4.3 프론트 시드 sink — Option B: MembershipRoleSource 시드(s18 중심)

`MembershipRoleSource` 에 `seedRoles(entries)` 추가하고, `MembershipRoleProvider` 하위 **브리지 컴포넌트**가
`useCurrentWorkspace().workspaces`(각 항목 `role` 포함)를 읽어 `memberRoleToRole` 변환 후 시드.

- **트레이드오프**:
  - ✅ **요구가 지목한 결함(배지·owner 게이팅)을 직접 해소** — 소비 지점(`roleFor`) 무변경.
  - ✅ 의존 방향 준수: 브리지는 feature 레이어(`useCurrentWorkspace` 소비 허용) + `memberRoleToRole` 동일 파일
    재사용(단일 소스 유지). s16 파일 미수정(기존 D-1 결정과 정합).
  - ✅ in-session 공존이 자연스러움: 시드는 `Map` upsert(목록 미포함 WS 항목 보존) → 서버값 우선(5.2) +
    미시드 WS 는 in-session 유지(5.3)가 `new Map(prev)`+set 의미로 그대로 성립.
  - ❌ provider-role(`useCurrentWorkspace().role`)은 여전히 null → `useDocumentScope`·`useEditorScope` 의
    role 은 미복원(이 스코프들이 role 을 실제로 게이팅에 쓰는지 설계 시 확인 필요).
  - ❌ 부모/자식 마운트 순서상 브리지 컴포넌트라는 간접층이 필요(부모 provider 가 자식 훅 직접 호출 불가).

### 4.4 프론트 시드 sink — Option C: 하이브리드(권고 검토)

백엔드 role 을 **두 sink 모두**에 반영: (1) `CurrentWorkspaceProvider` 가 `value.role` 채움(provider-role
소비자 복원) + (2) 브리지가 `MembershipRoleSource` 시드(배지·owner 게이팅 복원). 변환 단일 소스는 `shared/` 로
이관하거나 각 레이어가 규칙을 공유.

- **트레이드오프**:
  - ✅ 배지·owner 게이팅·editor/document 스코프까지 **role 신호 전면 복원**(파편화 제거).
  - ✅ Req 3·4(명시 결함) + 파급 개선을 함께 달성.
  - ❌ 변경 표면 최대: 시드 2곳 + 변환 이관 + 두 신호원 일관성(같은 WorkspaceRead.role 기원이므로 모순 위험은
    낮으나 검증 필요).
  - ❌ "단일 role 값 노출"(Req 5.2) 관점에서 두 신호원이 동일 기원임을 테스트로 못박아야 함.
  - **단계화 가능**: 1단계 백엔드 가산 + Option B(요구 직접 충족) → 2단계 provider-role 채우기(파급 이득) 로
    분해하면 위험을 낮추며 요구를 먼저 만족.

---

## 5. 노력·위험 (Effort / Risk)

| 영역 | 노력 | 위험 | 근거 |
|---|---|---|---|
| 백엔드 가산(role 조달·필드) | **S** (1~3d) | **Low** | 기존 member_scope 조인 재사용, 새 마이그레이션·엔드포인트 없음, L2 는 superset 단언이라 무파손 |
| 프론트 시드(Option B) | **S~M** | **Low~Med** | 브리지 1개 + `seedRoles` upsert. 위험은 in-session 병합 우선순위(Req 5) 회귀 |
| 프론트 하이브리드(Option C) | **M** (3~7d) | **Med** | 변환 단일 소스 이관 + 소비 지점 재배선 + 두 신호원 일관성 테스트. 동결 계약(s16 type·MembershipRoleSource) 인접 |
| 전체(권고 경로: BE 가산 + C 단계화) | **M** | **Med** | 교차 3-spec 이나 각 변경은 가산·국소. 주된 위험은 신호 일원화 검증 |

- **위험 상세**: (1) 동결 계약 인접 — `CurrentWorkspaceContextValue`(revalidation trigger)·`MembershipRoleSource`
  형태 변경 시 하위 spec 재검증 트리거. `role` 타입은 이미 존재하므로 값 주입은 형태 무변경이나, `seedRoles`
  추가는 인터페이스 확장. (2) in-session ⊕ load-seed 우선순위(Req 5.2/5.3) 오구현 시 "방금 만든 WS 역할이
  목록 재조회 후 사라짐" 회귀 가능 — upsert 의미·테스트로 못박아야 함. (3) admin override 접합 금지(INV-3):
  백엔드 role=멤버십 role 만, admin 은 세션 경로 — 서비스에서 `ctx.is_admin` 로 role 을 올리지 않도록 명시.

---

## 6. 설계 단계 권고 (Recommendations)

- **선호 접근**: 백엔드 **가산 확장(B-1 리포지토리 조인)** + 프론트 **Option C 를 단계화**(1단계 Option B 로
  Req 3·4 직접 충족 → 2단계 provider-role 채워 editor/document 파급 복원). 최소한 Option B 는 요구 충족의 하한선.
- **핵심 결정(설계에서 확정 필요)**:
  1. `WorkspaceRead.role` 을 `MemberRole | None`(문자열) 로 둘지, FE 미러에서만 변환할지 — 백엔드는 문자열
     Enum(`MemberRole`) 유지가 자연스럽다(직렬화 규약 §schemas).
  2. `list_all`(admin) 의 role LEFT JOIN 결과가 Req 1.2(admin 상승 미반영)·1.3(비멤버 null)을 동시에 만족하는지
     조인 형태 확정.
  3. 프론트 role 변환 단일 소스(`memberRoleToRole`)의 소유 위치 — s18 유지(Option B) vs `shared/` 이관(Option C).
  4. Req 5 병합 의미: `seedRoles` = `Map` upsert(목록 항목 덮어쓰기 + 비목록 항목 보존), 서버값 우선을
     테스트로 고정.
- **연구 이월(Research Needed)**:
  - `useDocumentScope`/`useEditorScope` 가 role 을 실제 게이팅에 사용하는 소비 지점(강제해제·편집 노출)이 있어,
    provider-role null→실값 전환이 **행동 변화**를 유발하는지 회귀 표면 확인(설계 시 소비처 감사).
  - StrictMode/이중 마운트·`refresh()` 재로드 경합 하에서 시드 브리지가 in-session 기록을 클로버링하지 않는지
    (latest-wins·runId 패턴과의 상호작용) 확인.

---

## 7. 다음 단계 (Next Steps)

- 본 격차 분석을 근거로 설계 문서를 생성한다: `/kiro-spec-design s24-role-persistence`
- 요구 승인 미완료 상태(spec.json `requirements.approved=false`)이므로, 요구 승인 후 진행하거나
  `-y` 로 요구를 자동 승인하며 설계로 직행할 수 있다.

---

## 8. 설계 결정 (Design Decisions — design.md 확정본)

> `/kiro-spec-design -y`(2026-07-21) 실행으로 §6 권고를 확정하고, 코드 실사(§2 대상 파일 전수 확인)로
> 다음을 못박았다.

### 결정 D1: 하이브리드 2-sink 는 선택이 아니라 요구 강제
- **맥락**: Req 2.2 는 "현재 워크스페이스 컨텍스트 shall role 을 null 이 아닌 실제 값으로 제공"을 명시한다.
  코드상 "현재 워크스페이스 컨텍스트"의 `role` 필드는 `CurrentWorkspaceContextValue.role`(=`useCurrentWorkspace().role`)
  이며 현재 `null` 하드코딩이다. 한편 Req 3·4 가 지목한 배지·owner 게이팅 소비자는 `MembershipRoleSource.roleFor`
  를 읽고, Req 5 의 in-session 축적(`recordOwner`/`recordSelfRole`)도 그 Map 에 산다.
- **결정**: §4.4 Option C(하이브리드)를 채택하되 **단계화가 아니라 필수 2-sink** 로 확정한다 — provider-role
  채우기(Req 2·파급) + `MembershipRoleSource` 시드(Req 3·4·5). 어느 하나만으로는  AC 전체를 못 덮는다.
- **트레이드오프**: 변경 표면이 두 곳이나, 두 sink 는 동일 기원(`WorkspaceRead.role`)에서 파생돼 모순 위험이
  낮다. 소비자 재배선(roleFor→provider-role)은 하지 않아 Req 5 공존을 자연 보존한다.

### 결정 D2: 파급 범위 확정 — 문서/편집 스코프도 provider-role null 갭의 피해자
- **맥락(신규 실사 발견)**: `useDocumentScope().role`·`useEditorScope().role` 은 provider-role 을 그대로
  통과시키므로 **항상 null** 이었고, 이는 `DocumentToolbar`/`TrashList`/`EditLockBanner` 의
  `RequireRole(EDITOR, currentRole=null)` 게이팅을 **비-admin editor/owner 에게 상시 차단**해 왔다(새로고침
  한정 아님 — admin 만 세션 override 로 통과). `MembershipRoleSource` 는 이 소비자들에 연결돼 있지 않다.
- **결정**: provider-role 채우기는 Req 2 충족인 동시에 이 상시 갭("role=null 상위갭")의 정식 해소다. 소비처
  게이팅 로직은 무변경, 신호만 복원한다. 회귀 테스트로 노출 시작을 확인한다.

### 결정 D3: 번역 단일 소스를 `shared/auth/roles.ts` 로 이관
- **맥락**: provider(app 레이어)가 role 문자열→`Role` 변환이 필요한데, `memberRoleToRole` 은 현재
  `features/workspace` 소유다. structure 스티어링상 app→features import 금지.
- **결정**: `memberRoleToRole` 를 `shared/auth/roles.ts` 로 이관(Role enum 과 co-locate)하고,
  `features/workspace/context/membershipRoleSource` 는 재-export 로 후방 호환(useMemberActions·기존 테스트
  import 무파손). 이로써 Req 2.5(단일 규칙) + 의존 방향을 동시에 만족.
- **대안 기각**: 소비처(scope 훅)에서 각자 변환 → 2.5 위반(산발). provider 인라인 변환 → 2.5 위반.

### 결정 D4: 백엔드는 B-1(리포지토리 조인), role 은 목록 경로에만 주입
- **결정**: `list_for_user` 는 member inner 조인에 `role` SELECT 추가(모든 항목 role 보장),
  `list_all` 은 호출자 `user_id` LEFT OUTER JOIN(비멤버 None, Req 1.3). 서비스가 `(ws, role)` → `WorkspaceRead`
  에 role 주입. **create/get/update/change_owner 는 role=None 유지**(optional 기본값)로 경계를 좁힌다.
- **근거**: N+1 회피(1.4), admin 상승 없음(1.2·1.3 동시 충족), L2 superset·exact-col·단일 리비전 가드 무영향.

### 결정 D5: 시드는 `MembershipRoleProvider` 내부 옵셔널 컨텍스트 읽기 + effect
- **맥락**: 부모 `CurrentWorkspaceProvider` 는 자식 훅을 호출 못 하나, `MembershipRoleProvider` 는 조립상
  **하위**라 `CurrentWorkspaceContext` 를 읽을 수 있다. `CurrentWorkspaceIndicator` 가 이미
  `useContext(CurrentWorkspaceContext)` 옵셔널 읽기 idiom 을 쓴다.
- **결정**: 별도 브리지 파일 없이 `MembershipRoleProvider` 가 옵셔널 컨텍스트를 읽어 `workspaces[].role` 을
  effect 로 `seedRoles` 한다(role=null 미시드). 컨텍스트 null(standalone 테스트)이면 미시드 → 기존 in-session
  전용 동작 보존. features→app 옵셔널 읽기는 허용 방향.
- **대안 기각**: 신규 `WorkspaceRoleSeeder` 컴포넌트 + main.tsx provider 추가 → 조립 churn 대비 이득 낮음.

## 9. 설계 합성 (Synthesis Outcomes)

- **일반화(Generalization)**: Req 2(provider-role)·3(배지)·4(owner 게이팅)·5(공존)은 모두 "단일 서버 role
  기원을 로드 시점에 복원"이라는 한 문제의 변주다. `WorkspaceRead.role` 을 단일 기원으로 삼고, 두 sink 를
  파생물로 두는 구조로 통합했다.
- **Build vs Adopt**: 새 저장소·엔드포인트·상태 컨테이너를 만들지 않고 기존 자산(member 조인·`Role` enum·
  `MembershipRoleSource` Map·provider `useMemo`)을 재사용/확장한다. 새 마이그레이션·컬럼 없음.
- **단순화(Simplification)**: 소비자 재배선(roleFor→provider-role) 회피, 신규 브리지 컴포넌트 회피, 번역
  중복 제거(shared 단일 소스). 순변경은 `role` 필드 1개·리포지토리 반환 형태·`seedRoles` 1개·번역 이관·
  provider 파생식 1개로 국소화.

## 10. 위험 (Risks & Mitigations — 설계 확정 반영)
- **provider-role null→실값 행동 변화**: 문서/편집 툴바가 비-admin editor/owner 에 노출 시작(의도된 해소).
  → 소비처 게이팅 로직 무변경 확인 + 회귀 테스트(editor 새로고침 시 툴바 노출/멤버관리 은닉).
- **시드 vs in-session 우선순위 오구현**: "방금 만든 WS 역할 소실" 회귀 가능. → `seedRoles`=upsert(목록 항목
  덮어쓰기 + 비목록 보존), 서버 우선(5.2)·미시드 in-session 유지(5.3)를 테스트로 고정.
- **마운트 순서 역전**: `MembershipRoleProvider` 가 `CurrentWorkspaceProvider` 상위로 가면 옵셔널 읽기 null →
  시드 중단. → 조립 테스트로 순서 못박음(재검증 트리거로 명시).
- **번역 이관 회귀**: import 경로 변경. → 기존 경로 재-export 로 후방 호환, 단위 테스트로 동일 함수 확인.
- **INV-3 위반(admin 상승 접합)**: → 백엔드 `list_all` 조인이 admin 여부를 role 산출에 쓰지 않음 + 시드가
  멤버십 role 만 취함을 테스트로 단언(1.2·5.4).
