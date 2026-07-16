# Requirements Document

## Introduction

`s01-contract-foundation`은 Notion-lite 전체 프로젝트(feature spec s02~s14, 통합 체크포인트 s04~s15)가
공유하는 **단일 계약 소스**와 그 계약을 실제로 검증 가능하게 만드는 **공용 런타임 인프라**를 소유한다.

이 spec은 두 가지를 함께 확정한다.

1. **공유 계약(단일 소스)**: 전체 DB 스키마, API 엔드포인트 카탈로그, `{Resource}Create/Read/Update`
   Pydantic 스키마 규약, 공통 에러 응답 모델, 도메인 불변식(INV-1~12) 카탈로그.
2. **공용 런타임 인프라**: MySQL 8 마이그레이션, pydantic-settings 단일 `Settings` 로더(config.yml + .env),
   공통 에러 핸들러, 세션 인증 의존성, 워크스페이스 단위 권한 resolver(owner/editor/viewer + admin bypass),
   FastAPI 앱 부트스트랩·라우터 조립 지점·health 엔드포인트.

이 계약은 모든 통합 체크포인트의 **검증 기준**이며, 하위 spec의 개별 design이 아니라 이 단일 소스에
대조하여 계약 드리프트를 방지한다. 계약이 바뀌면 모든 체크포인트가 재실행 대상이 된다(roadmap 재검증 트리거).

산출물 언어는 한국어이며, 원 명세 `docs/projects.md`(§2 데이터 모델, §3 EARS 요구사항, §4 상태 전이,
§5 불변식)를 계약의 상위 근거로 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 전체 DB 스키마 마이그레이션(user, workspace, workspace_member, document, document_version,
    attachment, share_link 7개 테이블)과 물리 삭제 없음(soft-delete) 전제의 제약·인덱스.
  - API 엔드포인트 카탈로그(경로·메서드·요구 권한·요청/응답 스키마 이름의 목록)와
    `{Resource}Create/Read/Update` Pydantic 스키마 명명·형태 규약.
  - 공통 에러 응답 모델(에러 코드·메시지·필드 오류 구조)과 이를 산출하는 공통 에러 핸들러.
  - pydantic-settings 단일 `Settings` 로더(비밀 아닌 값 config.yml, secret .env).
  - 세션 인증 의존성(현재 사용자·admin 여부 확정, 미인증 거부)의 시그니처와 동작.
  - 워크스페이스 단위 권한 resolver 인터페이스(owner/editor/viewer 순서 판정 + admin bypass, INV-3).
  - 도메인 불변식 INV-1~12를 계약 문서로 카탈로그화.
  - FastAPI 앱 부트스트랩, 라우터 조립 지점(빈 조립 지점 포함), health 엔드포인트.
- **Out of scope (다른 spec이 소유)**:
  - 각 feature의 실제 비즈니스 로직 — 로그인 자격증명 검증·세션 발급(s02), admin 계정 생명주기(s03),
    워크스페이스 CRUD·멤버십(s05), 문서 CRUD·계층·bundle 전이 엔진(s07), 잠금·버전(s09), 휴지통(s10),
    첨부(s12), 공유 링크(s14). 이 spec은 해당 엔드포인트의 **시그니처(계약)만** 두고 동작은 두지 않는다.
  - 프론트엔드 화면(계약 소비는 각 feature에서).
- **Adjacent expectations (하위 spec이 이 계약에 기대하는 것)**:
  - 모든 하위 spec은 여기서 정의한 스키마·에러 모델·세션 의존성·권한 resolver·스키마 규약을 재구현하지 않고
    **재사용**한다. 계약 시그니처를 벗어나는 구현은 계약 위반으로 간주된다.
  - 통합 체크포인트는 이 계약을 유일한 대조 기준으로 사용한다.

## Requirements

### Requirement 1: 데이터 스키마 마이그레이션 (전체 DB 스키마 단일 소스)

**Objective:** As a 하위 feature 구현자·운영자, I want `docs/projects.md` §2의 전체 데이터 모델이
버전 관리되는 마이그레이션으로 재현 가능하게 적용되기를, so that 모든 feature가 동일한 스키마 계약 위에서
구현되고 스키마 드리프트가 발생하지 않는다.

#### Acceptance Criteria

1. When 운영자가 스키마 마이그레이션을 적용하면, the system shall user, workspace, workspace_member,
   document, document_version, attachment, share_link 7개 테이블을 `docs/projects.md` §2에 정의된 컬럼과 함께 생성한다.
2. The system shall user 테이블에 login_id 유일 제약, is_active·is_deleted 불리언 플래그, created_at·updated_at을 포함시킨다.
3. The system shall workspace 테이블에 is_shareable 플래그와 trash_retention_days(기본값 30)를 포함시킨다.
4. The system shall workspace_member 테이블에 (workspace_id, user_id) 유일 제약과 role ENUM(owner, editor, viewer)을 포함시킨다.
5. The system shall document 테이블에 parent_id(NULL 허용, 자기참조), status ENUM(active, trashed, deleted),
   sort_order, current_version_id, lock_user_id, lock_acquired_at, trashed_at, created_by를 포함시킨다.
6. The system shall attachment 테이블에 workspace_id, document_id, file_path, kind ENUM(image, file), is_archived 플래그를 포함시킨다.
7. The system shall share_link 테이블에 token 유일 제약과 is_enabled 플래그를 포함시킨다.
8. Where 물리 삭제 없음(INV-4) 원칙이 적용되는 곳에서, the system shall user·document·attachment의 삭제·보관을
   레코드 제거가 아닌 플래그/상태 컬럼(is_deleted, status, is_archived)으로 표현할 수 있도록 스키마를 구성한다.
9. If 참조 무결성이 필요한 외래키가 존재하면, the system shall 물리 삭제가 없다는 전제 하에 dangling FK가 발생하지 않도록 외래키 제약을 정의한다.
10. When 운영자가 마이그레이션을 역방향(downgrade)으로 실행하면, the system shall 생성한 스키마 객체를 되돌려 마이그레이션이 재현 가능함을 보장한다.
11. While 마이그레이션이 적용된 상태에서, the system shall 조회 시 소프트 삭제 필터링(is_deleted/status 기준)을 지원하는 인덱스를 제공한다.

### Requirement 2: 공용 설정 로더 (단일 Settings)

**Objective:** As a 하위 feature 구현자, I want 모든 backend 모듈이 단일 `Settings` 객체로만 설정에
접근하기를, so that 모듈별 설정 파일·`os.environ` 직접 접근으로 인한 설정 분산과 드리프트가 방지된다.

#### Acceptance Criteria

1. When 애플리케이션이 부팅되면, the system shall 비밀이 아닌 설정을 단일 `config.yml`에서, secret 값을 `.env`에서 읽어 하나의 `Settings` 객체로 결합한다.
2. The system shall DB 접속 정보(host, port, database, user), 기본 trash_retention_days, 파일 저장 루트 경로, 세션 관련 설정을 `Settings` 스키마 항목으로 노출한다.
3. If secret 값(DB password 등)이 `.env`에 정의되면, the system shall 해당 값을 `Settings`를 통해서만 접근 가능하게 하고 config.yml에는 secret을 두지 않는다.
4. If 필수 설정 항목이 누락되면, the system shall 부팅 시점에 명확한 검증 오류로 실패한다(부분 부팅 금지).
5. The system shall 애플리케이션 코드가 `Settings` 접근자를 통해서만 설정을 읽도록 단일 접근 지점을 제공한다.
6. Where 새 설정 항목이 필요한 경우, the system shall 별도 설정 파일 신설 없이 config.yml(또는 secret이면 .env) 추가와 `Settings` 스키마 확장만으로 수용 가능한 구조를 제공한다.

### Requirement 3: 공통 에러 응답 모델 및 핸들러

**Objective:** As a 하위 feature 구현자·API 소비자, I want 모든 엔드포인트가 동일한 형태의 에러 응답을
반환하기를, so that 클라이언트와 통합 테스트가 단일 에러 계약으로 오류를 처리할 수 있다.

#### Acceptance Criteria

1. The system shall 안정적인 에러 코드, 사람이 읽을 메시지, 선택적 필드 단위 오류 목록을 담는 단일 에러 응답 스키마를 정의한다.
2. When 요청 본문·파라미터 검증이 실패하면, the system shall 422 상태와 필드 단위 오류를 포함한 공통 에러 응답을 반환한다.
3. When 인증이 필요한데 세션이 없으면, the system shall 401 상태와 공통 에러 응답을 반환한다.
4. When 권한이 부족하면, the system shall 403 상태와 공통 에러 응답을 반환한다.
5. When 대상 리소스가 없으면, the system shall 404 상태와 공통 에러 응답을 반환한다.
6. When 도메인 규칙(불변식) 위반이 발생하면, the system shall 409 또는 422 상태와 위반 조건을 설명하는 공통 에러 응답을 반환한다.
7. If 처리되지 않은 서버 오류가 발생하면, the system shall 내부 세부정보를 노출하지 않고 500 상태의 공통 에러 응답을 반환한다.
8. The system shall 에러 코드 카탈로그(인증·권한·검증·미존재·충돌·서버 오류 범주)를 계약 문서로 제공한다.

### Requirement 4: 세션 인증 의존성

**Objective:** As a 하위 feature 구현자, I want 보호된 엔드포인트가 재사용 가능한 단일 세션 인증
의존성으로 현재 사용자와 admin 여부를 확정하기를, so that 각 라우터가 인증 로직을 중복 구현하지 않는다.

#### Acceptance Criteria

1. When 유효한 세션을 가진 요청이 보호된 엔드포인트에 도달하면, the system shall 현재 사용자 식별자와 admin 여부를 담은 인증 컨텍스트를 제공한다.
2. If 세션이 없거나 유효하지 않으면, the system shall 요청을 거부하고 401 공통 에러 응답을 반환한다.
3. If 세션이 `is_active = false` 또는 `is_deleted = true`인 사용자를 가리키면, the system shall 인증을 거부한다.
4. The system shall admin 여부를 인증 컨텍스트에 노출하여 권한 resolver가 admin bypass를 판정할 수 있게 한다.
5. The system shall 세션 발급·검증에 필요한 저장 방식(세션 식별자 전달 수단)을 계약으로 정의하되, 로그인 자격증명 검증·세션 생성 로직 자체는 이 spec의 범위 밖(s02)임을 명시한다.

### Requirement 5: 워크스페이스 단위 권한 resolver (INV-1·2·3)

**Objective:** As a 하위 feature 구현자, I want 워크스페이스 단위 권한(owner/editor/viewer)과 admin bypass를
판정하는 단일 resolver를, so that 문서·휴지통·공유 등 모든 라우터가 권한 검사를 중복 없이 재사용한다.

#### Acceptance Criteria

1. The system shall 권한을 워크스페이스 단위로만 판정하며 문서별 개별 권한 개념을 제공하지 않는다(INV-1).
2. When 사용자가 특정 워크스페이스에 대해 최소 요구 role을 만족하는지 조회되면, the system shall workspace_member의 role을 기준으로 owner ≥ editor ≥ viewer 순서로 충족 여부를 판정한다.
3. If 사용자가 요청한 최소 role을 만족하지 못하면, the system shall 접근을 거부(403)한다.
4. While viewer 권한만 가진 사용자가 변경(CRUD·휴지통) 작업을 요청하면, the system shall 해당 작업을 거부한다(INV-2, 읽기 전용).
5. If 요청 사용자가 admin이면, the system shall 워크스페이스 멤버 여부·role과 무관하게 모든 판정을 통과시킨다(INV-3, admin bypass).
6. The system shall owner가 복수일 수 있음을 허용하고 owner가 editor의 모든 권한을 포함하도록 role 위계를 정의한다.
7. The system shall resolver를 재사용 가능한 의존성 인터페이스(요구 role을 파라미터로 받는 형태)로 제공하되, 각 feature의 구체적 권한 매핑 적용은 해당 feature spec에서 수행함을 명시한다.

### Requirement 6: API 엔드포인트 카탈로그 및 Pydantic 스키마 규약

**Objective:** As a 하위 feature 구현자, I want 전체 API 엔드포인트 목록과 요청/응답 스키마 명명 규약이
단일 소스로 확정되기를, so that 모든 feature가 동일한 경로·권한·스키마 규약으로 엔드포인트를 구현한다.

#### Acceptance Criteria

1. The system shall `docs/projects.md` §3(REQ-1~8)의 사용자 관찰 가능 동작을 실현하는 API 엔드포인트 카탈로그(경로, HTTP 메서드, 요구 최소 권한, 요청/응답 스키마 이름)를 계약 문서로 제공한다.
2. The system shall 각 도메인 리소스의 요청/응답 스키마를 `{Resource}Create` / `{Resource}Read` / `{Resource}Update` 명명 규약으로 정의하도록 규정한다.
3. The system shall 카탈로그가 인증·계정(REQ-1), admin(REQ-2), 워크스페이스(REQ-3), 문서(REQ-4), 잠금·버전(REQ-5), 휴지통(REQ-6), 공유(REQ-7), 첨부(REQ-8) 각 도메인의 엔드포인트를 빠짐없이 열거하도록 한다.
4. The system shall 각 카탈로그 항목에 어느 하위 spec(s02~s14)이 그 엔드포인트의 동작을 소유하는지 표기하여 계약과 구현 소유권을 매핑한다.
5. Where 목록·상세·생성·수정·상태전이 응답이 공통 필드(식별자, 타임스탬프, 상태)를 갖는 경우, the system shall Read 스키마 공통 필드 규약을 정의하여 스키마 중복을 방지한다.
6. The system shall 이 카탈로그를 하위 spec·통합 체크포인트가 참조하는 유일한 API 계약 기준으로 명시한다.

### Requirement 7: 도메인 불변식 카탈로그 (INV-1~12)

**Objective:** As a 통합 체크포인트·구현자, I want 계층 경계를 넘는 12개 불변식이 단일 문서로 카탈로그화되고
계약 요소(스키마·API·resolver)와 연결되기를, so that 각 체크포인트가 동일 기준으로 불변식 회귀를 검증한다.

#### Acceptance Criteria

1. The system shall `docs/projects.md` §5의 INV-1~12를 계약 문서에 원문 의미 그대로 열거한다.
2. The system shall 각 불변식에 대해 어느 계약 요소(스키마 제약, 권한 resolver, 상태/bundle 계약, 공유 재발급 계약 등)와 어느 하위 spec이 그 불변식을 강제·검증하는지 매핑을 제공한다.
3. The system shall 권한 관련 불변식(INV-1·2·3)을 권한 resolver·세션 의존성 계약과 연결한다.
4. The system shall 물리 삭제 없음(INV-4)을 스키마 soft-delete 제약과 연결한다.
5. The system shall bundle·휴지통 관련 불변식(INV-10·11·12)을 문서 상태 컬럼(status, trashed_at) 및 document-core 소유 계약과 연결한다.
6. The system shall 공유 무효화·재발급 불변식(INV-8)을 share_link 계약과 연결한다.
7. The system shall 불변식 카탈로그를 통합 체크포인트의 회귀 검증 기준으로 명시한다.

### Requirement 8: 애플리케이션 부트스트랩 및 상태 점검

**Objective:** As a 운영자·하위 feature 구현자, I want FastAPI 앱이 공용 인프라를 조립하여 부팅되고
상태를 점검할 수 있기를, so that 계약 spec 자체가 마이그레이션 적용·앱 부팅·설정 로드로 검증 가능하다.

#### Acceptance Criteria

1. When 운영자가 `backend/`에서 `uv run`으로 앱을 기동하면, the system shall `Settings` 로드·공통 에러 핸들러 등록·라우터 조립 지점을 포함한 FastAPI 애플리케이션을 부팅한다.
2. When health 엔드포인트가 호출되면, the system shall 애플리케이션 가용 상태를 나타내는 응답을 반환한다.
3. When health 엔드포인트가 DB 연결 점검을 포함해 호출되면, the system shall 마이그레이션된 데이터베이스에 연결 가능한지 여부를 응답에 반영한다.
4. The system shall 하위 spec이 자신의 라우터를 추가할 수 있는 조립 지점(빈 상태 포함)을 제공하되, 이 spec에서는 feature 라우터의 동작을 구현하지 않는다.
5. The system shall 공통 에러 핸들러가 앱 전역에 등록되어 처리되지 않은 예외가 공통 에러 응답으로 변환되도록 한다.
6. While 앱이 실행 중인 상태에서, the system shall 모든 요청이 단일 `Settings`·공통 에러 계약·(보호 엔드포인트의 경우) 세션 의존성을 거치도록 부트스트랩을 구성한다.
