# Requirements Document

## Introduction

`s06-integration-check-L2`는 **계층 2(L2)의 누적 통합 검증 체크포인트**다. 이 시점까지 완성된 upstream 누적
집합(`s01-contract-foundation` ⊕ `s02-auth` ⊕ `s03-admin-account` ⊕ `s05-workspace`)이 공유 계약과 정합하는지,
그리고 이번 계층에서 처음 결합되는 **경계(워크스페이스 권한·멤버십 ↔ 세션 인증·계정 생명주기)**가 실제 결합
상태에서 성립하는지 mock 없이 검증한다.

이 체크포인트는 **feature 로직을 구현하지 않는다.** 새 엔드포인트·서비스·스키마·마이그레이션을 추가하지 않으며,
오직 (1) 누적 upstream의 계약·경계 정합 검증과 (2) 그 검증을 실제 구현 결합으로 실행하는 integration/e2e 테스트만
소유한다. 검증의 유일한 대조 기준은 개별 spec(s02·s03·s05)의 design이 아니라 **`s01-contract-foundation`의 단일
소스**(데이터 스키마 · 세션/권한 resolver 계약 · 워크스페이스/멤버십 API 카탈로그 · 공통 에러 모델 · 불변식
카탈로그 INV-1~12)다.

L2의 검증 초점은 **권한 경계(INV-1·2, owner/editor/viewer 위계)**, **admin override(INV-3)**, **admin 소유권
변경(카탈로그 행 9, docs 2.7)**이다. 특히 `s01` `require_ws_role` resolver가 `s05`가 채운 **실제 workspace_member
데이터** 위에서 계약대로 판정하는지, 그리고 admin bypass가 모든 워크스페이스 게이트에서 성립하는지를 실제 결합으로
확인한다. 또한 아래 계층(auth·admin-account)과의 결합(삭제/비활동 사용자의 멤버십 상호작용, 유일 owner 상태
전이)까지 누적 검증한다.

이 체크포인트는 로드맵의 **게이트 G-1**(각 체크포인트가 상위 계층 impl 착수의 선행 조건이 되는 게이트 규칙)을
담당한다: 이 체크포인트가 통과하기 전에는 L3(`s07-document-core`)의 impl을 착수할 수 없다. 또한 upstream
(s01·s02·s03·s05) 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행하는 **재검증 트리거**의 대상이다.

산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md` §3 REQ-2·REQ-3·REQ-7.2, §5 INV-1·2·3·4·6,
`s01-contract-foundation/design.md`(§Physical Data Model · §API Endpoint Catalog 9~17 · §Errors · §Invariants
Catalog · §Common/Permissions), `s04-integration-check-L1/design.md`(재사용할 통합 테스트 하네스 패턴),
`.kiro/steering/roadmap.md`(게이트·재검증 트리거)를 참조한다.

## Boundary Context

- **In scope (이 체크포인트가 소유)**:
  - **계약 대조 검증**: 실제 결합된 시스템의 `workspace`·`workspace_member` 스키마, 워크스페이스/멤버십/소유권
    API(`s01` 카탈로그 행 9~17), 공통 에러 모델이 `s01` 단일 소스와 일치하는지 대조.
  - **권한 경계 검증(이번 계층 신규 경계 = 권한·멤버십)**:
    - owner가 워크스페이스를 생성하고 전체 사용자 목록에서 멤버를 role(owner/editor/viewer) 지정으로 추가한 뒤,
      role별 권한 경계가 `require_ws_role`을 통해 실제 멤버십 데이터로 성립하는지 검증(INV-1·2).
    - viewer는 읽기 전용 경계에서 owner 요구 변경 작업이 거부(403)됨(INV-2).
    - owner 요구 작업은 owner만 통과하고 editor·viewer·비멤버는 거부(403)됨(위계 owner ≥ editor ≥ viewer).
  - **admin override 검증(INV-3)**: admin이 자신이 멤버가 아닌 워크스페이스의 viewer·owner 게이트 라우트에
    모두 접근 성공(권한 검사 bypass, docs 2.6).
  - **admin 소유권 변경 검증(docs 2.7, 카탈로그 행 9)**: admin이 소유권을 변경(upsert-to-owner)하면 새 owner가
    owner 게이트를 통과하고, 비-admin 요청은 거부(403)됨.
  - **아래 계층 결합 검증(계정 생명주기 ↔ 멤버십)**:
    - 유일 owner를 admin이 비활동/삭제(s03) 처리해도 editor·viewer 멤버의 워크스페이스 활동은 무영향(docs 3.7).
    - 삭제/비활동 처리된 사용자(L1)라도 그 멤버십 행과 이름이 보존되며(INV-4), 다만 로그인은 거부됨.
  - **워크스페이스 설정 반영**: owner/admin이 `is_shareable`·`trash_retention_days`를 설정하면 실제 결합 상태에
    반영·조회됨.
  - **게이트·재검증 판정**: 위 검증 전부가 mock 없이 통과함을 게이트(G-1 규칙, L2→L3) 통과 조건으로 기록하고,
    재검증 트리거 대상(s01·s02·s03·s05)을 명시.
- **Out of scope (이 체크포인트가 소유하지 않음)**:
  - 새로운 feature 동작·엔드포인트·서비스·스키마·마이그레이션 구현(모두 s01·s02·s03·s05 소유, 이미 완료 가정).
  - 검증 중 발견된 계약 위반의 **수정** — 원인 spec(s01/s02/s03/s05)에서 고쳐야 하며, 체크포인트는 회귀를
    포착·보고만 한다.
  - **문서 도메인(L3 이상) 관심사**: editor의 문서 쓰기 권한, 문서 CRUD·이동·bundle 엔진, 잠금·버전, 휴지통, 첨부,
    공유 링크. L2에서 editor 위계는 `require_ws_role`이 워크스페이스 엔드포인트를 게이팅하는 범위에서만 관찰하며,
    editor의 문서 쓰기 권한 자체는 후속 체크포인트(s08 이상)가 검증한다.
  - 개별 spec 단위 검증의 재실행(각 spec의 자체 테스트 소유). 체크포인트는 **결합·경계**만 본다.
- **Adjacent expectations (인접 spec/계약에 대한 기대)**:
  - `s01`이 `workspace`·`workspace_member`·`user` 스키마, `WorkspaceRoleResolver`/`require_ws_role`/`Role`
    (위계 판정·admin bypass), 세션 인증(`get_current_user`/`AuthContext`), 공통 에러 모델, Base Schemas,
    엔드포인트 카탈로그(행 9~17), 불변식 카탈로그(INV-1·2·3·4)를 단일 소스로 제공한다.
  - `s05`가 카탈로그 행 10~17(워크스페이스·멤버십)과 행 9(admin 소유권 변경)의 동작을 구현하고, `workspace_member`
    데이터를 채워 `s01` resolver를 실제 role로 동작시켜 배치되어 있다(admin만 통과하던 상태 → 실제 role 판정).
  - `s02`가 로그인·세션과 계정 상태 게이트를, `s03`가 계정 생명주기(생성·비활동·삭제·재활성화)를 구현하여
    배치되어 있고, 이들이 `s01` 계약을 재정의 없이 재사용한다.
  - `s04-integration-check-L1`의 통합 테스트 하네스(마이그레이션·앱 부팅·admin 시드·세션 유지 클라이언트·계정
    생명주기 헬퍼)가 존재하며, 이 체크포인트는 그 패턴을 **확장·재사용**한다(중복 신설 금지).

## Requirements

### Requirement 1: 검증 방법론 및 대조 기준 (mock 없는 실제 결합 · s01 단일 소스 · 누적 집합 · L1 하네스 확장)

**Objective:** As a L2 통합 체크포인트, I want 누적 upstream을 실제 구현으로 결합한 상태에서 단일 계약 소스에 대조
검증하기를, so that 워크스페이스 권한 경계 회귀가 상위 계층(L3 이상)으로 전파되기 전에 조기에 포착된다.

#### Acceptance Criteria

1. The L2 Integration Checkpoint shall 모든 검증을 mock·stub·가짜 구현 없이 실제 `s01`·`s02`·`s03`·`s05` 구현을
   결합한 상태(마이그레이션 적용된 실제 DB + 실제 부팅된 애플리케이션 + 실제 서명 쿠키 세션 + 실제 workspace_member
   데이터)에서 수행한다.
2. The L2 Integration Checkpoint shall 계약 정합의 대조 기준을 항상 `s01-contract-foundation`의 단일 소스
   (데이터 스키마·엔드포인트 카탈로그·권한 resolver 계약·공통 에러 모델·불변식 카탈로그)로 삼으며, 개별 spec
   (s02·s03·s05)의 design을 기준으로 삼지 않는다.
3. The L2 Integration Checkpoint shall 어떤 feature 동작·엔드포인트·서비스·스키마·마이그레이션도 신규로 구현하지
   않고 검증 및 그 테스트 자산만 산출한다.
4. The L2 Integration Checkpoint shall `s04-integration-check-L1`의 통합 테스트 하네스 패턴(마이그레이션·앱 부팅·
   admin 시드·세션 유지 클라이언트·계정 생명주기 헬퍼)을 재사용·확장하며 동일한 하네스를 중복 신설하지 않는다.
5. If 검증 대상 시스템에 계약을 위반하는 결합 회귀가 발견되면, the L2 Integration Checkpoint shall 이를 실패로
   보고하되 원인 spec에서의 수정을 유발할 뿐 체크포인트 내부에서 feature 로직을 변경하여 우회하지 않는다.

### Requirement 2: 계약 대조 — workspace·workspace_member 스키마 · 워크스페이스/멤버십/소유권 API · 에러 모델

**Objective:** As a L2 통합 체크포인트, I want 결합된 시스템의 워크스페이스 스키마·API·에러 형태가 `s01` 단일 소스와
일치함을 확인하기를, so that s05가 계약을 벗어난 드리프트 없이 s01·s02·s03와 동일 기준 위에 얹혀 있음을 보장한다.

#### Acceptance Criteria

1. The L2 Integration Checkpoint shall 마이그레이션이 적용된 실제 DB의 `workspace` 테이블이 `s01` 물리 데이터 모델
   (`name`, `is_shareable`, `trash_retention_days`, 타임스탬프)과 컬럼·제약 면에서 일치함을 확인한다.
2. The L2 Integration Checkpoint shall 마이그레이션이 적용된 실제 DB의 `workspace_member` 테이블이 `s01` 물리
   데이터 모델(`workspace_id` FK, `user_id` FK, `role` ENUM(owner/editor/viewer), UNIQUE(workspace_id, user_id),
   INDEX(user_id))과 일치함을 확인한다.
3. The L2 Integration Checkpoint shall 부팅된 애플리케이션에 `s01` 엔드포인트 카탈로그 행 10~17(`/workspaces`
   생성·목록·상세·수정·삭제, `/workspaces/{id}/members` 추가·변경·제거)이 카탈로그가 정한 경로·메서드·요구
   role대로 노출됨을 확인한다.
4. The L2 Integration Checkpoint shall 부팅된 애플리케이션에 `s01` 엔드포인트 카탈로그 행 9(`POST
   /admin/workspaces/{id}/owner`, admin 소유권 변경)가 카탈로그가 정한 경로·메서드·admin 요구대로 노출됨을 확인한다.
5. When 결합된 시스템의 임의 워크스페이스/멤버십 엔드포인트가 오류를 반환하면, the L2 Integration Checkpoint shall
   응답이 `s01` 공통 에러 응답 형태(`code`·`message`·선택적 `field_errors`)이고 상태 코드가 에러 코드 카탈로그
   (401/403/404/409/422)와 일치함을 확인한다.
6. The L2 Integration Checkpoint shall 워크스페이스/멤버십 응답 본문이 `s01` Base Schemas 규약(`WorkspaceRead`는
   `TimestampedRead` 상속, 목록은 `Page[WorkspaceRead]`)을 따르고, `s05`가 새 마이그레이션을 추가하지 않고
   `s01` 스키마만 사용함을 확인한다.

### Requirement 3: 권한 경계 — role 위계 (INV-1·2, owner/editor/viewer via require_ws_role)

**Objective:** As a L2 통합 체크포인트, I want `s01` `require_ws_role` resolver가 `s05`가 채운 실제 멤버십 데이터
위에서 owner/editor/viewer 위계를 계약대로 판정함을 확인하기를, so that 워크스페이스 단위 권한(INV-1)과 viewer
읽기 전용(INV-2) 경계가 실제 결합에서 성립함을 보장한다.

#### Acceptance Criteria

1. When owner가 워크스페이스를 생성하고 전체 사용자 목록에서 사용자를 지정 role(owner/editor/viewer)로 멤버 추가한
   뒤, the L2 Integration Checkpoint shall 각 멤버가 자신의 세션으로 viewer 요구 라우트(`GET /workspaces/{id}`)에
   접근 가능함을 확인한다(owner/editor/viewer 모두 통과).
2. When editor 또는 viewer 멤버가 owner 요구 라우트(`PATCH`/`DELETE /workspaces/{id}`, 멤버 추가·변경·제거)에
   접근하면, the L2 Integration Checkpoint shall 요청이 403 forbidden으로 거부됨을 확인한다(INV-2 viewer 읽기 전용,
   위계 owner ≥ editor).
3. When 어떤 워크스페이스의 멤버가 아닌 사용자가 그 워크스페이스의 viewer 요구 또는 owner 요구 라우트에 접근하면,
   the L2 Integration Checkpoint shall 요청이 403 forbidden으로 거부됨을 확인한다(비멤버 접근 차단, INV-1).
4. When owner 멤버가 owner 요구 라우트에 접근하면, the L2 Integration Checkpoint shall 요청이 통과(권한 게이트
   기준 성공)함을 확인한다.
5. The L2 Integration Checkpoint shall editor 멤버가 viewer 요구 라우트는 통과하되 owner 요구 라우트는 거부됨을
   확인하여 위계상 editor가 viewer보다 높고 owner보다 낮은 중간 등급으로 판정됨을 확인한다.

### Requirement 4: admin override (INV-3) — 비멤버 워크스페이스 접근

**Objective:** As a L2 통합 체크포인트, I want admin이 자신이 멤버가 아닌 워크스페이스의 모든 권한 게이트를 bypass함을
확인하기를, so that admin 접근이 어떤 워크스페이스 권한 검사로도 차단되지 않는다는 INV-3가 실제 결합에서 성립함을
보장한다.

#### Acceptance Criteria

1. When admin이 자신이 멤버가 아닌 워크스페이스의 viewer 요구 라우트(`GET /workspaces/{id}`)에 접근하면, the L2
   Integration Checkpoint shall 접근이 성공함을 확인한다(admin bypass, docs 2.6).
2. When admin이 자신이 멤버가 아닌 워크스페이스의 owner 요구 라우트(예: `PATCH /workspaces/{id}`, 멤버 추가)에
   접근하면, the L2 Integration Checkpoint shall 접근이 성공함을 확인한다(모든 게이트에서 admin bypass, INV-3).
3. The L2 Integration Checkpoint shall admin 목록 조회(`GET /workspaces`)가 멤버 스코프에 제한되지 않고 전체
   워크스페이스를 반환함을 확인한다(admin 전체 가시성).

### Requirement 5: admin 소유권 변경 (docs 2.7, 카탈로그 행 9)

**Objective:** As a L2 통합 체크포인트, I want admin이 소유권을 변경하면 새 owner의 권한이 실제로 반영되고 비-admin은
거부됨을 확인하기를, so that admin 소유권 변경(upsert-to-owner)과 권한 resolver의 결합이 실제 결합에서 성립함을
보장한다.

#### Acceptance Criteria

1. When admin이 `POST /admin/workspaces/{id}/owner`로 어떤 사용자를 새 owner로 지정하면, the L2 Integration
   Checkpoint shall 그 사용자가 이후 그 워크스페이스의 owner 요구 라우트를 자신의 세션으로 통과함을 확인한다
   (새 owner 권한 반영).
2. When admin이 워크스페이스에 owner가 없는 상태(유일 owner가 제거·소실된 상태)에서 새 owner를 지정하면, the L2
   Integration Checkpoint shall 지정이 성공하고 새 owner가 owner 권한을 획득함을 확인한다(owner 부재 상태 복구,
   docs 3.7).
3. If 비-admin 사용자가 `POST /admin/workspaces/{id}/owner`를 호출하면, the L2 Integration Checkpoint shall
   요청이 403 forbidden으로 거부됨을 확인한다(admin 전용 게이트).
4. When admin이 존재하지 않는 워크스페이스 또는 존재하지 않는 대상 사용자로 소유권 변경을 시도하면, the L2
   Integration Checkpoint shall 요청이 404 not_found로 거부됨을 확인한다.

### Requirement 6: 계정 생명주기(L1) ↔ 멤버십 결합

**Objective:** As a L2 통합 체크포인트, I want 계정 상태 변경(s03)이 워크스페이스 멤버십·타 멤버 활동에 미치는 영향이
계약대로임을 확인하기를, so that 아래 계층(계정 생명주기)과 이번 계층(멤버십) 결합 경계가 성립하고 INV-4가 유지됨을
보장한다.

#### Acceptance Criteria

1. When admin이 어떤 워크스페이스의 유일 owner를 비활동(`is_active=false`) 또는 삭제(`is_deleted=true`) 처리하면,
   the L2 Integration Checkpoint shall 그 워크스페이스의 editor·viewer 멤버가 자신의 role에 해당하는 라우트에
   계속 정상 접근함을 확인한다(타 멤버 활동 무영향, docs 3.7).
2. When 워크스페이스 멤버인 사용자가 admin에 의해 삭제(`is_deleted=true`) 처리되면, the L2 Integration Checkpoint
   shall 그 사용자의 `workspace_member` 행과 사용자 이름이 DB에 보존됨을 확인한다(멤버십·이름 보존, INV-4).
3. When 삭제 또는 비활동 처리된 멤버가 로그인을 시도하면, the L2 Integration Checkpoint shall 로그인이 401로
   거부됨을 확인한다(계정 상태 게이트, s02 결합).
4. The L2 Integration Checkpoint shall 유일 owner 상태 전이 시나리오 전반에서 `workspace`·`workspace_member`·
   `user` 레코드에 대한 예기치 않은 물리 삭제가 발생하지 않았음을 확인한다(user는 INV-4 대상, 멤버십은 명시적
   멤버 제거 외 유지).

### Requirement 7: 워크스페이스 설정 반영 (is_shareable · trash_retention_days)

**Objective:** As a L2 통합 체크포인트, I want owner·admin이 워크스페이스 설정을 변경하면 실제 결합 상태에 반영됨을
확인하기를, so that 후속 계층(휴지통 s10·공유 s14)이 소비할 설정 계약이 이번 계층에서 성립함을 보장한다.

#### Acceptance Criteria

1. When owner가 `PATCH /workspaces/{id}`로 `is_shareable`를 변경하면, the L2 Integration Checkpoint shall 변경이
   반영되어 이후 조회(`GET /workspaces/{id}`)에서 갱신된 값이 반환됨을 확인한다.
2. When owner가 `PATCH /workspaces/{id}`로 `trash_retention_days`를 양의 정수로 변경하면, the L2 Integration
   Checkpoint shall 변경이 반영됨을 확인하며, 0 이하 값은 422로 거부됨을 확인한다.
3. When admin이 자신이 멤버가 아닌 워크스페이스의 설정을 변경하면, the L2 Integration Checkpoint shall 변경이
   성공함을 확인한다(설정 경로에서도 admin bypass, INV-3).
4. The L2 Integration Checkpoint shall 새로 생성된 워크스페이스의 기본 설정이 `is_shareable=false`이고
   `trash_retention_days`가 `s01` `Settings` 기본값임을 확인한다.

### Requirement 8: 게이트 G-1 판정 및 재검증 트리거 (누적)

**Objective:** As a 로드맵 게이트 관리자, I want L2 검증 결과가 L3 impl 착수 가부와 재검증 대상을 명확히 산출하기를,
so that L3(`s07-document-core`) impl 착수 가부와 upstream 변경 시 재실행 범위를 예측 가능하게 통제할 수 있다.

#### Acceptance Criteria

1. When Requirement 2~7의 모든 검증이 실제 결합 상태에서 통과하면, the L2 Integration Checkpoint shall 게이트를
   통과로 판정하여 L3(`s07-document-core`) impl 착수의 선행 조건 충족을 기록한다.
2. If Requirement 2~7 중 하나라도 실패하면, the L2 Integration Checkpoint shall 게이트를 미통과로 판정하고 L3
   impl 착수를 차단 상태로 표시한다.
3. The L2 Integration Checkpoint shall 재검증 트리거 대상을 명시한다: `s01`·`s02`·`s03`·`s05` 중 어느 것이
   수정되어도 이 체크포인트(및 로드맵상 그 이후 모든 체크포인트 L3~L6)를 누적 집합 기준으로 재실행해야 하며,
   `s01` 수정 시에는 모든 체크포인트를 재실행해야 한다.
