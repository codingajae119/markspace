# Requirements Document

## Project Description (Input)
s24-role-persistence — 재로그인/새로고침 후에도 현재 사용자의 워크스페이스별 role(owner/editor/viewer)이 복원되도록 하는 기능.

배경: 현재 `MembershipRoleSource`는 role을 메모리(React state `Map<workspaceId, Role>`)에만 best-effort로 축적하고(`recordOwner`=이번 세션 WS 생성, `recordSelfRole`=이번 세션 멤버 뮤테이션 에코), 백엔드 `WorkspaceRead`는 호출자 role을 담지 않으며 `CurrentWorkspaceProvider`는 `role: null`을 하드코딩한다. 그래서 재로그인/새로고침 시 role 신호가 사라져 로드 시점에 role을 다시 채울 데이터 경로가 아예 없다. 두 가지 결함이 발생한다: (1) 헤더 배지(`CurrentWorkspaceIndicator`)가 "역할 미확인"으로 뜬다(표시 결함). (2) 더 심각하게, owner의 `MemberManagementPanel`이 `<RequireRole minimum={OWNER} currentRole={null}>`로 게이팅 OFF되어(fallback null) **owner가 자기 워크스페이스의 멤버 관리 UI에 접근 불가**하다(기능 잠금). admin은 세션 `is_admin` 단락으로 통과하지만 일반 사용자 owner는 잠긴다.

목표: `GET /workspaces` 응답(`WorkspaceRead`)에 **호출자 관점의 role**을 실어 로드 시점에 role을 지속적으로 복원하고, 프론트가 그 값으로 `MembershipRoleSource`(또는 provider role)를 시드해 배지와 owner 게이팅이 새로고침 후에도 정확히 동작하게 한다. `GET /workspaces`는 이미 "그 사용자의 워크스페이스 목록"이라 각 WS에서 호출자의 멤버십 role을 알고 있으므로, 별도 조회 없이 응답 스키마 확장으로 충족 가능하다.

경계: 이 기능은 s05(workspace 백엔드: 스키마·repository·service·router)·s16(`CurrentWorkspaceProvider`, `WorkspaceRead` 프론트 타입)·s18(`MembershipRoleSource` 시드 경로)에 걸치는 교차 변경이며, s18~s22에 반복 기록된 "role=null 상위갭"의 정식 해소다. best-effort in-session 축적(`recordOwner`/`recordSelfRole`)은 제거 대상이 아니라 로드-시드로 보강되는 관계이며, role 파생·번역 단일 소스 규칙(`memberRoleToRole`)은 유지한다. admin override 접합 금지(INV-3) — role 필드는 멤버십 role만 담고 admin은 기존 `RequireRole`/`hasWorkspaceRole` 세션 경로가 별도 통과시킨다.

## Introduction
본 기능은 사용자의 워크스페이스별 role을 재로그인·새로고침과 무관하게 복원한다. 워크스페이스 목록 응답에 호출자 관점의 멤버십 role을 실어 서버를 권위 있는 role 출처로 삼고, 프론트는 로드 시점에 그 값으로 role 신호를 시드한다. 그 결과 (1) 헤더 역할 배지가 실제 role을 정확히 표시하고, (2) owner가 새로고침 후에도 자기 워크스페이스의 멤버 관리 UI에 접근할 수 있게 되어, 기존의 "role=null 상위갭"으로 인한 표시 결함과 owner 기능 잠금을 함께 해소한다. 이 기능은 role 신호의 **지속적 복원**에 한정되며, 권한 모델·역할 등급 체계·admin 경로 자체는 변경하지 않는다.

## Boundary Context
- **In scope**:
  - `GET /workspaces` 응답 각 워크스페이스 항목에 호출자 관점의 멤버십 role(owner/editor/viewer) 노출(가산적 확장).
  - 프론트 로드 시점에 응답 role로 현재 워크스페이스 role 신호 복원(시드).
  - 새로고침·재로그인 이후 헤더 역할 배지의 정확한 표시.
  - 새로고침·재로그인 이후 owner의 멤버 관리 UI 접근 복원.
  - 로드-시드와 기존 in-session 축적(`recordOwner`/`recordSelfRole`)의 일관된 공존(단일 값 노출).
- **Out of scope**:
  - role 필드에 admin override를 접합하는 것(INV-3) — admin 접근은 기존 세션 `is_admin` 경로 유지.
  - in-session best-effort 축적(`recordOwner`/`recordSelfRole`)의 제거·대체.
  - role 문자열→role 등급 변환 규칙·역할 등급 체계(VIEWER<EDITOR<OWNER)의 변경.
  - 문서 단위 권한, 권한 검사 자체의 로직 변경, 인증·세션·로그인 흐름 변경.
  - role 신호의 실시간 푸시·polling 갱신(로드/refresh 시점 복원에 한정).
- **Adjacent expectations**:
  - s05(백엔드 workspace): 목록 조회는 이미 호출자 멤버십을 아는 쿼리를 사용하므로, 별도 조회 없이 응답에 role을 포함할 것으로 기대한다.
  - s16(공통 레이어): `WorkspaceRead` 타입과 현재 워크스페이스 컨텍스트의 `role` 필드/기본값 소유를 유지하고, 값 주입 경로를 제공한다.
  - s18(멤버십 role 시드): role 신호를 소비하는 게이팅·표시 지점(배지·멤버 관리 패널)은 복원된 role을 그대로 사용한다.
  - admin 게이팅은 이 기능이 소유하지 않으며, 기존 `RequireAdmin`/세션 경로가 별도로 통과시킨다.

## Requirements

### Requirement 1: 워크스페이스 목록 응답의 호출자 role 노출
**Objective:** As a 인증된 사용자, I want 내 워크스페이스 목록 응답이 각 워크스페이스에서의 내 멤버십 role을 포함하기를, so that 재로그인·새로고침 이후에도 프론트가 별도 조회 없이 role을 복원할 수 있다.

#### Acceptance Criteria
1. When 인증된 사용자가 워크스페이스 목록을 요청하면, the 워크스페이스 서비스 shall 응답의 각 워크스페이스 항목에 호출자의 멤버십 role(owner/editor/viewer)을 포함한다.
2. The 워크스페이스 서비스 shall 각 항목의 role 값을 해당 워크스페이스에서의 호출자 멤버십 role로만 산출하고, admin 여부에 따른 role 상승을 반영하지 않는다.
3. If 호출자가 목록에 포함된 특정 워크스페이스에 멤버십을 가지지 않으면(예: admin 전체 조회 경로), then the 워크스페이스 서비스 shall 해당 항목의 role을 "역할 없음"(null 또는 미포함)으로 표기한다.
4. When 목록을 반환하면, the 워크스페이스 서비스 shall role을 워크스페이스별 추가 요청 없이 단일 목록 응답 안에서 함께 제공한다.
5. The 워크스페이스 서비스 shall 기존 응답 필드(id·name·is_shareable·trash_retention_days·타임스탬프)를 변경 없이 유지하고 role을 가산적으로만 추가한다.

### Requirement 2: 로드 시점 role 복원(프론트 시드)
**Objective:** As a 워크스페이스에 소속된 사용자, I want 앱 로드 시 내 role이 목록 응답으로부터 복원되기를, so that 새로고침·재로그인 이후에도 role 기반 UI가 정확히 동작한다.

#### Acceptance Criteria
1. When 워크스페이스 목록이 로드되면, the 현재 워크스페이스 컨텍스트 shall 응답의 role 값으로 각 워크스페이스의 role 신호를 시드한다.
2. While 현재 워크스페이스가 선택되어 있고 그 role이 복원되어 있으면, the 현재 워크스페이스 컨텍스트 shall role을 null이 아닌 실제 값(owner/editor/viewer)으로 제공한다.
3. When 사용자가 다른 워크스페이스로 전환하면, the 현재 워크스페이스 컨텍스트 shall 전환된 워크스페이스의 호출자 멤버십 role을 반영한다.
4. If 로드된 워크스페이스 항목에 role 값이 존재하지 않으면(멤버십 없음 등), then the 현재 워크스페이스 컨텍스트 shall 해당 워크스페이스의 role 신호를 "역할 없음"(null)으로 유지한다.
5. The 현재 워크스페이스 컨텍스트 shall role 문자열→내부 role 등급 변환을 단일 변환 규칙을 통해서만 수행하고, 변환 로직을 소비 지점마다 흩뿌리지 않는다.

### Requirement 3: 헤더 역할 배지 정확성
**Objective:** As a 사용자, I want 헤더의 워크스페이스 역할 배지가 새로고침 이후에도 내 실제 role을 표시하기를, so that "역할 미확인"으로 잘못 표시되지 않는다.

#### Acceptance Criteria
1. While 현재 워크스페이스의 role이 복원되어 있으면, the 역할 표시기 shall 해당 role(owner/editor/viewer)을 배지로 표시한다.
2. When 사용자가 새로고침하거나 재로그인 후 진입하면, the 역할 표시기 shall 이번 세션의 생성·뮤테이션 이력이 없더라도 복원된 role을 표시한다.
3. If 현재 워크스페이스의 role 신호가 존재하지 않으면(멤버십 없음 등), then the 역할 표시기 shall 기존의 "역할 미확인" 표시를 유지한다.

### Requirement 4: owner 멤버 관리 접근 복원
**Objective:** As a 워크스페이스 owner, I want 새로고침·재로그인 이후에도 내 워크스페이스의 멤버 관리 UI에 접근할 수 있기를, so that role 신호 소실로 멤버 관리 기능이 잠기지 않는다.

#### Acceptance Criteria
1. While 현재 사용자가 현재 워크스페이스의 owner이고 role이 복원되어 있으면, the 멤버 관리 게이팅 shall 멤버 관리 패널 접근을 허용한다.
2. When owner가 새로고침 후 진입하면, the 멤버 관리 게이팅 shall 이번 세션의 in-session 축적 신호가 없더라도 복원된 role만으로 접근을 허용한다.
3. While 현재 사용자가 현재 워크스페이스에서 editor 또는 viewer이면, the 멤버 관리 게이팅 shall 멤버 관리 패널 접근을 차단한다.
4. Where 사용자가 admin이면, the 멤버 관리 게이팅 shall 기존 세션 기반 admin 경로로 접근을 허용하고, role 필드에는 admin 상승을 담지 않는다.

### Requirement 5: in-session 축적과의 공존 및 불변식 유지
**Objective:** As a 유지보수자, I want 로드-시드가 기존 best-effort in-session 축적을 대체하지 않고 보강하기를, so that 세션 중 생성·뮤테이션 에코와 로드 복원이 모순 없이 공존한다.

#### Acceptance Criteria
1. While 사용자가 세션 도중 워크스페이스를 생성하거나 자기 멤버십을 변경하면, the 현재 워크스페이스 컨텍스트 shall 기존 in-session role 기록(`recordOwner`/`recordSelfRole`) 동작을 그대로 유지한다.
2. When 동일 워크스페이스에 대해 로드-시드 role과 in-session 기록이 모두 존재하면, the 현재 워크스페이스 컨텍스트 shall 서버 권위 값인 로드-시드를 우선 적용하고 단일 role 값만 노출한다(모순된 두 값 동시 노출 금지).
3. If 특정 워크스페이스에 로드-시드 role이 아직 없으면(예: 방금 생성되어 목록 재조회 이전), then the 현재 워크스페이스 컨텍스트 shall in-session 기록으로 해당 워크스페이스의 role 신호를 채운다.
4. The 현재 워크스페이스 컨텍스트 shall role 신호에 멤버십 role만 담고 admin override를 접합하지 않는다(INV-3).
