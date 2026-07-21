# Gap Analysis — s26-open-access-roles

역할 모델을 owner/editor/viewer 3단계에서 owner/member 2단계로 재편하고, 문서 읽기 경계를
전역 개방하는 요구(requirements.md)와 현재 코드베이스 사이의 구현 갭 분석. 설계 단계(HOW)의
의사결정을 돕기 위한 정보·옵션 제시이며 최종 선택은 하지 않는다.

## 1. 현재 상태 조사 (Current State)

### 1.1 권한 근간 — s01 `app/common/permissions.py`
- **`Role(IntEnum)`**: `VIEWER=1 < EDITOR=2 < OWNER=3`. 정수 순서 = 권한 포함 관계. 모든
  위계 비교(`role >= minimum`)와 admin bypass 판정의 **단일 소스**.
- **`_ROLE_MAP: dict[str, Role]`**: `{"owner","editor","viewer"} → Role`. WS_member.role 문자열을
  위계 비교용 Role 로 매핑. 미정의 문자열은 매핑 제외 → `resolve()` 가 `None`(비멤버 동일 취급).
- **`WorkspaceRoleResolver.resolve() / has_at_least()`**: workspace_member 단건 조회로 role·admin
  bypass(INV-3) 판정. `has_at_least` 는 `ctx.is_admin` 이면 조회 없이 True.
- **`require_ws_role(minimum)`** (FastAPI 의존성 팩토리), **`require_admin`** (admin 전용 게이트,
  중앙 단일 정의 — feature 재정의 금지).
- 의존 방향: db·auth·errors·models 만 import. routers·feature 도메인 import 금지.

### 1.2 API 직렬화 role — `app/workspace/schemas.py`
- **`MemberRole(str, Enum)`**: `OWNER="owner"`, `EDITOR="editor"`, `VIEWER="viewer"`. 요청/응답
  직렬화 전용. 위계 비교용 `Role`(IntEnum)과 **별개 타입**.
- 요청 스키마(`MemberCreate.role`, `MemberUpdate.role`)가 `MemberRole` 타입이므로, **enum 값
  집합을 바꾸면 그 외 문자열("editor"·"viewer")은 pydantic 이 자동 422 거부**(Req 1.4 자동 충족).
- **`WorkspaceRead.role: MemberRole | None = None`**: s24가 추가한 가산 optional 필드
  (호출자 관점 role, 비멤버 None). 현재 `list_workspaces` 만 `_to_read()` 로 명시 주입하고,
  `get_workspace` 는 주입하지 않아 항상 None.

### 1.3 DB 스키마 — `migrations/versions/0001_initial_schema.py`
- `workspace_member.role` = `sa.Enum("owner","editor","viewer", name="workspace_member_role")`,
  `nullable=False`. **마이그레이션 head = 0003** (0002 autosave, 0003 last_selected_workspace_id).
- 단일 owner 불변식: 코드 관례(생성 시 요청자 owner화)로 유지, DB 제약은 UNIQUE(ws,user)뿐.

### 1.4 "활성 사용자" 게이트 — `app/common/auth.py`
- **`get_current_user`**: 세션 `user_id` → User 로드 → `is_active=False`·`is_deleted=True` 거부 →
  `AuthContext(user_id, is_admin)`. **이것이 곧 요구되는 "활성 사용자" 판정**(Req 3.6). 전역
  읽기는 이 게이트를 그대로 재사용하면 되고 새 판정 로직 불필요.

### 1.5 읽기 5개 엔드포인트 — 현재 게이트
| # | 엔드포인트 | 파일 | 현재 게이트 | workspace_id 원천 |
|---|-----------|------|------------|------------------|
| 1 | `GET /workspaces/{id}/documents` (문서 트리) | `document/router.py:117` | `require_ws_role(VIEWER)` | 경로 id=ws_id 직접 |
| 2 | `GET /documents/{id}` (문서 상세) | `document/router.py:135` | `ws_role_for_document(VIEWER)` | 문서→ws 어댑터 |
| 3 | `GET /documents/{id}/versions` (버전 이력) | `lock_version/router.py:128` | `ws_role_for_document(VIEWER)` | 문서→ws 어댑터 |
| 4 | `GET /attachments/{id}` (첨부 조회/다운로드) | `attachment/router.py:122` | `ws_role_for_attachment(VIEWER)` | 첨부→ws 어댑터 |
| 5 | `GET /workspaces/{id}` (WS 상세) | `workspace/router.py:99` | `require_ws_role(VIEWER)` | 경로 id=ws_id 직접 |

- **어댑터 패턴**(`document/dependencies.py`, `attachment/dependencies.py`): 리소스 id →
  workspace_id 매핑(미존재 시 **판정보다 먼저 404**) → s01 `require_ws_role` 위임. 전역 읽기는
  "매핑(존재검사→404)은 유지, role 위임은 제거하고 활성 사용자만 요구"로 변형해야 한다.

### 1.6 편집·관리 게이트 (변경 대상)
- **편집 계열(→ member 통일)**: 문서 생성/수정/이동/삭제(`ws_role_for_document(EDITOR)`),
  잠금/저장/취소(`lock_version/router.py` EDITOR), 첨부 업로드(EDITOR), 공유 발급/토글
  (`sharing/router.py`), 휴지통 목록/복원/완전삭제(`trash/router.py` EDITOR, `ws_role_for_bundle`).
- **관리 계열(owner 유지)**: WS 수정/삭제, 멤버·assignable 조회, 멤버 추가/변경/제거
  (`require_ws_role(OWNER)`), force-unlock(`lock_version/router.py` OWNER). **변경 없음**.

### 1.7 프론트엔드 미러
- **`shared/auth/roles.ts`**: `Role` enum(VIEWER=1/EDITOR=2/OWNER=3), `WorkspaceRole =
  "owner"|"editor"|"viewer"`, `memberRoleToRole()` 문자열→enum 번역 **단일 소스**.
- **`shared/auth/permissions.ts`**: `hasWorkspaceRole({currentRole, isAdmin, minimum})` — admin
  우선 통과 → null 거부 → `currentRole >= minimum`. 백엔드 resolver 미러.
- **`features/workspace/api/types.ts`**: `MemberRole = "owner"|"editor"|"viewer"` (feature 미러).
- **`features/workspace/components/RoleSelect.tsx`**: `ROLE_OPTIONS` 3값으로 옵션 **폐쇄** —
  owner/editor/viewer 리터럴 배열. 2값으로 축소 대상.
- **s24 role 복원**: `roleSeedAssembly`·`membershipRoleSource`·provider-role. 메커니즘 유지,
  복원되는 값 집합만 owner/member 로 변경(Req 6.5).

### 1.8 회귀 테스트 표면 (규모)
- Backend: `Role.VIEWER|EDITOR / "viewer"|"editor" / require_ws_role / ws_role_for` 패턴이
  **73개 파일·449회** 출현. 특히 `test_permissions.py`(24), `test_membership_service.py`(26),
  L2 `test_permission_boundary.py`(15), `test_admin_override.py`(6), L3 권한 게이팅 스위트,
  L4~L6 누적 계약 스위트, `test_migration_roundtrip.py`.
- Frontend: role 관련 ~30개 파일(roles.test·permissions.test·RoleSelect.test·roleSeedAssembly·
  memberRoster.e2e·rolePersistence.e2e 등).

## 2. 요구사항-자산 매핑 (Requirement → Asset Map)

| 요구 | 대상 자산 | 갭 태그 | 비고 |
|------|----------|--------|------|
| R1.1~1.3 role 2단계·직렬화 | `Role`(IntEnum), `MemberRole`(str Enum) + FE `roles.ts` | **Constraint** | IntEnum 수치 재정의(VIEWER 삭제, EDITOR→MEMBER). FE 미러 동기 필수 |
| R1.4 잘못된 role 거부 | `MemberCreate/Update.role: MemberRole` | **자동충족** | enum 값 집합 축소 시 pydantic 이 자동 422 |
| R1.5 admin bypass | `get_current_user`·`require_admin`·resolver | **없음** | INV-3 불변, 변경 없음 |
| R2.1~2.4 데이터 이관 | `workspace_member.role` ENUM (mig 0001) | **Missing** | 신규 마이그레이션 0004 필요 |
| R2.5 롤백 비대칭(member→editor) | 0004 `downgrade()` | **Missing** | viewer 미복구 = 의도된 비대칭 |
| R3.1~3.4 읽기 전역 개방(문서·트리·버전·첨부) | 읽기 4개 게이트 + 어댑터 | **Missing** | role 게이트 → 활성 사용자 게이트 전환 |
| R3.5 WS 상세 role 호출자 관점 | `WorkspaceService.get_workspace` | **Missing** | resolver.resolve 로 role 주입(비멤버 null) |
| R3.6 미인증·비활성 거부 | `get_current_user` | **없음** | 기존 게이트 재사용 |
| R3.7 리소스 부재 404 | 어댑터 존재검사 + 서비스 404 | **Constraint** | 매핑 존재검사(404)는 유지, role 위임만 제거 |
| R3.8 비멤버 200(403 제거) | 읽기 경로 anti-enum 403 | **Missing** | 읽기 경로 403 → 200 전환 |
| R4.1~4.6 멤버 편집 권한 | 편집·휴지통 EDITOR 게이트 | **Missing** | `Role.EDITOR` → `Role.MEMBER` 일괄 전환 |
| R5.1~5.5 owner 관리 유지 | OWNER 게이트 다수 | **없음** | 유지(Role.OWNER 존치) |
| R6.1~6.5 FE 정합 | `roles.ts`·`permissions.ts`·`types.ts`·`RoleSelect.tsx`·s24 복원 | **Missing** | BE 미러 동기 |
| R7.1~7.5 불변식·회귀 | L1~L6 + 단위 권한 테스트(73파일) | **Missing** | 대규모 테스트 갱신 |
| Adjacent: steering 갱신 | `product.md`·`tech.md` "owner/editor/viewer"·"viewer 권한" 문구 | **Missing** | 문서 정합 |

## 3. 핵심 설계 쟁점 (Research Needed — 설계 단계 결정)

1. **`Role` IntEnum 재설계**: 2단계 표현 방식. `MEMBER=1, OWNER=2`(간결, 재번호)가 유력하나
   **FE `roles.ts` 수치와 반드시 동기**해야 한다(현 VIEWER=1/EDITOR=2/OWNER=3). `EDITOR` 심볼을
   `MEMBER` 로 리네임할지, 하위 호환 alias 를 둘지 결정. (권장: 폐쇄형 시스템·단일 배포이므로
   깔끔한 리네임.) **[Research Needed]**
2. **읽기 게이트 전환 형태**: (a) 새 활성-사용자 어댑터(`require_active_user_for_document/
   _for_attachment` — 존재검사 404 후 role 위임 없이 `get_current_user` 만) 신설 vs (b) 기존
   어댑터에 "읽기 모드" 파라미터 추가. 경계 규칙(어댑터는 매핑만, 판정은 s01)과 정합하는 형태
   선택. **[Research Needed]**
3. **문서 트리 비멤버·부재 워크스페이스 응답**: `GET /workspaces/{id}/documents` 는 Page 반환.
   전역 개방 후 (a) 존재하는 WS 비멤버 → 200 트리, (b) **존재하지 않는 WS** → 404 vs 빈 200.
   R3.7(리소스 부재 404)이 문서·WS·첨부를 명시하므로 트리도 WS 부재 시 404 가 정합적이나, 현재
   경로엔 WS 존재검사가 없다(게이트가 대신 403). 존재검사 추가 위치 결정 필요. **[Research Needed]**
4. **ENUM 마이그레이션 순서(MySQL)**: `ALTER ... MODIFY role ENUM('owner','editor','viewer','member')`
   → `UPDATE ... SET role='member' WHERE role IN('editor','viewer')` → `ALTER ... MODIFY role
   ENUM('owner','member')`. downgrade 는 역순 + `member→editor`. 3-스텝 원자성·중간 상태 검증.
   **[Research Needed]**
5. **"단일 0001" 가드 회귀**: memory `user-settings-additive` 기록 — 마이그레이션 추가 시 L2~L6
   의 마이그레이션 개수/head 가드 테스트가 갱신 대상. 0004 추가로 head=0004 로 이동, 관련 가드
   동기 필요. **[Research Needed — 영향 파일 목록화]**
6. **트리·휴지통 경계 유지**: R7.4 — 휴지통 목록은 전역 개방에서 **제외**(member 이상 유지).
   `trash/router.py` EDITOR→MEMBER 로만 바꾸고 활성-사용자 게이트로 내리지 않도록 주의.

## 4. 구현 접근 옵션 (Options)

### Option A — 기존 컴포넌트 in-place 전환 (권장)
`Role`/`MemberRole` enum 값 집합을 그 자리에서 재정의하고, 읽기 5개 게이트를 활성-사용자
게이트로 교체, `Role.EDITOR`→`Role.MEMBER` 일괄 치환, 마이그레이션 0004 추가, FE 미러 동기,
테스트 갱신. VIEWER 삭제가 강제 함수로 모든 변경점을 드러낸다.
- ✅ s01 단일 소스 구조를 그대로 활용 — 판정 로직 재구현 없음.
- ✅ enum 축소로 잘못된 role 거부(R1.4)·직렬화(R1.3)가 자동 정합.
- ✅ 폐쇄형·단일 배포 환경이라 병렬 모델·플래그 불필요.
- ❌ 449회 출현 지점의 광범위한 기계적 수정 — 누락 위험(테스트가 방어).
- ❌ 데이터 마이그레이션 downgrade 비대칭(viewer 소실) 문서화 필요.

### Option B — 신규 병렬 role 모델 도입
새 2단계 타입을 추가하고 구 3단계를 deprecate 하며 점진 이관.
- ✅ 이론상 롤백 안전, 구·신 공존.
- ❌ 폐쇄형·외부 소비자 없음·단일 배포이므로 **과설계**. 두 모델 동시 유지가 오히려 불변식
  일관성을 해친다. 비권장.

### Option C — 단계적(phased) 하이브리드
Phase 1: BE role 축소 + 마이그레이션 → Phase 2: 읽기 전역 개방 → Phase 3: FE 미러·테스트.
- ✅ 리뷰 게이트를 축(역할 축소 vs 읽기 개방)별로 분리 — task 분해·검증에 유리.
- ✅ 최종 상태는 Option A 와 동일(구현 순서 전략일 뿐).
- ❌ Phase 경계에서 BE·FE role 값 집합 불일치 구간 발생(중간 테스트가 일시적으로 red).
- **활용**: Option A 를 채택하되 **task 순서를 C 의 3축으로 분해**하는 절충이 현실적.

## 5. 노력·리스크 (Effort & Risk)

- **Effort: L (1–2주)** — 신규 알고리즘·기술 없음(전부 기존 패턴)이나 7개 도메인 + 공통 권한
  근간 + FE 미러 + L1~L6 6단계 통합 + 데이터 마이그레이션에 걸친 **넓은 blast radius**. 개별
  변경은 얕지만 지점이 많다(449회/73파일 + FE ~30파일).
- **Risk: Medium** — 미지 기술 없음·판정 로직은 s01 단일 소스라 재구현 없음(리스크↓). 그러나
  (a) 데이터 마이그레이션 + downgrade 비대칭, (b) 읽기 403→200 경계 변경이 anti-enumeration
  기대와 충돌 가능(L2~L6 권한 경계 테스트 대량 갱신), (c) BE/FE role 수치 미러 동기 실패 시
  게이팅 오작동 — 이 3축이 medium 요인. 강한 회귀 스위트(L1~L6)가 안전망.

## 6. 설계 단계 권고 (Recommendations)

- **선호 접근**: Option A(in-place 전환) + task 순서는 Option C 3축 분해(역할 축소 → 읽기 개방
  → FE·회귀).
- **핵심 결정 선확정**(§3): ① `Role` 2단계 수치·심볼(MEMBER/OWNER) 및 FE 동기, ② 읽기 게이트
  전환 형태(신규 활성-사용자 어댑터 권장), ③ 트리·부재 WS 404 정책, ④ ENUM 3-스텝 마이그레이션,
  ⑤ "단일 0001/head" 가드 영향 파일 목록.
- **불변식 명문화**: INV-1 을 "편집·관리에 한해 유지, 읽기에 한해 완화"로 재서술(R7.1·7.2),
  공유 링크 토큰·is_shareable 게이트는 **미변경**(R7.3), 휴지통은 개방 제외(R7.4)를 설계에 못박기.
- **Carry-forward research items**: §3 의 5개 [Research Needed] 항목.
- **문서 정합**: `product.md`·`tech.md` 의 "owner/editor/viewer"·"viewer 권한"·"viewer mode" 문구
  갱신을 tasks 에 포함(Adjacent expectation). 단, Toast UI "viewer mode"(읽기 렌더 모드)는 role
  이름이 아니므로 혼동 주의 — 렌더 모드 명칭은 유지.

## 7. 설계 결정 (Design Decisions — 확정)

설계 단계에서 §3 의 5개 [Research Needed] + 파생 쟁점을 확정한다. 각 결정은 design.md
의 Boundary·Components 로 반영된다.

### D1 — `Role` IntEnum 2단계 재설계 (§3-1 확정)
- **선택**: `Role(IntEnum) = {MEMBER=1, OWNER=2}`. `VIEWER` 삭제, `EDITOR` 심볼 → `MEMBER`
  리네임, **하위 호환 alias 없음**. `_ROLE_MAP = {"owner": OWNER, "member": MEMBER}`
  (editor/viewer 제거).
- **근거**: 폐쇄형·외부 소비자 없음·단일 배포이므로 깔끔한 리네임이 alias 유지보다 명료하다.
  `EDITOR` 심볼 리네임은 강제 함수로 모든 편집 게이트 호출지점(9개 파일 20+ 회)을
  드러낸다 — 누락하면 컴파일/임포트 에러로 즉시 발각된다.
- **FE 동기(필수)**: `frontend/src/shared/auth/roles.ts` 의 `Role` enum 을 `{MEMBER=1,
  OWNER=2}` 로 동일 재번호. 수치 순서(1<2)가 BE·FE 양측 위계 비교의 계약이므로 두 값이
  일치해야 게이팅이 정합한다.
- **Follow-up**: 읽기 게이트 전환으로 `Role.VIEWER` 참조는 앱 코드에서 모두 사라진다
  (읽기 게이트가 VIEWER 를 쓰던 유일한 소비처였다). 잔존 참조는 테스트에만 존재 → 회귀 갱신.

### D2 — 읽기 게이트 = 편집 어댑터에서 role 위임 제거 (§3-2 확정)
- **선택**: Option (a) 신규 활성-사용자 게이트. 편집 어댑터(`ws_role_for_*`)의 "id→ws
  매핑(부재 404)" 절반은 유지하고 "s01 role 위임" 절반만 제거한 대칭 게이트 3종을 신설한다.
  - `require_active_workspace(workspace_id)` — **common** 신설. WS 존재→404, 활성 사용자만
    요구, role 판정 없음. 문서 트리 소비.
  - `active_user_for_document(id)` — **document/dependencies.py** 신설. 문서→ws 매핑,
    None→404, ctx 반환. 문서 상세 + 버전 이력(재사용) 소비.
  - `active_user_for_attachment(id)` — **attachment/dependencies.py** 신설. 첨부→ws 매핑,
    None→404, ctx 반환. 첨부 서빙 소비.
- **근거**: role 위임을 제거하면 403 발생 지점 자체가 사라져 R3.8(비멤버 200)이 구조적으로
  충족된다. 기존 어댑터의 존재검사(404) 위치를 그대로 보존 → R3.7 회귀 없음. 새 판정 로직
  재구현 없음(s01 단일 소스 존중).
- **common 배치 근거**: `require_active_workspace` 는 문서 트리(document router)가 소비하는데,
  document 가 workspace 도메인을 import 하면 교차-feature 위반이다. `Workspace` 는 공통 모델
  (`app.models`)이고 common 은 이미 `WorkspaceMember` 를 조회하므로, WS 존재 게이트를 common
  에 두면 교차-feature import 없이 좌측(common) 의존만으로 해결된다. structure.md "권한 검사는
  공통 레이어" 원칙과 정합.
- **WS 상세 예외**: `GET /workspaces/{id}` 는 서비스가 이미 WS 를 로드(role 주입 위해)하므로
  게이트는 `get_current_user`(활성만)로 두고 존재검사+role 주입은 서비스가 수행(D3). 별도
  게이트 불필요.

### D3 — WS 상세 role 호출자 관점 주입 (§3 파생, R3.5 확정)
- **현재**: `WorkspaceService.get_workspace(db, workspace_id)` 는 `WorkspaceRead.model_validate
  (ws)` 만 반환 → `role` 항상 None(호출자 role 미주입). `list_workspaces` 만 `_to_read(ws,
  role)` 로 주입.
- **선택**: `get_workspace` 시그니처에 `ctx: AuthContext` 추가. WS 로드(None→404) 후 호출자
  멤버십 role 문자열(owner/member/None)을 조회해 기존 `_to_read(ws, role_str)` 재사용으로
  주입한다. 비멤버는 None, admin 상승 없음(INV-3).
- **근거**: `_to_read` 가 이미 role 주입 로직(문자열→MemberRole, None 허용)을 캡슐화하므로
  재사용한다. role 문자열은 `MembershipRepository.get(db, ws_id, user_id).role`(없으면 None).

### D4 — 편집 게이트 `EDITOR`→`MEMBER` 일괄 (R4 확정)
- **선택**: 편집·휴지통 계열 모든 `Role.EDITOR` 게이트를 `Role.MEMBER` 로 치환. 대상(9지점):
  document create(1)·rename/move/trash(3), lock/save/cancel(3), attachment upload(1),
  sharing issue/toggle(2), trash list(1)·restore/purge(2). force-unlock 은 `Role.OWNER` 유지.
- **R7.4 주의**: 휴지통 목록(`trash/router.py`)은 전역 읽기 개방에서 **제외** — `require_ws_role
  (EDITOR)`→`require_ws_role(MEMBER)` 로만 낮추고 활성-사용자 게이트로 내리지 않는다.
- **자동 정합**: `EDITOR` 심볼을 enum 에서 리네임하므로 잔존 `Role.EDITOR` 는 즉시 임포트
  에러 → 누락 방어.

### D5 — 마이그레이션 0004 (3-스텝 ENUM, §3-4 확정)
- **head**: 0003 → 0004 (down_revision="0003"). 비-additive(ENUM MODIFY)로 0002/0003 의
  가산 패턴과 다르다.
- **upgrade**(3-스텝 원자성):
  1. `ALTER TABLE workspace_member MODIFY role ENUM('owner','editor','viewer','member') NOT NULL`
     (확장: 4값 임시)
  2. `UPDATE workspace_member SET role='member' WHERE role IN ('editor','viewer')` (데이터 이관)
  3. `ALTER TABLE workspace_member MODIFY role ENUM('owner','member') NOT NULL` (축소: 2값)
- **downgrade**(역순, 비대칭):
  1. `ALTER ... MODIFY role ENUM('owner','editor','viewer','member') NOT NULL`
  2. `UPDATE ... SET role='editor' WHERE role='member'` (**viewer 미복구 — R2.5 의도된 비대칭**)
  3. `ALTER ... MODIFY role ENUM('owner','editor','viewer') NOT NULL`
- **단일 owner 불변식(R2.3)**: UPDATE 가 owner 행을 건드리지 않으므로 WS 당 owner 개수 불변.
- **roundtrip**: 구조 roundtrip(upgrade→downgrade→구조 비교)은 ENUM 구조가 owner/editor/viewer
  로 복귀해 통과. 데이터 비대칭(viewer 소실)은 구조 테스트가 잡지 않는 의도된 결과.

### D6 — `MemberRole`(schemas) 2값 (R1.3·1.4 확정)
- **선택**: `MemberRole(str, Enum) = {OWNER="owner", MEMBER="member"}` (EDITOR/VIEWER 제거).
- **자동 충족**: `MemberCreate.role`·`MemberUpdate.role: MemberRole` 이므로 "editor"/"viewer"
  요청은 pydantic 이 라우터 계층에서 자동 422(R1.4). 응답 직렬화도 owner/member 로 자동 정합
  (R1.3). 서비스 재검증 불필요.

### D7 — "단일 0001/head" 가드 영향 파일 (§3-5 확정)
0004 추가로 `revision_files == [0001,0002,0003]` / `heads == ["0003"]` 를 단언하는 가드가
전부 red 로 전환된다. 확인된 소비처:
- `tests/integration_L2/test_workspace_contract_conformance.py` (546·557)
- `tests/integration_L4/test_cumulative_contract_conformance.py` (363·374)
- `tests/integration_L5/test_cumulative_contract_conformance.py` (369·380)
- `tests/integration_L6/test_cumulative_contract_conformance.py` (408·419)
- `tests/workspace/test_owner_change_integration.py` (395)
- `tests/attachment/test_app_assembly.py` (84)
- `tests/test_migration_roundtrip.py` (계약 테이블 roundtrip — ENUM 구조 복귀 반영)
- (L3 누적 스위트도 동일 패턴 존재 가능 — task 에서 grep 재확인)
각 가드는 `[…,"0004_open_access_roles.py"]` / `["0004"]` 로 갱신한다.

## 8. 설계 합성 (Synthesis)

### 8.1 Generalization
- **읽기 5개 = "활성 사용자 + 대상 존재"의 5 변주**. 활성-사용자 판정은 `get_current_user`
  단일 소스로 균질하고, 존재 확인만 리소스별(WS/문서/첨부)로 다르다. 따라서 편집 어댑터
  3종(require_ws_role·ws_role_for_document·ws_role_for_attachment)과 **1:1 대칭**인 읽기
  게이트 3종으로 일반화한다(D2). "읽기 게이트 = 편집 어댑터 − role 위임"이 통일 규칙.

### 8.2 Build vs. Adopt
- **전부 Adopt(기존 s01 인프라 재사용)**. 새 라이브러리·알고리즘 없음. `get_current_user`
  (활성 게이트)·`WorkspaceRoleResolver`(role 조회)·`_to_read`(role 주입)·기존 어댑터 매핑
  패턴을 그대로 소비한다. 병렬 role 모델(Option B)은 폐쇄형 환경에서 과설계로 기각.

### 8.3 Simplification
- **alias·플래그·병렬 모델 제거**: `Role` 하위 호환 alias 없음, feature 플래그 없음, 구·신
  role 공존 없음(단일 배포). enum 값 집합 축소만으로 잘못된 role 거부·직렬화가 자동 정합
  하므로 별도 검증기·화이트리스트를 신설하지 않는다(D6).
- **task 순서만 3축 분해(Option C)**: 최종 상태는 Option A(in-place)와 동일하되, 구현·리뷰
  순서를 ①BE role 축소+마이그레이션 → ②읽기 전역 개방 → ③FE 미러+회귀 로 나눈다.

## 9. 리스크 & 완화 (갱신)
- **BE/FE role 수치 미러 불일치** → 게이팅 오작동. 완화: D1 에서 두 파일(`permissions.py`·
  `roles.ts`)을 동일 값으로 명시, `permissions.test`/`roles.test` 가 즉시 검증.
- **읽기 403→200 경계 변경이 anti-enumeration 기대와 충돌** → L2~L6 권한 경계 테스트 대량
  갱신. 완화: 읽기 경로는 열거-방지 403 을 **의도적으로 제거**(R3.8)함을 설계에 명문화,
  경계 테스트 기대값을 200 으로 전환.
- **데이터 마이그레이션 downgrade 비대칭(viewer 소실)** → 롤백 시 정보 손실. 완화: R2.5 의
  의도된 비대칭임을 0004 downgrade 주석·design.md 에 명문화.
- **head-guard 대량 red** → CI 실패. 완화: D7 영향 파일 목록을 회귀 task 에 포함.
