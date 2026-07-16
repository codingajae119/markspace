# Requirements Document

## Introduction

`s07-document-core`는 Notion-lite의 **핵심 도메인**인 계층적 markdown 문서와, 문서 3단계 상태
(active → trashed → deleted) 전이를 지배하는 **묶음(bundle) 비흡수 엔진**을 구현한다. 문서 엔티티·계층
(parent/child)·CRUD·이동/재정렬(순환 방지·동일 워크스페이스 제약)·현재 버전 렌더/preview를 소유하며,
무엇보다 삭제·복구·완전삭제를 **묶음 단위로 원자적**으로 처리하는 상태 전이 엔진을 단일 구현으로
캡슐화한다(INV-5·6·10·11·12).

이 spec은 `docs/projects.md` §4의 가장 까다로운 불변식(비흡수 모델, 독립 보관 타이머 기준, 복구 위치
규칙)을 코드 한 곳에 담는다. 이 엔진은 **하위 spec의 기반**이다. s10-trash는 휴지통 목록·복구·완전삭제
API와 보관 타이머를 이 엔진의 primitive(복구·완전삭제·묶음 식별) 위에 얹고, s14-sharing은 문서 상태·active
하위 집합 질의를 재사용한다. 따라서 이 spec의 성공 기준은 (1) 상태 전이 엔진이 단일 구현으로 캡슐화되어
하위 spec이 **재구현하지 않고 재사용**할 수 있는 경계를 제공하는 것과, (2) 불변식 INV-5·6·10·11·12가
property/edge-case 수준에서 성립함을 검증 가능하게 만드는 것이다.

모든 계약 엔티티(문서 DB 스키마·API 카탈로그·에러 모델·Base Schemas·세션/권한 resolver)는 `s01`이 정의한
단일 소스를 **재사용**하며 재정의하지 않는다. 권한 게이팅은 `s05`가 실동작시킨 워크스페이스 권한 resolver
(`require_ws_role`)를 재사용한다(문서별 개별 권한 없음, INV-1). 산출물 언어는 한국어이며, 상위 근거로
`docs/projects.md`(§2.4 document·§2.5 document_version 데이터 모델, §3 REQ-4·REQ-6, §4.1~4.3 상태 전이,
§5 INV-1·2·3·4·5·6·9·10·11·12)를 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 문서 생성·하위 문서 생성·조회·목록·제목 수정(`s01` 카탈로그 행 18~21)과 삭제(행 23), 이동/재정렬(행 22).
  - 계층 구조(parent/child)와 같은 워크스페이스 내 이동/재정렬(parent 재지정·형제 순서), 순환 방지(자기/후손
    이동 거부, INV-5), 워크스페이스 경계 유지(INV-6).
  - 현재 버전 markdown 렌더링과 편집 화면 preview가 공용하는 **단일 markdown 렌더 규약**(4.4·4.5).
  - **status + bundle 전이 엔진**(단일 구현, 하위 spec 재사용 대상):
    - active → trashed 삭제 캐스케이드: 삭제 시점의 active 하위만 하나의 묶음으로 포착, 공통 trashed_at 기록,
      이미 trashed된 하위는 제외(비흡수).
    - trashed → active 복구 primitive: 복구 시점 부모 상태 기준 복귀 위치 결정, sort_order 원위치 복원,
      자동 재중첩 없음.
    - trashed → deleted 완전삭제 primitive: 묶음 단위 원자적 전이.
    - 묶음 식별·열거 primitive: 무엇이 하나의 묶음인지 판정.
  - 문서 상태와 편집 잠금의 독립성 정의(잠긴 문서도 삭제/상태 전이 가능, §4.3). lock 필드의 존재 인지(정의는
    `s01` 스키마) — 잠금 **동작**은 소유하지 않는다.
- **Out of scope (다른 spec이 소유)**:
  - 휴지통 목록/복구/완전삭제 **API·UX**와 묶음 보관 타이머 자동 영구삭제(s10). 이 spec은 엔진 **primitive만**
    소유하며 s10이 그 위에 API·타이머를 얹는다.
  - 편집 잠금 흐름(시작/저장/취소/강제해제)과 버전 스냅샷 생성·본문 저장(s09). 문서 생성은 초기 버전을
    만들지 않으며, 본문 저장은 s09가 담당한다.
  - 공유 링크 발급/무효화(s14), 첨부 파일 저장·완전삭제 시 보관 이동(s12, 8.6). 완전삭제 primitive는 상태
    전이만 수행하고 첨부 아카이브는 s12가 관찰·수행한다.
  - `s01` 계약 요소(문서 DB 스키마·API 카탈로그·에러 모델·Base Schemas·권한 resolver 로직·세션 인증)의
    **정의**와 `s05` 워크스페이스·멤버십 동작. 프론트엔드 화면.
- **Adjacent expectations (이 spec이 상·하위에 기대·제공하는 것)**:
  - `s01` 문서·문서버전 스키마, 에러 모델, Base Schemas, 권한 resolver를 재구현 없이 재사용하고, `s05`가
    채운 `workspace_member` 데이터로 실동작하는 `require_ws_role`을 재사용한다(문서 id → workspace_id 매핑
    어댑터만 신설).
  - s10-trash는 이 spec의 복구·완전삭제·묶음 식별 primitive를 재사용하며 상태 전이 규칙을 재구현하지 않는다.
  - s14-sharing은 이 spec의 문서 상태 질의와 active 하위 집합 질의를 재사용한다.
  - s09-lock-version은 이 spec이 인정한 lock 필드 위에서 잠금·버전 동작을 구현하며, 문서 상태 전이와 잠금은
    서로 독립임을 전제한다.

## Requirements

### Requirement 1: 문서 생성 및 계층 구조

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 문서와 특정 문서의 하위 문서를 생성하기를,
so that 계층적 markdown 문서 트리를 워크스페이스 안에 구성할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 워크스페이스에 문서 생성을 요청하면, the system shall active 상태의 루트 문서를 생성하고 요청자를 최초 작성자로 기록한다.
2. When editor 이상 사용자가 특정 문서를 부모로 지정해 하위 문서 생성을 요청하면, the system shall 지정한 문서를 부모로 하는 active 문서를 생성한다.
3. If 하위 문서 생성 시 지정한 부모 문서가 존재하지 않거나 active 상태가 아니면, the system shall 요청을 거부하고 공통 에러 응답을 반환한다.
4. If 하위 문서 생성 시 지정한 부모 문서가 요청한 워크스페이스에 속하지 않으면, the system shall 워크스페이스 경계 위반으로 요청을 거부한다.
5. When 문서가 생성되면, the system shall 같은 부모를 가진 형제 문서들 사이에서 마지막 순서로 배치되도록 정렬 순서를 부여한다.
6. If viewer role만 가진 사용자가 문서 또는 하위 문서 생성을 요청하면, the system shall 해당 작업을 403으로 거부한다.
7. If 요청 사용자가 대상 워크스페이스의 editor 이상 role이 아니고 admin도 아니면, the system shall 생성 요청을 거부한다.

### Requirement 2: 문서 조회·목록·렌더 및 preview

**Objective:** As a 워크스페이스 viewer 이상 사용자, I want 문서를 열어 현재 버전의 markdown을
확인하고 워크스페이스의 문서 목록을 조회하기를, so that 협업 문서를 읽고 계층 구조를 파악할 수 있다.

#### Acceptance Criteria

1. When viewer 이상 사용자가 특정 문서를 조회하면, the system shall 해당 문서의 메타데이터와 현재 버전의 markdown 본문을 반환한다.
2. When 사용자가 문서를 열람하면, the system shall 현재 버전의 markdown을 안전하게(위험 요소 제거) 렌더링한 결과를 함께 제공한다.
3. If 조회 대상 문서에 현재 버전이 아직 없으면(본문 저장 전), the system shall 빈 본문에 대한 렌더 결과를 정상 반환한다.
4. When viewer 이상 사용자가 워크스페이스의 문서 목록을 요청하면, the system shall 해당 워크스페이스의 active 문서를 계층 파악이 가능한 형태로 반환한다.
5. The system shall 열람 렌더링과 편집 화면 preview가 동일한 markdown 렌더 규약(문법·안전 처리)을 공용하도록 단일 렌더 규약을 제공한다.
6. If 요청 사용자가 대상 워크스페이스의 viewer 이상 role이 아니고 admin도 아니면, the system shall 조회 요청을 거부한다.
7. If 조회·목록 대상 문서 또는 워크스페이스가 존재하지 않으면, the system shall 404 공통 에러 응답을 반환한다.

### Requirement 3: 문서 수정 (제목·메타데이터)

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 문서의 제목을 수정하기를, so that 문서
식별 정보를 최신 상태로 유지할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 문서 제목 수정을 요청하면, the system shall 해당 문서의 제목을 갱신한다.
2. If viewer role만 가진 사용자가 문서 수정을 요청하면, the system shall 해당 작업을 403으로 거부한다.
3. If 수정 대상 문서가 존재하지 않으면, the system shall 404 공통 에러 응답을 반환한다.
4. While 문서 수정 요청이 처리되는 동안, the system shall 본문 내용 저장과 버전 생성은 이 경계에서 수행하지 않고 잠금·버전 spec에 위임한다.

### Requirement 4: 문서 이동·재정렬 (순환 방지·동일 워크스페이스)

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 문서를 같은 워크스페이스 내 다른 부모 밑으로
옮기거나 형제 사이 순서를 바꾸기를, so that 문서 계층을 재구성할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 문서 이동을 요청하면, the system shall 대상 문서의 부모와 형제 간 정렬 순서를 요청한 위치로 갱신한다.
2. If 이동 대상 문서가 자기 자신이거나 자신의 하위(후손) 문서 밑으로 이동하려 하면, the system shall 순환 방지를 위해 이동을 거부한다.
3. If 이동 목적지(새 부모)가 대상 문서와 다른 워크스페이스에 속하면, the system shall 워크스페이스 경계 위반으로 이동을 거부한다.
4. If 이동 목적지(새 부모)가 존재하지 않거나 active 상태가 아니면, the system shall 이동을 거부한다.
5. When 재정렬 요청이 두 형제 사이 위치를 지정하면, the system shall 기존 형제의 순서를 재배치하지 않고도 그 사이에 삽입 가능한 정렬 순서를 부여한다.
6. If viewer role만 가진 사용자가 이동·재정렬을 요청하면, the system shall 해당 작업을 403으로 거부한다.
7. While 이동이 수행되는 동안, the system shall 이동 결과 문서 계층 그래프에 사이클이 생기지 않도록 보장한다.

### Requirement 5: 삭제·묶음 포착 엔진 (active → trashed)

**Objective:** As a 워크스페이스 editor 이상 사용자, I want active 문서 또는 하위 문서를 삭제하면 그
시점의 서브트리가 하나의 묶음으로 휴지통에 들어가기를, so that 삭제가 묶음 단위로 예측 가능하게 동작한다.

#### Acceptance Criteria

1. The system shall 문서 상태를 active → trashed → deleted 세 단계로 관리한다.
2. When editor 이상 사용자가 active 문서를 삭제하면, the system shall 해당 문서와 그 시점의 active 하위 문서만 하나의 묶음으로 trashed 전환하고 묶음 공통 trashed_at을 기록한다.
3. While 삭제 캐스케이드가 서브트리를 포착하는 동안, the system shall 이미 trashed 상태인 하위 문서를 캐스케이드에서 제외하고 그 하위의 기존 묶음·기존 trashed_at을 그대로 유지한다.
4. When editor 이상 사용자가 active 상태에서 하위 문서만 개별 삭제하면, the system shall 그 자식과 자식의 active 하위를 휴지통에서 독립 묶음으로 만든다.
5. When 하나의 삭제 조작이 묶음을 전환하면, the system shall 그 전환을 묶음 단위로 원자적으로 적용한다.
6. If viewer role만 가진 사용자가 문서 삭제를 요청하면, the system shall 해당 작업을 403으로 거부한다.
7. If 삭제 대상 문서가 존재하지 않거나 이미 active 상태가 아니면, the system shall 삭제 요청을 거부한다.

### Requirement 6: 비흡수 모델·독립 묶음 불변식 (INV-11·12 기준)

**Objective:** As a 상태 엔진 소비자(하위 spec)·검증자, I want 서로 다른 시점의 삭제로 생긴 묶음이 절대
병합되지 않고 각자의 보관 기준을 갖기를, so that 휴지통·공유 동작이 일관된 불변식 위에서 구축된다.

#### Acceptance Criteria

1. If 자식이 부모보다 먼저 trashed되어 독립 묶음으로 존재하는 상태에서 부모가 삭제되면, the system shall 그 자식을 흡수하지 않고 독립 묶음으로 유지한다.
2. The system shall 서로 다른 시점에 생성된 묶음을 이후에도 병합·흡수하지 않고 각각 독립적으로 전이시킨다.
3. While 묶음들이 휴지통에 공존하는 동안, the system shall 독립 묶음으로 존재하는 자식이 항상 부모보다 먼저 trash에 진입했음(child.trashed_at ≤ parent.trashed_at)을 보장한다.
4. The system shall 각 묶음의 보관 만료 기준 시각을 그 묶음 자신의 trashed_at으로 삼아, 다른 묶음의 삭제·복구가 그 기준에 영향을 주지 않도록 한다.
5. The system shall 하나의 묶음을 그 묶음을 발생시킨 직접 삭제 대상 문서(묶음 루트)로 식별하고, 묶음 구성원을 결정적으로 열거하는 수단을 제공한다.

### Requirement 7: 복구 엔진 primitive (복구 위치·순서)

**Objective:** As a 휴지통 spec(s10) 구현자, I want 묶음을 active로 되돌리는 복구 primitive가 복구 시점의
부모 상태에 따라 복귀 위치를 결정하고 순서를 원위치로 복원하기를, so that 휴지통 복구 API가 상태 규칙을
재구현하지 않고 이 primitive를 호출하기만 하면 된다.

#### Acceptance Criteria

1. When 묶음 복구가 요청되고 묶음 루트의 부모가 active이면, the system shall 그 묶음을 부모 밑으로 복귀시키고 부모 참조를 유지한다.
2. If 묶음 루트의 부모가 non-active(trashed·deleted 또는 부재)이면, the system shall 그 묶음을 root로 복귀시키고 부모 참조를 제거한다.
3. When 묶음 루트가 부모 밑으로 복귀하면, the system shall 보존된 원래 정렬 순서로 재삽입하되, 그 위치가 충돌하면 원래 직전·직후 형제 사이 중간값으로, 원래 이웃이 모두 사라졌으면 가장 가까운 잔존 형제 기준 근사 위치로, 그마저 불가하면 맨 뒤로 삽입한다.
4. When 묶음 루트가 root로 복귀하면, the system shall 원위치 복원 대신 root 맨 뒤에 배치한다.
5. The system shall 자식을 root로 복구한 뒤 그 부모가 복구되더라도 자식을 부모 밑으로 자동 재중첩하지 않는다.
6. The system shall 독립 묶음을 부모 묶음과 무관하게 단독으로 복구할 수 있게 하며, 한 묶음의 복구가 다른 독립 묶음을 함께 되살리지 않도록 한다.
7. When 묶음이 복구되면, the system shall 복구된 구성원 전체를 active로 전환하고 묶음 내부의 상대적 계층 구조를 유지한다.

### Requirement 8: 완전삭제 엔진 primitive (trashed → deleted)

**Objective:** As a 휴지통 spec(s10) 구현자, I want 묶음을 즉시 영구삭제하는 primitive가 묶음 전체를
원자적으로 deleted로 전환하기를, so that 휴지통 완전삭제 API와 보관 타이머가 이 primitive를 호출한다.

#### Acceptance Criteria

1. When 묶음에 대한 완전삭제 primitive가 호출되면, the system shall 해당 묶음의 모든 구성원을 즉시 deleted로 전환한다.
2. While 완전삭제가 수행되는 동안, the system shall 전환을 묶음 단위로 원자적으로 적용하고 다른 독립 묶음에는 영향을 주지 않는다.
3. The system shall deleted를 종착 상태로 취급하여 애플리케이션 복구 경로를 제공하지 않는다.
4. Where 완전삭제가 물리 삭제 없이 수행되는 경우, the system shall 레코드를 제거하지 않고 상태 전환만으로 영구삭제를 표현한다.
5. The system shall 완전삭제 primitive를 상태 전이에 한정하고 첨부 파일 보관 이동·버전 처리는 소유하지 않는다.

### Requirement 9: 상태 엔진 캡슐화·재사용 경계 및 상태·잠금 독립

**Objective:** As a 하위 spec 구현자·검증자, I want status/bundle 전이 규칙이 document-core 서비스에
단일 구현으로 캡슐화되어 재사용 가능한 경계를 제공하기를, so that s10·s14가 규칙을 재구현하지 않고 드리프트
없이 재사용한다.

#### Acceptance Criteria

1. The system shall 삭제·복구·완전삭제·묶음 식별 규칙을 document-core의 단일 상태 엔진 구현에 캡슐화한다.
2. The system shall s10·s14가 상태 전이·묶음 규칙을 재구현하지 않고 이 엔진 primitive를 호출해 소비할 수 있는 인터페이스를 제공한다.
3. The system shall 특정 문서의 active 하위 집합을 질의하는 수단을 제공하여 공유(s14)와 삭제 캐스케이드가 동일한 계층 질의 규칙을 공용하게 한다.
4. While 문서에 편집 잠금이 걸려 있는 동안에도, the system shall 문서 상태 전이(삭제·복구·완전삭제)를 잠금과 독립적으로 수행한다.
5. The system shall lock 관련 필드를 문서 스키마상 존재하는 것으로 인정하되 이 경계에서는 값을 설정하지 않고 그 동작을 잠금·버전 spec에 위임한다.

### Requirement 10: 계약 정합·권한 resolver 재사용 및 라우터 조립

**Objective:** As a 하위 feature 구현자·통합 체크포인트, I want 이 spec이 `s01` 단일 계약과 `s05` 권한
resolver를 재사용하고 계약을 벗어나지 않기를, so that 계약 드리프트 없이 문서 코어가 계층 위에 정합적으로
얹힌다.

#### Acceptance Criteria

1. The system shall 문서 요청/응답 스키마를 `s01`의 `{Resource}Create/Read/Update` 규약과 Base Schemas를 상속하여 정의하고 계약 엔티티를 재정의하지 않는다.
2. The system shall 모든 오류를 `s01` 공통 에러 응답 형태(code·message·field_errors)로 반환한다.
3. The system shall `s01` 세션 인증 의존성과 워크스페이스 권한 resolver를 재사용하여 문서 CRUD·이동·삭제는 editor 이상, 조회는 viewer 이상으로 게이팅하고 admin 접근은 어떤 권한 검사로도 차단하지 않는다.
4. The system shall 문서 id로부터 소속 워크스페이스를 확정해 권한 resolver에 주입하는 매핑 어댑터를 제공하되 resolver의 위계 비교·admin bypass 로직은 재구현하지 않는다.
5. The system shall 문서 라우터를 `s01` 라우터 조립 지점에 등록하여 앱 부팅 시 카탈로그 행 18~23이 노출되도록 한다.
6. The system shall `document`·`document_version` 접근을 `s01` 초기 마이그레이션 스키마 위에서 수행하고 새 스키마 마이그레이션을 추가하지 않는다.
7. Where 설정 기본값이 필요하면, the system shall `s01` 단일 Settings를 통해서만 접근한다.
