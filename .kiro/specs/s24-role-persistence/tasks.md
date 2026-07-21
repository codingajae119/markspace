# Implementation Plan

## 1. 백엔드: 워크스페이스 목록 응답의 호출자 role 조달

- [x] 1.1 WorkspaceRead 스키마에 role 가산 필드 추가
  - `role: MemberRole | None = None` optional 필드를 추가하고 기존 필드(id·name·is_shareable·trash_retention_days·타임스탬프)와 `TimestampedRead` 상속은 무변경으로 유지한다(가산만).
  - role 속성이 없는 ORM `Workspace` 를 `model_validate` 해도 role=None 으로 검증을 통과함을 단위 테스트로 확인한다.
  - 관찰 가능: 스키마 인스턴스가 role 미지정 시 None, 명시 주입 시 해당 값을 직렬화한다.
  - _Requirements: 1.1, 1.5_
  - _Boundary: WorkspaceRead (backend schema)_

- [x] 1.2 (P) 워크스페이스 리포지토리에서 호출자 role 을 단일 조인으로 조달
  - `list_for_user` 를 member_scope inner 조인에 role 컬럼을 함께 SELECT 하도록 확장해 `(Workspace, role)` 튜플 목록 + total 을 반환한다(inner 조인이라 모든 항목이 멤버십 role 보유).
  - `list_all` 에 호출자 `user_id` 인자를 추가하고 호출자 멤버십 LEFT OUTER JOIN(상관 조건: `workspace_id` 일치 AND `user_id`=호출자)으로 `(Workspace, role|None)` 을 반환한다(비멤버 WS 는 None).
  - total·정렬(id 오름차순)·limit/offset 의미는 무변경으로 유지하고, 워크스페이스별 추가 요청 없이 단일 쿼리로 role 을 제공한다(N+1·후조회 방식 미채택).
  - 관찰 가능: 단위 테스트에서 멤버 WS 는 실제 role, 비멤버 WS(admin 전체 조회 경로)는 None 을 반환하며 admin 여부에 따른 role 상승이 없다.
  - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - _Boundary: WorkspaceRepository (backend data)_

- [x] 1.3 워크스페이스 서비스에서 role 주입 및 admin 상승 금지
  - `list_workspaces` 가 `(ws, role)` 튜플을 받아 각 `WorkspaceRead` 에 role 을 주입해 매핑하고, `list_all` 호출에 `ctx.user_id` 를 전달한다.
  - admin 여부로 role 을 상승시키지 않고 리포지토리가 산출한 멤버십 role(또는 None)을 그대로 노출한다(INV-3).
  - 관찰 가능: 단위 테스트에서 비-admin·admin 모두 응답 각 item.role 이 멤버십 role 만 반영하고(admin 상승 없음), 기존 응답 필드는 무변경이다.
  - _Depends: 1.1, 1.2_
  - _Requirements: 1.1, 1.2, 1.5_
  - _Boundary: WorkspaceService (backend service)_

## 2. 공통 레이어: role 번역 단일 소스 이관 및 응답 타입 미러

- [x] 2.1 role 번역 단일 소스 shared 이관(명시적 마이그레이션, 트리 그린 유지)
  - `WorkspaceRole = "owner" | "editor" | "viewer"` 문자열 유니온을 정의하고 `memberRoleToRole(role: WorkspaceRole): Role` 를 `shared/auth/roles` 로 이관해 `Role` enum 과 co-locate 한다(번역 단일 소스, 방향 위반 없이 app·features 양측 소비).
  - 기존 `features/workspace/context/membershipRoleSource` 의 `memberRoleToRole` export 는 shared 재-export shim 으로 전환하고, `useMemberActions` 의 import 도 단일 소스에 정렬한다(동작 무변경). 이동과 shim 을 한 태스크에서 원자적으로 처리해 기존 importer·테스트가 그대로 통과하게 유지한다(후방 호환).
  - 관찰 가능: 단위 테스트에서 "owner"/"editor"/"viewer" → `Role.OWNER`/`EDITOR`/`VIEWER` 매핑이 성립하고, 기존 import 경로와 신규 shared 경로가 동일 함수를 가리키며 타입 체크가 그린이다.
  - _Requirements: 2.5_
  - _Boundary: shared/auth roles, features/workspace(re-export shim·useMemberActions) — 단일 소스 마이그레이션_

- [x] 2.2 WorkspaceRead FE 미러에 role 가산 필드 추가
  - `WorkspaceRead` FE 미러에 `role?: WorkspaceRole | null` 를 가산하고(2.1 의 `WorkspaceRole` 재사용), 기존 미러 필드는 무변경으로 유지한다(superset·백엔드 응답과 형태 정합).
  - 관찰 가능: strict 타입 체크에서 미러의 role 접근이 가능하고, 목록 응답 item 의 role 값을 소비 지점에서 읽을 수 있다.
  - _Depends: 2.1_
  - _Requirements: 1.5, 2.1_
  - _Boundary: shared/types workspace mirror_

## 3. 프론트 로드-시드 배선

- [x] 3.1 (P) CurrentWorkspaceProvider provider-role 파생
  - `value.role` 을 `null` 하드코딩에서 `currentWorkspace.role` 존재 시 `memberRoleToRole` 파생, 부재·미선택 시 null 로 대체한다(`shared` 만 import, 의존 방향 준수).
  - 워크스페이스 전환(`selectWorkspace`) 시 새 `currentWorkspace` 로 role 을 재파생하고, `CurrentWorkspaceContextValue.role` 의 형태(`Role | null`, s16 소유)는 변경하지 않는다(값 주입만).
  - 관찰 가능: 단위 테스트에서 role 있는 WS 선택 시 provider-role 이 비-null 실값, role 부재·미선택 시 null, 전환 시 전환 WS 의 멤버십 role 로 재파생된다.
  - _Depends: 2.1, 2.2_
  - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - _Boundary: CurrentWorkspaceProvider (app)_

- [x] 3.2 (P) MembershipRoleSource seedRoles 추가 및 로드-시드 병합
  - `MembershipRoleSource` 인터페이스에 `seedRoles(entries)` 를 추가하고 `Map` upsert 로 목록 항목은 서버값으로 덮어쓰고(서버 권위 우선) 목록에 없는 WS 항목은 in-session 기록을 보존한다(WS 당 단일 role 값 노출).
  - `MembershipRoleProvider` 가 옵셔널 `CurrentWorkspaceContext` 를 읽어 로드된 `workspaces` 중 role≠null 항목만 `[id, memberRoleToRole(role)]` 로 시드하고(role=null 미시드, admin override 미접합), 컨텍스트가 null 인 standalone 마운트(단위 테스트)에서는 시드하지 않아 기존 in-session 전용 동작을 보존한다.
  - `recordOwner`/`recordSelfRole` 의 동작·시그니처는 무변경으로 유지한다(시드는 대체가 아니라 보강).
  - 관찰 가능: 단위 테스트에서 시드 후 `roleFor` 가 서버 role 을 반환하고, 미시드 WS 는 in-session 값을 보존하며, role=null 항목은 시드되지 않고, in-session 과 시드가 공존해도 단일 값만 노출한다.
  - _Depends: 2.1, 2.2_
  - _Requirements: 2.1, 3.2, 4.2, 5.1, 5.2, 5.3, 5.4_
  - _Boundary: MembershipRoleSource (features/workspace)_

## 4. 통합·회귀·E2E 검증

- [x] 4.1 (P) 백엔드 목록 응답 통합 및 L2 계약 검증
  - `GET /workspaces`(비-admin): 응답 각 item 에 role 존재 + 기존 필드 무변경(superset) + 단일 응답으로 제공됨을 검증한다.
  - `GET /workspaces`(admin): 멤버 WS 는 role, 비멤버 WS 는 role null/미포함이며 admin 상승이 없음을 검증한다.
  - L2 `test_workspace_contract_conformance`(WorkspaceRead superset 필드·workspace/workspace_member exact-set 컬럼·단일 마이그레이션 리비전)가 유지 통과함을 확인한다.
  - 관찰 가능: 비-admin/admin 목록 통합 스위트와 L2 계약 가드가 모두 통과한다.
  - _Depends: 1.3_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - _Boundary: backend integration / L2 contract_

- [x] 4.2 (P) 프론트 조립·시드 통합 및 배지·owner 패널 회귀
  - `MembershipRoleProvider` + `CurrentWorkspaceProvider` 조립(마운트 순서: `MembershipRoleProvider` 가 provider 하위)에서 로드 후 `roleFor(id)` 가 시드 role 을 반환하고 role=null 항목은 null 을 유지하며, recordOwner 후 목록 재조회로 덮어써도 값이 일관됨을 검증한다.
  - 배지 회귀: in-session 이력 없이 새로고침 시 배지가 실제 role 을 표시하고, 신호가 없으면 "역할 미확인" 을 유지한다.
  - owner 패널 회귀: in-session 없이 owner role 복원만으로 멤버 관리 패널이 노출되고, editor/viewer 는 차단, admin 은 세션 경로로 통과(role 필드에 admin 미접합)됨을 검증하며, 마운트 순서를 회귀로 고정한다.
  - 관찰 가능: 조립·배지·owner 패널 통합 테스트가 통과하고 마운트 순서 역전 시 시드 중단이 회귀로 포착된다.
  - _Depends: 3.2_
  - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2_
  - _Boundary: features/workspace integration_

- [x] 4.3 provider-role 파급 복원 회귀 및 E2E critical paths
  - provider-role 이 null→실값으로 바뀌며 `useDocumentScope`/`useEditorScope` 소비처(`DocumentToolbar`/`TrashList`/`EditLockBanner`) 게이팅이 editor/owner 에게 의도대로 노출됨을 회귀로 확인한다(소비처 게이팅 로직 무변경, 파급 복원).
  - E2E 4개 role 경로: owner 새로고침(배지=owner + 멤버 관리 접근), editor 새로고침(문서 툴바 노출 + 멤버 관리 은닉), viewer 새로고침(읽기 전용·툴바/멤버 관리 미노출·배지=viewer), admin(세션 경로로 관리/툴바 통과·role 필드는 멤버십 role 만).
  - 관찰 가능: 파급 회귀 테스트와 4개 role E2E 시나리오가 모두 통과한다.
  - _Depends: 1.3, 3.1, 3.2, 4.2_
  - _Requirements: 2.2, 4.3, 4.4, 5.4_
  - _Boundary: features/document, features/editor (regression), E2E_

## Implementation Notes
- 1.2↔1.3 은 경계 간 원자적 마이그레이션 쌍이다. 1.2 가 repository 반환 형태(`list[Workspace]`→`(Workspace, role)` 튜플)와 `list_all` 시그니처(`user_id` 추가)를 바꾸면 유일 호출자 `service.py` 가 갱신되기 전까지 service/router/integration_L2 테스트가 의도적으로 깨진다. 1.2 검증은 `tests/workspace/test_repository.py` 로 스코프하고, 1.3 이 서비스 언팩·`ctx.user_id` 전달로 파손을 닫는다(1.3 완료 후 전체 백엔드 스위트 그린 확인).
- `list_all` LEFT OUTER JOIN 의 호출자 상관(`WorkspaceMember.user_id == user_id`)은 반드시 JOIN ON 절에 둔다(WHERE 에 두면 outer→inner 붕괴로 비멤버 행 탈락 = anti-join 버그, Req 1.3 위반). 동일 파일 `_assignable_filters` 의 상관 idiom 참고.
- 3.2 `MembershipRoleSource` 인터페이스에 `seedRoles` 를 **required** 로 추가(design 시그니처에 `?` 없음)하면 전체 인터페이스 객체 리터럴을 만드는 소비자 테스트 목(useMemberActions/useWorkspaceActions/MemberManagementPanel/WorkspaceSettingsPanel .test)이 tsc 필수-멤버 누락으로 깨진다 → 각 목에 `seedRoles: vi.fn()` 한 줄 가산 필요(design §Revalidation Triggers 가 인터페이스 확장=소비자 재검증 트리거로 이미 명시). 프로덕션 소비자 로직·단언은 무변경. 1.1 가산 `role` 필드가 exact-set 응답 계약 가드(`WORKSPACE_READ_KEYS`)를 깨는 것과 동형의 "가산 확장→가드 갱신" 리플.
