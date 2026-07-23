# Requirements Document

## Introduction

`s12-attachment`는 MarkSpace 문서에 붙는 **이미지(붙여넣기)·첨부 파일**을 파일로 저장하고, 워크스페이스별로
격리 보관하며, 문서가 완전삭제되거나 저장으로 더 이상 참조되지 않게 된 파일을 **삭제하지 않고 "삭제된 파일
보관 폴더"로 이동(아카이브)** 하는 첨부 도메인을 구현한다. 편집 중 이미지 붙여넣기는 base64 인라인이 아니라
파일로 저장되어 문서에서 참조되며(REQ-8.1), editor 이상 사용자는 파일을 첨부해 문서에 연결한다(8.2). 파일 저장과
보관 폴더는 모두 워크스페이스 단위로 격리된다(8.3·8.8).

이 spec의 핵심 성격은 **하위 계층(문서·버전·휴지통) 위에 얹혀 그들의 사건에 반응하는 상위 레이어**라는
점이다. 문서 완전삭제(deleted 전이)는 `s10-trash`가, 저장에 따른 새 버전 생성은 `s09-lock-version`이 소유하고
트리거하지만, 그 결과 첨부 파일을 보관 폴더로 이동하는 반응(8.6·8.7)은 이 spec이 소유한다. 하위 계층은 상위
계층(s12)을 알지 못하므로(의존 방향은 항상 아래층을 향한다), s12는 **문서 상태·현재 버전 참조라는 관측 가능한
결과를 기준으로 첨부 생명주기를 조정하는 조정(reconciliation) 방식**으로 두 사건에 반응한다.

모든 계약 엔티티(첨부 API 카탈로그 행 32~33, 에러 모델, Base Schemas, 세션/권한 resolver, `attachment`·
`document`·`document_version` 스키마, 파일 저장 루트 Settings `file_storage_root`)는 `s01`이 정의한 단일 소스를
**재사용**하며 재정의하지 않는다. 권한 게이팅은 `s05`가 실동작시킨 워크스페이스 권한 resolver(`require_ws_role`)를
재사용한다(문서별 개별 권한 없음, INV-1). 물리 삭제는 없으며(INV-4), 보관 이동만 수행한다. 보관은 애플리케이션상
복원 대상이 아니며 admin을 포함해 조회할 수 없다(INV-7). 산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md`
(§2.6 attachment 데이터 모델, §3 REQ-8, §4.4 보관 이동, §5 INV-4·6·7)를 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 편집 중 이미지 붙여넣기 저장(카탈로그 행 32의 image 경로): 파일로 저장하고 문서에서 참조 가능한
    URL을 반환한다(base64 인라인 아님, 8.1).
  - editor 이상 파일 첨부 저장(행 32의 file 경로): 파일을 저장하고 문서에 연결한다(8.2).
  - 첨부 바이너리 조회 서빙(행 33, `GET /attachments/{id}` → 바이너리): 워크스페이스 단위 viewer 이상
    게이팅. 보관된(아카이브된) 첨부는 조회 불가(8.10).
  - 파일 저장의 워크스페이스 격리(8.3): 첨부 파일을 워크스페이스 단위로 분리된 저장 위치에 둔다.
  - 문서 완전삭제(deleted 전이) 반응 보관 이동(8.6): deleted 문서에 연결된 첨부를 물리 삭제 없이 보관
    폴더로 이동하고 `is_archived=true`로 표시한다(INV-4).
  - 저장 참조 소멸 아카이브(8.7): 새 버전 저장으로 현재 버전이 더 이상 참조하지 않게 된 이미지를 보관
    폴더로 이동한다.
  - 보관 폴더의 워크스페이스 격리(8.8)와 비노출·영구성(8.9·8.10·8.11, INV-7): 보관은 복원 대상이 아니며
    admin 포함 조회 불가, 보관 폴더는 단조 증가(monotonic)를 수용한다.
- **Out of scope (다른 spec이 소유)**:
  - 공유 링크 경유 파일 접근·차단(8.4·8.5, `GET /public/{token}/attachments/{aid}`, 카탈로그 행 37) —
    `s14-sharing`가 s12의 저장·격리·아카이브 결과를 소비한다.
  - 문서 상태 전이·완전삭제 로직(active→trashed→deleted, 묶음 규칙) — `s07-document-core` 엔진과
    `s10-trash`가 소유. s12는 deleted 전이의 **결과를 관측**할 뿐 전이를 수행하지 않는다.
  - 편집 잠금·저장 시 버전 생성(current_version 갱신) — `s09-lock-version`가 소유. s12는 "새 버전 저장"의
    **결과(현재 버전 참조 변화)를 관측**할 뿐 저장·버전 생성을 수행하지 않는다.
  - markdown 본문 렌더링(첨부 참조를 이미지로 표시) — `s07-document-core`의 렌더 규약이 소유. s12는
    참조 URL 규약만 제공한다.
  - `s01` 계약 요소(API 카탈로그·에러 모델·Base Schemas·권한 resolver 로직·세션 인증·DB 스키마·Settings
    로더)의 **정의**와 `s05` 워크스페이스·멤버십 **동작**. 프론트엔드 화면.
- **Adjacent expectations (이 spec이 상·하위에 기대·제공하는 것)**:
  - `s01`은 `attachment` 스키마(`workspace_id`·`document_id`·`file_path`·`original_name`·`kind`·`is_archived`)와
    파일 저장 루트 Settings(`file_storage_root`), 카탈로그 행 32~33을 안정 계약으로 제공한다. s12는 이를
    재사용하고 재정의하지 않으며, 새 DB 마이그레이션을 추가하지 않는다.
  - `s09`는 저장 시 새 `document_version` 생성·`document.current_version_id` 갱신을 트리거한다. `s10`은
    완전삭제·자동 영구삭제로 문서를 deleted로 전환한다. s12는 이 두 사건의 결과를 문서 상태·현재 버전
    참조로 **관측**해 첨부 보관 이동(8.6·8.7)을 수행하며, s09·s10은 s12를 알지 못한다(의존 방향 준수).
  - `s05`가 채운 `workspace_member`로 `require_ws_role`이 실동작하며, 첨부 접근은 워크스페이스 단위로만
    판정된다(INV-1). `s13-integration-check-L5`가 보관 이동↔완전삭제·참조 소멸↔버전 저장을 누적 검증한다.
  - `s14-sharing`는 링크 경유 파일 접근(8.4·8.5)에서 s12의 저장·격리·아카이브 결과를 소비한다. 보관된
    첨부는 어떤 경로로도 노출되지 않는다는 규약을 s12가 보장한다.

## Requirements

### Requirement 1: 편집 중 이미지 붙여넣기 파일 저장

**Objective:** As a 문서 편집 사용자, I want 편집 중 붙여넣은 이미지가 파일로 저장되고 문서에서 참조되기를,
so that 문서 본문에 base64로 이미지를 인라인하지 않고도 이미지를 문서에 포함할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 편집 중 이미지를 붙여넣어 첨부를 요청하면, the system shall 그 이미지를 파일로
   저장하고 문서에서 참조할 수 있는 첨부 참조를 반환한다.
2. The system shall 붙여넣은 이미지를 base64 인라인이 아니라 별도 파일로 저장하고 첨부 종류를 image로 기록한다.
3. When 이미지 첨부가 생성되면, the system shall 그 첨부를 요청 대상 문서와 그 문서의 소속 워크스페이스에
   연결하여 기록한다.
4. The system shall 이미지 첨부 응답에 이후 문서 본문에서 이미지를 참조하는 데 사용할 안정적인 참조 URL을
   포함한다.
5. If 이미지 첨부 대상 문서가 존재하지 않으면, the system shall 404 공통 에러 응답을 반환한다.

### Requirement 2: editor 이상 파일 첨부 저장

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 파일을 문서에 첨부하기를, so that 이미지가 아닌
문서·자료 파일도 문서에 연결해 보관·공유할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 문서에 파일을 첨부하면, the system shall 그 파일을 저장하고 대상 문서에 연결한 뒤
   첨부 참조를 반환한다.
2. The system shall 첨부 종류(이미지/일반 파일)를 기록하고 원본 파일명을 함께 보존한다.
3. If viewer role만 가진 사용자가 파일 첨부 또는 이미지 붙여넣기 저장을 요청하면, the system shall 해당 요청을
   403으로 거부한다.
4. If 요청이 세션 인증되지 않았으면, the system shall 401 공통 에러 응답으로 거부한다.
5. Where 첨부 업로드 크기 제한이 설정된 경우, the system shall 제한을 초과하는 업로드를 거부하고 도메인 규칙
   위반으로 표면화한다.

### Requirement 3: 워크스페이스 격리 저장 및 첨부 조회 서빙

**Objective:** As a 보안·권한 검증자, I want 첨부 파일이 워크스페이스 단위로 격리 저장되고 조회도 워크스페이스
권한으로만 게이팅되기를, so that 한 워크스페이스의 첨부가 다른 워크스페이스로 노출되지 않고 권한 모델(INV-1·6)이
첨부에도 일관되게 적용된다.

#### Acceptance Criteria

1. The system shall 각 첨부 파일을 그 첨부가 속한 워크스페이스 단위로 분리된 저장 위치에 보관한다.
2. The system shall 첨부의 소속 워크스페이스를 클라이언트 입력이 아니라 대상 문서의 소속 워크스페이스로부터
   확정한다.
3. When viewer 이상 사용자가 보관되지 않은 첨부의 바이너리를 요청하면, the system shall 그 첨부가 속한
   워크스페이스 권한을 판정한 뒤 파일 바이너리를 반환한다.
4. If 첨부 소속 워크스페이스에 대해 viewer 미만이거나 비멤버인 사용자가 첨부 바이너리를 요청하면, the system
   shall 403 공통 에러 응답으로 거부한다.
5. The system shall 첨부 접근 권한을 워크스페이스 단위로만 판정하고 문서·첨부별 개별 권한을 두지 않는다.
6. If 존재하지 않는 첨부의 바이너리가 요청되면, the system shall 404 공통 에러 응답을 반환한다.

### Requirement 4: 문서 완전삭제 반응 보관 이동 (8.6, 물리 삭제 없음)

**Objective:** As a 파일 생명주기 관리자, I want 문서가 완전삭제(deleted)되면 그 문서에 연결된 첨부가 삭제되지
않고 보관 폴더로 이동되기를, so that 물리 삭제 없이(INV-4) 완전삭제 문서의 첨부가 정리되어 더는 서빙되지 않는다.

#### Acceptance Criteria

1. When 어떤 문서가 완전삭제되어 deleted 상태가 되면, the system shall 그 문서에 연결된 아직 보관되지 않은
   첨부 전부를 보관 폴더로 이동하고 `is_archived=true`로 표시한다.
2. The system shall 완전삭제 반응 보관 이동을 물리 파일 삭제 없이 파일을 보관 위치로 옮기는 방식으로만
   수행한다(INV-4).
3. The system shall deleted 전이 자체를 수행하지 않고 `s10`·`s07`이 만든 deleted 상태라는 관측 가능한 결과를
   기준으로 보관 이동을 판정한다.
4. The system shall 완전삭제 반응 보관 이동을 반복 수행해도 이미 보관된 첨부를 다시 이동하거나 오류를 내지
   않도록 멱등하게 동작한다.
5. Where 한 완전삭제 묶음에 여러 문서·여러 첨부가 포함된 경우, the system shall 그 묶음의 deleted 문서에 연결된
   첨부만 보관 이동하고 다른 문서의 첨부에는 영향을 주지 않는다.

### Requirement 5: 저장 참조 소멸 이미지 아카이브 (8.7)

**Objective:** As a 파일 생명주기 관리자, I want 새 버전 저장으로 현재 버전이 더 이상 참조하지 않게 된 이미지가
보관 폴더로 이동되기를, so that 과거 버전만 참조하는 이미지가 현재 문서 저장 공간에 남지 않고 정리된다.

#### Acceptance Criteria

1. When 문서의 새 버전 저장으로 현재 버전 본문이 어떤 이미지 첨부를 더 이상 참조하지 않게 되면, the system
   shall 그 이미지 첨부를 보관 폴더로 이동하고 `is_archived=true`로 표시한다.
2. The system shall 어떤 이미지가 현재 버전에 의해 참조되는지 여부를 문서의 현재 버전 본문에 담긴 첨부 참조로
   판정한다.
3. While 첨부가 아직 어떤 저장 버전에도 반영되지 않은 새 붙여넣기 상태인 동안, the system shall 그 이미지를
   참조 소멸로 간주해 보관 이동하지 않는다.
4. The system shall 저장·버전 생성 자체를 수행하지 않고 `s09`가 만든 현재 버전 참조라는 관측 가능한 결과를
   기준으로 참조 소멸을 판정한다.
5. The system shall 현재 버전이 여전히 참조하는 이미지 첨부를 보관 이동하지 않는다.
6. The system shall 저장 참조 소멸 아카이브를 이미지 종류 첨부에 한정하고, 일반 파일 첨부의 보관 이동은 문서
   완전삭제 반응(REQ-4)으로만 처리한다.

### Requirement 6: 보관 폴더 격리·비노출·영구성 (8.8~8.11, INV-7)

**Objective:** As a 보안·권한 검증자, I want 보관 폴더가 워크스페이스별로 격리되고 어떤 조회 경로로도 노출되지
않으며 복원 대상이 아니기를, so that 보관 이동이 영구삭제로 간주되어 애플리케이션상 되돌릴 수 없고 감사·격리
경계가 유지된다.

#### Acceptance Criteria

1. The system shall 보관 폴더를 첨부의 소속 워크스페이스 단위로 분리된 위치로 구성한다.
2. If 보관된(아카이브된) 첨부의 바이너리가 조회 요청되면, the system shall 그 요청을 404로 처리하여 보관 파일을
   노출하지 않는다.
3. The system shall 보관된 첨부 조회 차단을 요청자의 role과 무관하게 적용하여 admin 사용자에게도 보관 파일을
   노출하지 않는다.
4. The system shall 보관 이동을 영구삭제로 간주하고 애플리케이션에 보관 첨부의 복원(active 되돌리기) 경로를
   두지 않는다(INV-7).
5. Where 보관 폴더가 시간에 따라 증가하는 경우, the system shall 자동 정리 없이 단조 증가하는 보관 폴더를
   수용한다.

### Requirement 7: 계약 재사용·경계 정합 및 라우터 조립

**Objective:** As a 하위 feature 구현자·통합 체크포인트, I want s12가 `s01` 단일 계약·`s05` 권한 resolver·하위
계층(s07·s09·s10)의 관측 가능한 결과를 재사용하고 계약을 벗어나지 않기를, so that 계약·불변식 드리프트 없이
첨부가 L5 계층에 정합적으로 얹힌다.

#### Acceptance Criteria

1. The system shall 첨부 응답 스키마를 `s01`의 `{Resource}Read` 규약과 Base Schemas를 상속하여 정의하고
   `attachment` 등 계약 엔티티를 재정의하지 않는다.
2. The system shall 모든 오류를 `s01` 공통 에러 응답 형태(code·message·field_errors)로 반환한다.
3. The system shall `s01` 세션 인증 의존성과 `s05`가 실동작시킨 워크스페이스 권한 resolver를 재사용해 첨부
   업로드·조회 접근을 게이팅하고 resolver 위계 비교·admin bypass 로직을 재구현하지 않는다.
4. The system shall 첨부 라우터를 `s01` 라우터 조립 지점에 등록하여 앱 부팅 시 카탈로그 행 32~33이 노출되도록
   한다.
5. The system shall `attachment`·`document`·`document_version` 접근을 `s01` 초기 마이그레이션 스키마 위에서
   수행하고 새 스키마 마이그레이션을 추가하지 않는다.
6. Where 파일 저장 루트·보관 폴더 루트·아카이브 배치 실행 주기 등 설정이 필요하면, the system shall `s01` 단일
   Settings를 통해서만 접근하고 모듈별 설정 파일을 신설하지 않는다.
7. The system shall 문서 상태 전이·버전 생성·묶음 규칙을 재구현하지 않고 `s07`·`s09`·`s10`이 만든 관측 가능한
   결과(문서 status·현재 버전 참조)에만 의존해 첨부 보관 이동을 판정한다.
