# Requirements Document

## Introduction

`s13-integration-check-L5`는 **계층 5(L5)의 누적 통합 검증 체크포인트**다. 이 시점까지 완성된 upstream 누적
집합(`s01-contract-foundation` ⊕ `s02-auth` ⊕ `s03-admin-account` ⊕ `s05-workspace` ⊕ `s07-document-core`
⊕ `s09-lock-version` ⊕ `s10-trash` ⊕ `s12-attachment`)이 공유 계약과 정합하는지, 그리고 이번 계층에서 처음
결합되는 **경계(첨부·이미지 파일 생명주기 ↔ 문서 완전삭제(휴지통) ↔ 저장·버전 ↔ 아래 계층 권한·계정·워크스페이스
격리)**가 실제 결합 상태에서 성립하는지 mock 없이 검증한다.

이 체크포인트는 **feature 로직을 구현하지 않는다.** 새 엔드포인트·서비스·스키마·마이그레이션·상태 엔진·조정
서비스·스케줄러를 추가하지 않으며, 오직 (1) 누적 upstream의 계약·경계 정합 검증과 (2) 그 검증을 실제 구현 결합으로
실행하는 integration/e2e 테스트만 소유한다. 검증의 유일한 대조 기준은 개별 spec(s02·s03·s05·s07·s09·s10·s12)의
design이 아니라 **`s01-contract-foundation`의 단일 소스**(데이터 스키마 · 세션/권한 resolver 계약 · 카탈로그 행
32~33 · 공통 에러 모델 · Settings 스키마 · 불변식 카탈로그 INV-1~12)다.

L5의 검증 초점은 두 개의 계층 간 트리거다. (1) **보관 이동↔완전삭제 결합(8.6, L4↔L5)**: `s10`이 완전삭제 또는
보관 만료 스윕으로 문서를 `deleted` 상태로 전이시키면, `s12`의 `ArchivalSweepService`가 그 관측 가능한 결과를
스캔해 연결된 미보관 첨부를 워크스페이스 보관 폴더로 **이동**(`is_archived=true`)하되 물리 삭제는 하지 않는다
(INV-4). (2) **참조 소멸↔버전 저장 결합(8.7, L4↔L5)**: `s09`가 새 버전을 저장해 현재 버전 본문이 어떤 이미지
첨부를 더 이상 참조하지 않게 되면, `s12`가 현재 버전 참조를 관측해 그 이미지를 보관 이동하되, 아직 어떤 저장
버전에도 반영되지 않은 새 붙여넣기(`attachment.created_at > current_version.created_at`)는 오아카이브하지 않는
**붙여넣기 보호**를 지킨다. 두 반응은 하위 계층(s09·s10)이 상위 계층(s12)을 알지 못한 채(의존 방향 준수) 실제 DB
상태를 관측·조정하는 방식이므로, 이 체크포인트는 조정 스윕이 **mock 없이 실제 DB 상태에 대해 실제로 실행**되어
관측 가능한 파일시스템 부수효과(보관 폴더로의 이동)와 DB 부수효과(`is_archived=true`)를 남기는지 확인한다.

또한 이번 계층 결합에서 확인해야 할 격리·비노출 축이 있다. 첨부 파일 저장과 보관 폴더가 워크스페이스 단위로
격리되고(8.3·8.8, INV-6), 보관된 첨부는 **요청자의 role과 무관하게 404**로 차단되어 admin에게도 노출되지 않으며
이 차단이 **권한 판정보다 먼저** 적용되고(8.9·8.10, INV-7), 보관에는 복원 경로가 없다. 아울러 이번 계층 결합에서
`s12`가 `s01` `Settings`에 `attachment_archive_root`·`attachment_sweep_interval_seconds`·`attachment_max_bytes`를
**additive**로 추가하고 APScheduler(이미 `s10`이 도입) 스케줄러 어댑터를 lifespan에 결합했다. 이 additive 확장이
`s01` Settings 계약 로딩과 앱 부팅을 회귀시키지 않는지 실제 부팅으로 확인한다.

이 체크포인트는 로드맵의 **게이트(G-1 규칙)**(각 체크포인트가 상위 계층 impl 착수의 선행 조건이 되는 게이트 규칙)을
담당한다: 이 체크포인트가 통과하기 전에는 L6(`s14-sharing`)의 impl을 착수할 수 없다. 또한 upstream
(s01·s02·s03·s05·s07·s09·s10·s12) 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행하는 **재검증
트리거**의 대상이다.

산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md` §2.6·§3 REQ-8·§4.4 보관 이동·§5 INV-1·2·3·4·6·7,
`s01-contract-foundation/design.md`(§Physical Data Model `attachment`(`workspace_id`·`document_id`·`file_path`·
`original_name`·`kind`·`is_archived`) · §API Endpoint Catalog 32~33 · §Errors · §Invariants Catalog · §Settings
스키마 `file_storage_root` · §Common/Permissions), `s12-attachment/design.md`(§AttachmentService·§AttachmentStorage·
§ArchivalSweepService(8.6·8.7)·§ReferenceScanner·§ArchivalScheduler·Settings additive 확장),
`s11-integration-check-L4/design.md`(재사용·확장할 통합 테스트 하네스 `tests/integration_L4` 패턴 — 그것이 재사용하는
L3/L2/L1 하네스 포함), `.kiro/steering/roadmap.md`(게이트·재검증 트리거·Shared seams to watch)를 참조한다.

## Boundary Context

- **In scope (이 체크포인트가 소유)**:
  - **계약 대조 검증**: 실제 결합된 시스템의 `attachment` 스키마(`workspace_id`·`document_id`·`file_path`·
    `original_name`·`kind ENUM('image','file')`·`is_archived`·인덱스 `(workspace_id, is_archived)`·`(document_id)`),
    첨부 API(`s01` 카탈로그 행 32~33: `POST /documents/{id}/attachments`(editor, multipart), `GET /attachments/{id}`
    (viewer, binary)), 응답 스키마 `AttachmentRead`/요청 `AttachmentCreate` 규약, 참조 URL 규약(`/attachments/{id}`),
    공통 에러 모델이 `s01` 단일 소스와 일치하는지 대조. **Settings additive 확장 조정 항목**: `s12`가 추가한
    `attachment_archive_root`·`attachment_sweep_interval_seconds`·`attachment_max_bytes`가 `s01` `Settings` 계약
    로딩을 깨지 않고 기존 필드(`file_storage_root` 등)가 보존되며 아카이브 스케줄러가 lifespan에 결합되는지 확인.
  - **첨부 생성·서빙·격리 흐름 검증(이번 계층 신규 경계 = 첨부 생명주기)**: editor 이상이 편집 중 이미지를
    붙여넣어 파일로 저장(base64 인라인 아님)하고 참조 URL을 받으며(8.1), 파일을 첨부(8.2)하고, 저장이 워크스페이스
    단위로 격리(8.3)됨. viewer 이상이 미보관 첨부 바이너리를 조회하되 소속 워크스페이스 권한으로만 게이팅됨. 문서
    소속 WS 확정이 클라이언트 입력이 아니라 대상 문서 기준임.
  - **보관 이동↔완전삭제 결합 검증(8.6, L4↔L5)**: `s10` 완전삭제(`DELETE /trash/{bundleId}` → `purge_bundle`)
    또는 보관 만료 스윕(`RetentionSweepService`)으로 문서가 `deleted`로 전이된 뒤, `s12` `ArchivalSweepService`가
    실제 DB 상태를 관측해 그 문서에 연결된 미보관 첨부를 보관 폴더로 이동하고 `is_archived=true`로 표시하며 물리
    삭제가 없음(INV-4). deleted 전이는 s12가 수행하지 않고 관측만 함. 반복 실행 멱등. 묶음 범위(해당 deleted 문서
    첨부에만 적용).
  - **참조 소멸↔버전 저장 결합 검증(8.7, L4↔L5)**: `s09` 저장(`POST /documents/{id}/save`)으로 현재 버전 본문이
    어떤 이미지 첨부를 더 이상 참조하지 않게 되면 `s12`가 현재 버전 참조를 관측해 그 이미지를 보관 이동하며, 아직
    저장 버전에 반영되지 않은 새 붙여넣기(`attachment.created_at > current_version.created_at`)는 붙여넣기 보호로
    아카이브하지 않음. 현재 버전이 여전히 참조하는 이미지는 보관하지 않음. 이미지 종류에 한정(일반 파일 첨부는 8.6
    완전삭제 반응으로만).
  - **보관 폴더 격리·비노출·영구성 검증(8.8·8.9·8.10·8.11, INV-7)**: 보관 폴더가 워크스페이스 단위 격리(8.8)이며
    단조 증가를 수용(8.11)함. 보관된 첨부의 바이너리 조회는 요청자 role과 무관하게 404로 차단되어(8.10) admin
    에게도 노출되지 않고(8.9), 이 보관 차단이 **권한 판정보다 먼저** 적용됨. 애플리케이션에 보관 첨부의 복원 경로가
    없음(INV-7).
  - **아래 계층 결합 엣지케이스 검증**: 첨부 업로드는 editor 이상만(viewer 403, INV-2)·비멤버 차단(INV-1)·admin
    bypass(INV-3), 첨부 서빙은 소속 WS viewer 이상만이며 다른 워크스페이스의 첨부가 노출되지 않음(WS 격리, INV-6).
    삭제(`is_deleted=true`) 처리된 사용자가 만든 첨부 레코드가 물리 삭제 없이 보존되고 그 사용자의 후속 첨부 요청이
    로그인 게이트(401)로 차단됨(INV-4). 첨부 시나리오 전반에서 `attachment` 레코드에 예기치 않은 물리 삭제 부재(INV-4).
  - **게이트·재검증 판정**: 위 검증 전부가 mock 없이 통과함을 게이트(G-1 규칙, L5→L6) 통과 조건으로 기록하고,
    재검증 트리거 대상(s01·s02·s03·s05·s07·s09·s10·s12)을 명시.
- **Out of scope (이 체크포인트가 소유하지 않음)**:
  - 새로운 feature 동작·엔드포인트·서비스·스키마·마이그레이션·상태 엔진·조정 서비스·스케줄러 구현(모두
    s01·s02·s03·s05·s07·s09·s10·s12 소유, 이미 완료 가정).
  - 검증 중 발견된 계약 위반의 **수정** — 원인 spec에서 고쳐야 하며, 체크포인트는 회귀를 포착·보고만 한다.
  - **후속 계층(L6) 관심사**: 공유 링크 경유 파일 접근·차단(`GET /public/{token}/attachments/{aid}`, 8.4·8.5,
    카탈로그 행 37, `s14`), 공유 링크 발급·무효화·재발급(INV-8). L5는 첨부의 저장·격리·보관 이동 결과가 성립하는
    범위까지만 관찰하고, 링크 경유 파일 접근 자체는 후속 체크포인트(s15/L6)가 검증한다.
  - 개별 spec 단위 검증의 재실행(각 spec의 자체 테스트 소유). 체크포인트는 **결합·경계**만 본다.
- **Adjacent expectations (인접 spec/계약에 대한 기대)**:
  - `s01`이 `attachment` 스키마, `WorkspaceRoleResolver`/`require_ws_role`/`Role`(위계 판정·admin bypass), 세션
    인증(`get_current_user`/`AuthContext`), 공통 에러 모델, Base Schemas(`ORMReadModel`·`Page`), 엔드포인트 카탈로그
    (행 32~33), `Settings` 스키마(`file_storage_root` 포함), 불변식 카탈로그(INV-1·2·3·4·6·7)를 단일 소스로 제공한다.
  - `s07`이 문서→WS 어댑터(`ws_role_for_document`)·`DocumentRepository`(`get_workspace_id`·`load_current_content`)를
    구현하여 배치되어 있고, `s12`는 이를 재정의 없이 재사용한다.
  - `s09`가 저장 시 새 `document_version` 생성·`document.current_version_id` 갱신을 트리거하여 배치되어 있고,
    `s10`이 완전삭제·보관 만료로 문서를 `deleted`로 전이시켜 배치되어 있으며, `s12`는 이 두 사건의 결과(문서 status·
    현재 버전 참조)를 관측할 뿐 저장·버전 생성·상태 전이를 수행하지 않는다(의존 방향 준수).
  - `s12`가 카탈로그 행 32~33의 동작(첨부 업로드·서빙)과 `AttachmentStorage`(WS 격리 저장/보관 이동)·
    `ArchivalSweepService`(8.6·8.7 조정, `sweep(db, now)`·`archive_for_deleted_documents`·
    `archive_dereferenced_images`)·`ReferenceScanner`·`ArchivalScheduler`(`run_archival_sweep`)를 구현하여 배치되어
    있고, `s01` `Settings`에 `attachment_archive_root`·`attachment_sweep_interval_seconds`·`attachment_max_bytes`를
    additive로 확장하되 새 DB 마이그레이션은 추가하지 않는다.
  - `s11-integration-check-L4`의 통합 테스트 하네스(`tests/integration_L4` — L3/L2/L1 하네스 재사용 + 두 editor
    세션·잠금/휴지통/스윕 시나리오·`now` 주입 스윕 호출 픽스처)가 존재하며, 이 체크포인트는 그 패턴을 **확장·재사용**한다
    (중복 신설 금지).

## Requirements

### Requirement 1: 검증 방법론 및 대조 기준 (mock 없는 실제 결합 · s01 단일 소스 · 누적 집합 · L4 하네스 확장)

**Objective:** As a L5 통합 체크포인트, I want 누적 upstream을 실제 구현으로 결합한 상태에서 단일 계약 소스에 대조
검증하기를, so that 첨부 생명주기와 보관 이동↔완전삭제·참조 소멸↔버전 저장 결합의 회귀가 상위 계층(L6)으로 전파되기
전에 조기에 포착된다.

#### Acceptance Criteria

1. The L5 Integration Checkpoint shall 모든 검증을 mock·stub·가짜 구현 없이 실제 `s01`·`s02`·`s03`·`s05`·`s07`·
   `s09`·`s10`·`s12` 구현을 결합한 상태(마이그레이션 적용된 실제 DB + 실제 부팅된 애플리케이션 + 실제 서명 쿠키 세션 +
   실제 workspace_member 데이터 + 실제 파일시스템 저장/보관 폴더 + 실제 `ArchivalSweepService` + 실제
   `RetentionSweepService`)에서 수행한다.
2. The L5 Integration Checkpoint shall 계약 정합의 대조 기준을 항상 `s01-contract-foundation`의 단일 소스
   (`attachment` 스키마·엔드포인트 카탈로그 32~33·권한 resolver 계약·공통 에러 모델·Settings 스키마·불변식 카탈로그)로
   삼으며, 개별 spec(s02·s03·s05·s07·s09·s10·s12)의 design을 기준으로 삼지 않는다.
3. The L5 Integration Checkpoint shall 어떤 feature 동작·엔드포인트·서비스·스키마·마이그레이션·상태 엔진·조정
   서비스·스케줄러도 신규로 구현하지 않고 검증 및 그 테스트 자산만 산출한다.
4. The L5 Integration Checkpoint shall `s11-integration-check-L4`의 통합 테스트 하네스 패턴(마이그레이션·앱 부팅·
   admin 시드·세션 유지 클라이언트·워크스페이스/멤버/role 세션 시나리오 헬퍼·문서 트리 구성·엔진 세션 접근·휴지통
   삭제/`now` 주입 보관 스윕 호출 픽스처)을 재사용·확장하며 동일한 하네스를 중복 신설하지 않는다.
5. If 검증 대상 시스템에 계약을 위반하는 결합 회귀가 발견되면, the L5 Integration Checkpoint shall 이를 실패로
   보고하되 원인 spec에서의 수정을 유발할 뿐 체크포인트 내부에서 feature 로직을 변경하여 우회하지 않는다.
6. The L5 Integration Checkpoint shall 조정 스윕(8.6·8.7)을 실제 DB 상태에 대해 실제로 실행(`ArchivalSweepService`·
   `run_archival_sweep` 직접 호출, `now` 주입)하여 관측 가능한 파일시스템 부수효과(보관 폴더 이동)와 DB 부수효과
   (`is_archived=true`)를 남기는지 확인하며, 스윕을 mock으로 대체하지 않는다.

### Requirement 2: 계약 대조 — attachment 스키마 · 카탈로그(행 32~33) · AttachmentRead/Create · Settings additive 확장 · 에러 모델

**Objective:** As a L5 통합 체크포인트, I want 결합된 시스템의 첨부 스키마·API·참조 URL 규약·Settings 확장·에러 형태가
`s01` 단일 소스와 일치함을 확인하기를, so that s12가 계약을 벗어난 드리프트 없이 s01 위에 얹혀 있고 additive Settings
확장이 기존 계약을 깨지 않음을 보장한다.

#### Acceptance Criteria

1. The L5 Integration Checkpoint shall 마이그레이션이 적용된 실제 DB의 `attachment` 테이블(`workspace_id BIGINT FK
   NOT NULL`, `document_id BIGINT FK NOT NULL`, `file_path VARCHAR(1024) NOT NULL`, `original_name VARCHAR(255)
   NOT NULL`, `kind ENUM('image','file') NOT NULL`, `is_archived BOOLEAN NOT NULL DEFAULT FALSE`, `created_at
   DATETIME NOT NULL`, INDEX `(workspace_id, is_archived)`·`(document_id)`)이 `s01` 물리 데이터 모델과 컬럼·제약·
   인덱스 면에서 일치하고, `s12`가 새 DB 마이그레이션을 추가하지 않았음을 확인한다.
2. The L5 Integration Checkpoint shall 부팅된 애플리케이션에 `s01` 엔드포인트 카탈로그 행 32~33(`POST
   /documents/{id}/attachments`(editor, multipart), `GET /attachments/{id}`(viewer, binary))이 카탈로그가 정한
   경로·메서드·요구 role대로 노출됨을 확인한다.
3. When 결합된 시스템의 첨부 업로드·조회 엔드포인트가 오류를 반환하면, the L5 Integration Checkpoint shall 응답이
   `s01` 공통 에러 응답 형태(`code`·`message`·선택적 `field_errors`)이고 상태 코드가 에러 코드 카탈로그
   (401/403/404/422)와 일치함을 확인한다.
4. The L5 Integration Checkpoint shall 첨부 업로드 응답 본문 `AttachmentRead`가 `s01` Base Schemas 규약
   (`ORMReadModel` 상속, `id`·`workspace_id`·`document_id`·`kind`·`original_name`·`is_archived`·`created_at`
   포함)을 따르고, 참조 URL(`url`)이 `/attachments/{id}` 규약과 일치하며(문서 본문 참조·8.7 판정 근거), 바이너리
   조회 응답이 스키마 본문이 아니라 스트리밍(binary)임을 확인한다.
5. The L5 Integration Checkpoint shall `s12`가 `s01` `Settings`에 additive로 추가한 `attachment_archive_root`·
   `attachment_sweep_interval_seconds`·`attachment_max_bytes` 필드가 존재하는 실제 결합 부팅에서 `s01` `Settings`/
   `get_settings` 로딩이 정상 성공하고(부팅 실패 없음), 기존 필드(`file_storage_root`·`default_trash_retention_days`·
   `trash_sweep_interval_seconds` 등)가 보존되며, 설정 접근이 여전히 단일 `Settings`/`get_settings` 경유임을
   확인한다(모듈별 설정 파일·`os.environ` 직접 접근 부재).
6. The L5 Integration Checkpoint shall 아카이브 스케줄러 어댑터가 부팅에 결합된 상태에서 `s01` `create_app()`이
   정상 부팅되고, `attachment_sweep_interval_seconds`가 `>0`이면 스케줄러가 기동·`<=0`이면 미기동되며, 이 결합이
   기존 앱 부팅 계약을 회귀시키지 않음을 확인한다.

### Requirement 3: 첨부 생성·서빙·워크스페이스 격리 흐름 결합 (8.1·8.2·8.3, INV-1·2·6 · 권한 게이팅)

**Objective:** As a L5 통합 체크포인트, I want 이미지 붙여넣기·파일 첨부·첨부 서빙이 실제 API 결합에서 계약대로
동작하고 워크스페이스 단위로 격리·게이팅됨을 확인하기를, so that 첨부 도메인(s12)이 s01 계약·s05 권한·s07 문서→WS
어댑터 위에서 격리·권한 불변식(INV-1·6)을 유지함을 보장한다.

#### Acceptance Criteria

1. When editor 이상 사용자가 `POST /documents/{id}/attachments`로 이미지를 붙여넣어 업로드하면, the L5 Integration
   Checkpoint shall 그 이미지가 base64 인라인이 아니라 파일로 저장되고(디스크에 실제 파일 존재) `kind=image`로
   기록되며 응답 `AttachmentRead.url`이 `/attachments/{id}` 규약의 안정 참조를 반환함을 확인한다(8.1).
2. When editor 이상 사용자가 파일(비이미지)을 첨부하면, the L5 Integration Checkpoint shall `kind=file`로 기록되고
   원본 파일명(`original_name`)이 보존되며 대상 문서·워크스페이스에 연결됨을 확인한다(8.2).
3. The L5 Integration Checkpoint shall 첨부의 소속 `workspace_id`가 클라이언트 입력이 아니라 대상 문서의 소속
   워크스페이스로부터 확정되고, 저장 파일이 워크스페이스 단위로 분리된 위치(`file_storage_root/{workspace_id}/...`)에
   보관됨을 파일시스템 관찰로 확인한다(8.3, INV-6).
4. When viewer 이상 사용자가 보관되지 않은 첨부의 바이너리를 `GET /attachments/{id}`로 요청하면, the L5 Integration
   Checkpoint shall 그 첨부 소속 워크스페이스 권한을 판정한 뒤 파일 바이너리를 스트리밍 반환함을 확인한다(8.3 서빙).
5. The L5 Integration Checkpoint shall 첨부 업로드가 `require_ws_role(EDITOR)`(문서→WS 어댑터 경유)로, 첨부 서빙이
   `require_ws_role(VIEWER)`(첨부→WS 어댑터 경유)로 게이팅되어 viewer의 업로드 403(INV-2)·비멤버 차단(INV-1)·미인증
   401·미존재 문서/첨부 404이며 admin이 비멤버 WS에서도 bypass함을 실제 세션 결합으로 확인한다.

### Requirement 4: 보관 이동↔완전삭제 결합 (8.6, L4↔L5, INV-4 · 관측 기반 조정 · 멱등)

**Objective:** As a L5 통합 체크포인트, I want 문서가 완전삭제(deleted)되면 s12 조정 스윕이 실제 DB 상태를 관측해
연결 첨부를 보관 폴더로 이동함을 확인하기를, so that 물리 삭제 없이(INV-4) 완전삭제 문서의 첨부가 정리되어 더는
서빙되지 않는 계층 간 트리거(8.6)가 실제 결합에서 성립함을 보장한다.

#### Acceptance Criteria

1. When editor가 첨부가 연결된 문서를 포함한 묶음을 `DELETE /trash/{bundleId}`(→ `s07` `purge_bundle`)로 완전삭제하여
   문서가 `status=deleted`가 된 뒤 `ArchivalSweepService.archive_for_deleted_documents`(또는 `sweep`/
   `run_archival_sweep`)를 실행하면, the L5 Integration Checkpoint shall 그 문서에 연결된 미보관 첨부 전부가 보관
   폴더로 이동되고 `is_archived=true`로 표시됨을 DB·파일시스템 관찰로 확인한다.
2. When 보관 만료 자동 영구삭제 스윕(`RetentionSweepService`)이 묶음을 `deleted`로 전이시킨 뒤 첨부 아카이브 스윕이
   실행되면, the L5 Integration Checkpoint shall 만료로 deleted된 문서의 첨부도 동일하게 보관 이동됨을 확인한다
   (완전삭제·보관 만료 두 경로 모두 deleted 관측으로 반응).
3. The L5 Integration Checkpoint shall 완전삭제 반응 보관 이동이 물리 파일 삭제 없이 파일을 저장 위치에서 보관
   위치(`attachment_archive_root/{workspace_id}/...`)로 옮기는 이동으로만 수행되고 원본 저장 파일이 물리 삭제되지
   않았음(INV-4)을 파일시스템 관찰로 확인한다.
4. The L5 Integration Checkpoint shall `s12`가 deleted 전이를 직접 수행하지 않고 `s10`·`s07`이 만든 `status=deleted`
   라는 관측 가능한 결과를 스캔해 보관 이동을 판정함을 확인한다(관측 기반 조정, s12는 상태 전이 미수행).
5. When 첨부 아카이브 스윕을 반복 실행하면, the L5 Integration Checkpoint shall 이미 보관된(`is_archived=true`)
   첨부가 다시 이동되거나 오류를 내지 않고 건너뛰어짐(멱등)을 확인하며, 한 완전삭제 묶음의 여러 문서·첨부 중 deleted
   문서에 연결된 첨부만 이동되고 다른(비deleted) 문서의 첨부는 불변임을 확인한다(묶음 범위).

### Requirement 5: 참조 소멸↔버전 저장 결합 (8.7, L4↔L5, 이미지 한정 · 붙여넣기 보호)

**Objective:** As a L5 통합 체크포인트, I want 새 버전 저장으로 현재 버전이 더 이상 참조하지 않게 된 이미지가 s12
조정 스윕으로 보관 이동되되 미저장 새 붙여넣기는 보호됨을 확인하기를, so that 저장(s09) 이벤트에 반응하는 참조 소멸
아카이브(8.7) 계층 간 트리거가 실제 결합에서 붙여넣기 보호를 지키며 성립함을 보장한다.

#### Acceptance Criteria

1. When 이미지 첨부를 참조하던 문서가 그 참조를 제거한 새 본문으로 `POST /documents/{id}/save`(→ `s09` 새
   `document_version` 생성·`current_version_id` 갱신)된 뒤 `ArchivalSweepService.archive_dereferenced_images`(또는
   `sweep`/`run_archival_sweep`)를 실행하면, the L5 Integration Checkpoint shall 그 이미지 첨부가 보관 폴더로 이동되고
   `is_archived=true`로 표시됨을 확인한다(8.7 참조 소멸 아카이브).
2. The L5 Integration Checkpoint shall 어떤 이미지가 현재 버전에 의해 참조되는지 여부가 현재 버전 본문에 담긴 첨부
   참조 URL(`/attachments/{id}`) 토큰 존재로 판정되고(`ReferenceScanner`), 현재 버전이 여전히 참조하는 이미지 첨부는
   보관 이동되지 않음을 확인한다(5.5 현재 참조 유지 시 미보관).
3. While 첨부가 아직 어떤 저장 버전에도 반영되지 않은 새 붙여넣기 상태인 동안(`attachment.created_at >
   current_version.created_at`), the L5 Integration Checkpoint shall 그 이미지를 참조 소멸로 간주하지 않고 보관
   이동하지 않음을 확인한다(붙여넣기 보호, 편집 중 붙여넣기 직후 오아카이브 방지).
4. The L5 Integration Checkpoint shall `s12`가 저장·버전 생성 자체를 수행하지 않고 `s09`가 만든 현재 버전 참조라는
   관측 가능한 결과를 기준으로 참조 소멸을 판정함을 확인한다(관측 기반 조정, s12는 저장·버전 생성 미수행).
5. The L5 Integration Checkpoint shall 참조 소멸 아카이브가 이미지 종류(`kind=image`) 첨부에 한정되고 일반 파일
   첨부(`kind=file`)는 참조 소멸 스윕으로 보관 이동되지 않으며 파일 첨부의 보관 이동은 문서 완전삭제 반응(8.6)으로만
   처리됨을 확인한다(5.6 이미지 한정).

### Requirement 6: 보관 폴더 격리·비노출·영구성 및 role 무관 404 (8.8·8.9·8.10·8.11, INV-7 · 권한 판정 이전 차단)

**Objective:** As a L5 통합 체크포인트, I want 보관 폴더가 워크스페이스별로 격리되고 보관된 첨부가 어떤 role로도
노출되지 않으며 복원 대상이 아님을 확인하기를, so that 보관 이동이 영구삭제로 간주되어 애플리케이션상 되돌릴 수 없고
격리·비노출 경계(INV-7)가 실제 결합에서 유지됨을 보장한다.

#### Acceptance Criteria

1. When 보관된(아카이브된) 첨부의 바이너리가 `GET /attachments/{id}`로 조회 요청되면, the L5 Integration Checkpoint
   shall 그 요청이 요청자 role과 무관하게 404로 처리되어 보관 파일을 노출하지 않음을 확인한다(8.10, viewer·editor·
   owner 모두 404).
2. When admin 사용자가 보관된 첨부의 바이너리를 조회 요청하면, the L5 Integration Checkpoint shall admin에게도 404가
   반환되어 보관 파일이 노출되지 않고, 이 보관 차단이 **워크스페이스 권한 판정보다 먼저** 적용됨(role 무관 차단이
   resolver 게이트에 도달하기 전에 성립)을 확인한다(8.9, admin 포함 비노출).
3. The L5 Integration Checkpoint shall 보관 폴더가 첨부 소속 워크스페이스 단위로 분리된 위치
   (`attachment_archive_root/{workspace_id}/...`)로 구성되어 한 워크스페이스의 보관 파일이 다른 워크스페이스 경로에
   섞이지 않음을 파일시스템 관찰로 확인한다(8.8, INV-6).
4. The L5 Integration Checkpoint shall 애플리케이션에 보관된 첨부를 active로 되돌리는(복원) 엔드포인트·경로가 존재하지
   않고, 보관 후 그 첨부의 조회가 어떤 role로도 성공하지 않음을 확인한다(8.9 복원 없음, INV-7).
5. Where 보관 폴더가 시간에 따라 증가하는 경우, the L5 Integration Checkpoint shall 애플리케이션이 보관 폴더를 자동
   정리하지 않고 단조 증가를 수용함(반복 스윕 후에도 보관 파일이 삭제되지 않음)을 확인한다(8.11).

### Requirement 7: 아래 계층 결합 엣지케이스 — 권한/계정 결합 · WS 격리 · 작성자/물리삭제 부재 (INV-1·2·3·4·6)

**Objective:** As a L5 통합 체크포인트, I want role별 첨부 접근 경계와 admin override, 워크스페이스 첨부 격리, 삭제된
사용자의 첨부 레코드 보존이 계정·워크스페이스 계층 결합에서 성립함을 확인하기를, so that 아래 계층(auth·admin·
workspace)과 첨부 도메인의 결합이 실제 결합에서 안전함을 보장한다.

#### Acceptance Criteria

1. The L5 Integration Checkpoint shall role별 세션(owner/editor/viewer/비멤버/admin)으로 첨부 업로드·서빙 접근
   경계를 관찰하여 viewer의 업로드 거부(INV-2)·비멤버 차단(INV-1)·admin의 비멤버 WS 첨부 업로드·서빙 접근 성공
   (INV-3)이 아래 계층(s02 세션·s05 멤버십) 결합 위에서 성립함을 확인한다.
2. When 워크스페이스 A의 첨부를 워크스페이스 B에만 소속된(A 비멤버) 사용자가 `GET /attachments/{id}`로 요청하면,
   the L5 Integration Checkpoint shall 그 요청이 403으로 거부되어 한 워크스페이스의 첨부가 다른 워크스페이스로
   노출되지 않음(WS 격리, INV-6)을 확인한다.
3. When 첨부를 업로드한 사용자가 admin에 의해 삭제(`is_deleted=true`) 처리되면, the L5 Integration Checkpoint
   shall 그 사용자가 업로드한 첨부의 `attachment` 레코드와 그 사용자가 작성한 문서의 `created_by`가 물리 삭제 없이
   DB에 보존되고(첨부 스키마에 업로더 FK가 없으므로 첨부 레코드 자체의 존속으로 관찰), 삭제된 사용자의 후속 첨부
   업로드·조회 요청이 로그인 게이트(401)로 차단됨을 확인한다(INV-4, 계정 생명주기 결합).
4. The L5 Integration Checkpoint shall 첨부 업로드·서빙·완전삭제 반응 보관 이동·참조 소멸 아카이브 시나리오 전반에서
   `attachment` 레코드에 예기치 않은 물리 삭제(DELETE row)가 발생하지 않고 보관은 항상 `is_archived=true` + 파일
   이동으로만 표현됨을 확인한다(INV-4, 물리 삭제 부재).

### Requirement 8: 게이트 G-1 판정 및 재검증 트리거 (누적, L5→L6)

**Objective:** As a 로드맵 게이트 관리자, I want L5 검증 결과가 L6 impl 착수 가부와 재검증 대상을 명확히 산출하기를,
so that L6(`s14-sharing`) impl 착수 가부와 upstream 변경 시 재실행 범위를 예측 가능하게 통제할 수 있다.

#### Acceptance Criteria

1. When Requirement 2~7의 모든 검증이 실제 결합 상태에서 통과하면, the L5 Integration Checkpoint shall 게이트를
   통과로 판정하여 L6(`s14-sharing`) impl 착수의 선행 조건 충족을 기록한다.
2. If Requirement 2~7 중 하나라도 실패하면, the L5 Integration Checkpoint shall 게이트를 미통과로 판정하고 L6
   impl 착수를 차단 상태로 표시한다.
3. The L5 Integration Checkpoint shall 재검증 트리거 대상을 명시한다: `s01`·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·
   `s12` 중 어느 것이 수정되어도 이 체크포인트(및 로드맵상 그 이후 모든 체크포인트 L6)를 누적 집합 기준으로
   재실행해야 하며, `s01` 수정 시에는 모든 체크포인트를 재실행해야 한다.
4. If 검증 대상 환경(마이그레이션된 MySQL 8·부팅 앱·파일시스템 저장/보관 폴더·아카이브 스케줄러 결합)이 미충족이면,
   the L5 Integration Checkpoint shall 이를 스킵이 아니라 실패로 처리하여 미검증이 게이트 통과로 오인되지 않게 한다.
