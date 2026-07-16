# Requirements Document

## Introduction

`s05-workspace`는 Notion-lite의 **협업 권한 단위인 워크스페이스**를 구현한다. 워크스페이스 CRUD,
멤버십(owner/editor/viewer) 관리, 워크스페이스 단위 권한 판정, 공유 게이트(`is_shareable`)·휴지통
보관일(`trash_retention_days`) 설정, 그리고 admin 소유권 변경이 이 경계에 모인다.

이 spec은 프로젝트의 **권한 모델을 실제로 동작시키는 계층**이다. `s01-contract-foundation`이 정의한
워크스페이스 권한 resolver(owner ≥ editor ≥ viewer 위계 + admin bypass)는 `workspace_member` 데이터가
채워지기 전까지 admin만 통과시킨다. 이 spec이 멤버십 데이터를 소유·채움으로써 resolver가 실제 role을
근거로 판정하게 되고, 이후 문서·잠금·휴지통·첨부·공유 등 모든 하위 도메인이 이 권한 경계에 의존한다.
따라서 권한 불변식 INV-1·2·3의 실동작 정합이 이 spec의 핵심 성공 기준이다.

산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md`(§1.2 권한 3종, §2.2~2.3 워크스페이스·멤버십
데이터 모델, §3 REQ-2.7·REQ-3·REQ-7.2, §5 INV-1·2·3·6)를 참조한다. 모든 계약 엔티티(스키마·에러 모델·
세션 인증·권한 resolver·DB 스키마)는 `s01`에서 정의된 단일 소스를 **재사용**하며 재정의하지 않는다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 워크스페이스 생성·목록·상세·수정·삭제 동작(`s01` 카탈로그 행 10~14).
  - 멤버십 추가·role 변경·제거 동작(`s01` 카탈로그 행 15~17).
  - `is_shareable` 공유 게이트 플래그와 `trash_retention_days` 보관일 설정.
  - 워크스페이스 단위 권한 판정의 **실동작**: `workspace_member` 데이터 소유와 `s01` resolver 활성화(INV-1·2·3).
  - admin 소유권 변경 동작(`s01` 카탈로그 행 9, `POST /admin/workspaces/{id}/owner`, REQ-2.7).
- **Out of scope (다른 spec이 소유)**:
  - 문서·계층·이동·상태/bundle 엔진(s07), 잠금·버전(s09), 휴지통 동작(s10), 첨부(s12), 공유 링크 발급/무효화(s14).
    이 spec은 `is_shareable` **게이트 플래그만** 소유하며 공유 링크 자체는 소유하지 않는다.
  - 사용자 계정 생명주기(s02·s03). 이 spec은 멤버 후보로서 사용자를 **조회·참조**만 한다.
  - `s01` 계약 요소(권한 resolver 로직·세션 인증·에러 모델·스키마 베이스·DB 스키마)의 **정의**.
  - 프론트엔드 화면.
- **Adjacent expectations (이 spec이 상·하위에 기대·제공하는 것)**:
  - `s01` resolver·세션 인증·에러 모델·Base Schemas·DB 스키마를 재구현 없이 재사용한다.
  - 하위 문서 도메인(s07 이하)은 이 spec이 채운 `workspace_member` 데이터를 근거로 `s01` resolver가
    실제 role 판정을 수행할 것을 기대한다. 이 spec은 그 데이터 경계를 확정한다.
  - s03-admin-account는 워크스페이스 소유권 변경 엔드포인트(행 9)를 명시적으로 이 spec에 이양한다.

## Requirements

### Requirement 1: 워크스페이스 생성 및 조회

**Objective:** As a 인증된 사용자, I want 워크스페이스를 생성하고 내가 접근 가능한 워크스페이스를
조회하기를, so that 협업 문서의 최상위 권한 컨테이너를 확보하고 소속 워크스페이스를 파악할 수 있다.

#### Acceptance Criteria

1. When 인증된 사용자가 워크스페이스 생성을 요청하면, the system shall 워크스페이스를 생성하고 요청자를 owner role 멤버로 함께 등록한다.
2. When 워크스페이스가 생성되면, the system shall `is_shareable`를 false로, `trash_retention_days`를 시스템 기본값(단일 Settings의 기본 보관일)으로 초기화한다.
3. When 인증된 사용자가 워크스페이스 목록을 요청하면, the system shall 요청자가 멤버인 워크스페이스만 반환한다.
4. If 요청자가 admin이면, the system shall 멤버 여부와 무관하게 전체 워크스페이스를 목록으로 반환한다.
5. When viewer 이상 role을 가진 멤버가 특정 워크스페이스 상세를 요청하면, the system shall 해당 워크스페이스 정보를 반환한다.
6. If 요청한 워크스페이스가 존재하지 않으면, the system shall 404 공통 에러 응답을 반환한다.

### Requirement 2: 워크스페이스 수정·설정·삭제

**Objective:** As a 워크스페이스 owner 또는 admin, I want 워크스페이스 속성과 공유·보관 정책을 변경하고
필요 시 삭제하기를, so that 워크스페이스의 이름·공유 가능 여부·휴지통 보관 기간을 통제할 수 있다.

#### Acceptance Criteria

1. When owner가 워크스페이스 이름 수정을 요청하면, the system shall 해당 워크스페이스의 name을 갱신한다.
2. When owner 또는 admin이 `is_shareable`를 설정하면, the system shall 공유 가능 게이트 플래그를 갱신한다.
3. When owner 또는 admin이 `trash_retention_days`를 설정하면, the system shall 해당 워크스페이스의 휴지통 보관일을 갱신한다.
4. If `trash_retention_days`가 양의 정수가 아니면, the system shall 422 검증 오류를 담은 공통 에러 응답을 반환한다.
5. When owner가 문서가 없는(빈) 워크스페이스의 삭제를 요청하면, the system shall 해당 워크스페이스와 그에 속한 모든 멤버십을 제거한다.
6. While 워크스페이스에 대한 수정·설정·삭제 요청이 처리되는 동안, the system shall 요청 사용자가 owner(admin 포함) 권한을 만족하는 경우에만 작업을 수행한다.
7. If 삭제 대상 워크스페이스에 문서가 하나라도 남아 있으면(비어 있지 않으면), the system shall 409 충돌 공통 에러 응답으로 삭제를 거부한다. 이는 `s01`의 `workspace` 참조 FK `ON DELETE RESTRICT` 및 INV-4(문서·첨부 물리 삭제 금지)와 정합하며, 삭제는 오직 빈 워크스페이스에 대해서만 허용된다.

### Requirement 3: 멤버십 관리 (추가·role 변경·제거)

**Objective:** As a 워크스페이스 owner, I want 전체 사용자 목록에서 멤버를 지정 role로 추가하고 role을
변경하거나 제거하기를, so that 워크스페이스 협업 구성원과 각자의 권한을 관리할 수 있다.

#### Acceptance Criteria

1. When owner가 전체 사용자 목록에서 사용자를 선택해 지정한 role(owner/editor/viewer)로 워크스페이스에 추가하면, the system shall 해당 사용자를 그 role의 멤버로 등록한다.
2. If 추가 대상 사용자가 이미 해당 워크스페이스의 멤버이면, the system shall 409 충돌 공통 에러 응답으로 거부한다.
3. If 추가 대상 사용자가 존재하지 않으면, the system shall 404 공통 에러 응답을 반환한다.
4. If 요청한 role 값이 owner/editor/viewer가 아니면, the system shall 422 검증 오류를 반환한다.
5. When owner가 특정 멤버의 role을 변경하면, the system shall 해당 멤버십의 role을 갱신한다.
6. When owner가 특정 멤버를 제거하면, the system shall 해당 멤버십을 제거한다.
7. The system shall 한 워크스페이스에 복수의 owner 멤버가 존재하도록 허용한다.
8. While 멤버십이 유지되는 동안, the system shall (workspace_id, user_id) 조합의 유일성을 보장한다.
9. When 멤버 제거 또는 role 변경으로 워크스페이스에 owner가 하나도 남지 않게 되어도, the system shall 해당 작업을 허용하고 editor·viewer의 접근·권한 판정에는 영향을 주지 않는다.

### Requirement 4: 워크스페이스 단위 권한 판정 (INV-1·2·3, resolver 실동작)

**Objective:** As a 하위 문서 도메인 구현자, I want 워크스페이스 단위 권한 판정이 실제 멤버십 role을
근거로 동작하기를, so that 문서·잠금·휴지통·공유 등 모든 하위 라우터가 일관된 단일 권한 경계를 재사용한다.

#### Acceptance Criteria

1. The system shall 워크스페이스 관련 모든 접근 권한을 워크스페이스 단위 role로만 판정하고 문서별·리소스별 개별 권한 개념을 두지 않는다.
2. When 사용자의 워크스페이스 role이 조회되면, the system shall `workspace_member`의 실제 role을 기준으로 owner ≥ editor ≥ viewer 위계에 따라 최소 요구 role 충족 여부를 판정한다.
3. If viewer role만 가진 사용자가 변경 작업(워크스페이스 수정·삭제·설정·멤버 관리)을 요청하면, the system shall 해당 작업을 403으로 거부한다.
4. If 사용자가 요구되는 최소 role을 만족하지 못하거나 워크스페이스 멤버가 아니면, the system shall 접근을 403으로 거부한다.
5. If 요청 사용자가 admin이면, the system shall 멤버 여부·role과 무관하게 워크스페이스 접근 판정을 통과시킨다.
6. The system shall owner가 editor의 모든 권한을 포함하도록 role 위계를 적용한다.
7. While `workspace_member` 데이터가 존재하는 동안, the system shall 공용 권한 resolver가 해당 멤버십 role을 실제 판정 근거로 사용하도록 데이터를 제공한다.

### Requirement 5: admin 소유권 변경

**Objective:** As a admin, I want 임의 워크스페이스의 소유권을 지정한 사용자에게 부여하기를, so that
유일 owner가 비활동·삭제되어 소유자가 없어진 워크스페이스라도 새 owner를 지정해 관리 연속성을 확보한다.

#### Acceptance Criteria

1. When admin이 특정 워크스페이스의 소유권 변경을 요청하면, the system shall 지정한 사용자를 해당 워크스페이스의 owner로 설정한다.
2. If 소유권 변경 대상 사용자가 아직 해당 워크스페이스의 멤버가 아니면, the system shall 그 사용자를 owner role 멤버로 새로 등록한다.
3. If 소유권 변경 대상 사용자가 이미 멤버이면, the system shall 해당 멤버십의 role을 owner로 갱신한다.
4. If 소유권 변경 요청자가 admin이 아니면, the system shall 요청을 403으로 거부한다.
5. If 대상 워크스페이스 또는 대상 사용자가 존재하지 않으면, the system shall 404 공통 에러 응답을 반환한다.
6. Where 워크스페이스에 owner가 하나도 없는 상태이더라도, the system shall admin 소유권 변경으로 새 owner를 지정할 수 있게 한다.

### Requirement 6: 계약 정합·재사용 및 라우터 조립

**Objective:** As a 하위 feature 구현자·통합 체크포인트, I want 이 spec이 `s01` 단일 계약을 재사용하고
계약을 벗어나지 않기를, so that 계약 드리프트 없이 워크스페이스 경계가 계층 위에 정합적으로 얹힌다.

#### Acceptance Criteria

1. The system shall 워크스페이스·멤버십 요청/응답 스키마를 `s01`의 `{Resource}Create/Read/Update` 규약과 Base Schemas를 상속하여 정의하고 계약 엔티티를 재정의하지 않는다.
2. The system shall 모든 오류를 `s01` 공통 에러 응답 형태(code·message·field_errors)로 반환한다.
3. The system shall `s01` 세션 인증 의존성과 워크스페이스 권한 resolver를 재사용하여 인증·권한을 처리한다.
4. The system shall 워크스페이스 라우터와 admin 소유권 변경 라우터를 `s01` 라우터 조립 지점에 등록하여 앱 부팅 시 노출되도록 한다.
5. The system shall `workspace`·`workspace_member` 접근을 `s01` 초기 마이그레이션 스키마 위에서 수행하고 새 스키마 마이그레이션을 추가하지 않는다.
6. Where 설정 기본값(기본 `trash_retention_days` 등)이 필요하면, the system shall `s01` 단일 Settings를 통해서만 접근한다.
