# Implementation Plan — s13-integration-check-L5

> **통합 검증 체크포인트(L5)** — feature 로직을 구현하지 않는다. 산출물은 `backend/tests/integration_L5/`의
> integration/e2e 테스트 자산과 게이트(G-1 규칙, L5→L6) 판정뿐이다. 모든 명령은 `backend/`에서 `uv run` 기준,
> 산출물 언어 한국어, 코드 식별자는 영어. **mock 금지**(실제 `s01`·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·`s12` 구현 +
> 실제 workspace_member·document·document_version·attachment 데이터 + 실제 파일시스템 저장/보관 폴더 + 실제
> `ArchivalSweepService` + 실제 `RetentionSweepService` 결합; 조정 서비스·스윕·엔진 직접 호출은 실제 s12·s10·s07 코드
> 실행이므로 허용). 계약 대조 기준은 개별 spec design이 아니라 **`s01-contract-foundation` 단일 소스**다. 애플리케이션
> 코드(`app/*`)·`config.yml`·마이그레이션·하위 하네스(`tests/integration_L4/*`·`L3`·`L2`·`L1`)는 수정하지 않는다 —
> L4 하네스는 **재사용·확장**한다.

- [ ] 1. Foundation: L5 실제 결합 검증 하네스 (L4 재사용·확장)
- [x] 1.1 L5 통합 테스트 하네스 구성 (L4 하네스 재사용 + 첨부 업로드/서빙·아카이브 스윕·파일시스템 관찰 픽스처)
  - `tests/integration_L5/conftest.py`에서 `s11` `tests/integration_L4`의 하네스 픽스처(실제 MySQL 8에 `alembic
    upgrade head` 적용·`s01` `create_app()` 부팅·admin 시드·세션 유지 `TestClient` 팩토리·고유 login_id 생성기·
    워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트·문서 트리 생성·부팅 앱과 동일 `SessionLocal`/`get_db`
    세션의 `DocumentStateEngine` 접근·두 editor(A·B) 세션·휴지통 삭제·`now` 주입 `RetentionSweepService` 호출)를
    재사용하고, 부팅 앱이 s02·s03·s05·s07·s09·s10·**s12 첨부 라우터 + 아카이브 스케줄러가 조립된 상태**(첨부 업로드·
    서빙 라우트 노출, lifespan 아카이브 스케줄러 훅 결합)임을 전제로 한다. 대상 문서에 이미지(`kind=image`)·파일
    (`kind=file`)을 업로드하고 이미지 참조 포함/제외 본문으로 저장(`POST /documents/{id}/save`)해 현재 버전 참조를
    만들거나 소멸시키는 첨부 시나리오 픽스처, 첨부 연결 문서를 완전삭제(`DELETE /trash/{bundleId}`) 또는 보관 만료
    스윕으로 `deleted` 전이시키는 deleted 유발 픽스처(L4 헬퍼 재사용), 부팅 앱과 동일 DB 세션으로 `s12`
    `ArchivalSweepService`(`sweep`/`archive_for_deleted_documents`/`archive_dereferenced_images`) 또는
    `run_archival_sweep`를 **`now` 주입**으로 호출하는 아카이브 스윕 접근 픽스처, `file_storage_root`/
    `attachment_archive_root` 기준 저장/보관 파일 존재·부재·WS 경로 격리를 관찰하는 파일시스템 관찰 픽스처를 신규 추가
  - mock·stub을 사용하지 않으며(조정 서비스·스윕·엔진 직접 호출은 실제 s12·s10·s07 코드), DB·파일시스템 미가용·부팅
    실패 시 스킵이 아니라 실패로 처리. 설정은 s01 `Settings` 재사용(additive `attachment_archive_root`·
    `attachment_sweep_interval_seconds`·`attachment_max_bytes` 포함), 애플리케이션 코드·`config.yml`·하위 하네스 자산은
    수정하지 않음(재사용만). 동일 하네스를 중복 신설하지 않음
  - 관찰 가능 완료: 픽스처가 마이그레이션된 DB + 부팅 앱(s12 첨부 라우트·아카이브 스케줄러 포함) + admin 시드 +
    role별·다중 WS 세션 클라이언트 + 구성된 워크스페이스/멤버/문서/첨부 + 조정 서비스 인스턴스 + `now` 주입 아카이브
    스윕 호출 헬퍼 + 파일시스템 관찰 헬퍼를 제공하고, editor가 `POST /documents/{id}/attachments`에서 200과
    `AttachmentRead.url`을, `GET /attachments/{id}`가 바이너리를, 아카이브 스윕 픽스처가 `run_archival_sweep`/
    `sweep(db, now)` 호출에서 결과를 반환하는 스모크 검증이 통과한다
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_
  - _Boundary: L5TestHarness_
- [x] 1.2 첨부·아카이브 스윕·파일시스템 시나리오 헬퍼 구성 (호출 래퍼, L4 헬퍼 재사용)
  - `tests/integration_L5/helpers.py`에 첨부 헬퍼(`POST /documents/{id}/attachments` multipart image/file 업로드·크기
    지정·`GET /attachments/{id}` 조회 래퍼), 이미지 참조 저장 헬퍼(첨부 `url`=`/attachments/{id}`을 포함/제외한
    markdown 본문으로 `POST /documents/{id}/save` 호출해 현재 버전 참조 생성/소멸), 아카이브 스윕 헬퍼(하네스 세션으로
    `ArchivalSweepService.sweep(db, now)`/`archive_for_deleted_documents`/`archive_dereferenced_images` 또는
    `run_archival_sweep` 호출·처리 건수/`is_archived`/파일시스템 상태 관찰, `now` 주입), 파일시스템 관찰 헬퍼
    (`file_storage_root`/`attachment_archive_root` 기준 저장/보관 파일 존재·부재·WS 경로 격리 확인)를 제공. 잠금·저장·
    휴지통 삭제·완전삭제·`now` 주입 retention 스윕·워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트·계정 생성·
    로그인·상태 전이(비활동/삭제) 헬퍼는 `s11` L4 `helpers.py`(및 그것이 재사용하는 L3/L2/L1 헬퍼)를 재사용(중복 정의
    금지)
  - 관찰 가능 완료: 헬퍼로 editor가 이미지를 업로드하고 참조 본문 저장 후 `GET /attachments/{id}`가 바이너리를
    반환하고, 첨부 연결 문서를 완전삭제한 뒤 아카이브 스윕 헬퍼가 `now` 주입 호출로 처리 건수를 반환하며, 파일시스템
    관찰 헬퍼가 저장/보관 경로의 파일 존재를 보고하는 스모크 검증이 통과한다
  - _Requirements: 1.4, 3.1, 4.1, 5.1, 6.1_
  - _Boundary: Helpers_
  - _Depends: 1.1_

- [ ] 2. Core: 계약 대조·첨부흐름·완전삭제결합·저장결합·격리비노출·아래계층 엣지 검증 스위트
- [x] 2.1 (P) 누적 계약 대조 스위트 — attachment 스키마·API(32~33)·AttachmentRead/Create·에러·Base·Settings additive
  - `tests/integration_L5/test_cumulative_contract_conformance.py`에: (1) 마이그레이션된 `attachment` 컬럼
    (`workspace_id BIGINT FK NOT NULL`·`document_id BIGINT FK NOT NULL`·`file_path VARCHAR(1024) NOT NULL`·
    `original_name VARCHAR(255) NOT NULL`·`kind ENUM('image','file') NOT NULL`·`is_archived BOOLEAN NOT NULL DEFAULT
    FALSE`·`created_at DATETIME NOT NULL`)과 인덱스(`(workspace_id, is_archived)`·`(document_id)`)가 s01 물리 모델과
    일치하고 s12가 새 마이그레이션을 추가하지 않았음, (2) 부팅 앱 라우트가 s01 카탈로그 행 32~33(`POST
    /documents/{id}/attachments` editor·`GET /attachments/{id}` viewer) 경로·메서드·요구 role대로 노출, (3) 미인증
    401·viewer 업로드 403·미존재 문서/첨부 404·업로드 크기 초과 422를 실제 유발해 응답이 `ErrorResponse`
    (code/message/field_errors) 형태이고 상태 코드가 s01 에러 카탈로그와 일치, (4) `AttachmentRead`가 s01 Base 규약
    (`ORMReadModel` 상속·`id`·`workspace_id`·`document_id`·`kind`·`original_name`·`is_archived`·`created_at`)을 따르고
    `url`이 `/attachments/{id}` 규약과 일치·바이너리 조회 응답이 스트리밍(binary)·`AttachmentCreate` multipart 규약,
    (5) s12 additive `attachment_archive_root`·`attachment_sweep_interval_seconds`·`attachment_max_bytes`가 존재하는
    실제 결합 부팅에서 `s01` `Settings`/`get_settings` 로딩 정상 성공·기존 필드(`file_storage_root`·
    `default_trash_retention_days`·`trash_sweep_interval_seconds` 등) 보존·단일 접근자 유지, (6) 아카이브 스케줄러
    결합 부팅에서 `create_app()` 정상 부팅·`attachment_sweep_interval_seconds` `>0` 기동/`<=0` 미기동·기존 부팅 계약
    무회귀를 검증. 대조 기준은 s01 단일 소스
  - 관찰 가능 완료: 스키마(attachment)·API 노출(32~33)·에러 형태·Base 규약·참조 URL·Settings additive 로딩·스케줄러
    결합 대조 그룹이 실제 결합 런타임에서 모두 통과하고, 불일치 시 어느 계약 요소가 드리프트했는지 assertion 메시지가
    지목한다
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Boundary: CumulativeContractConformanceSuite_
  - _Depends: 1.1_
- [x] 2.2 (P) 첨부 생성·서빙·WS 격리 흐름 스위트 — 이미지 붙여넣기·파일 첨부·서빙·게이팅 (8.1·8.2·8.3, INV-1·2·6)
  - `tests/integration_L5/test_attachment_lifecycle_flow.py`에 동일 WS의 owner/editor/viewer/비멤버/admin 세션으로:
    (1) editor가 이미지 업로드 → `kind=image`·파일로 저장(디스크 존재, base64 인라인 아님)·`AttachmentRead.url` =
    `/attachments/{id}` 반환 (3.1, 8.1), (2) editor가 비이미지 파일 업로드 → `kind=file`·`original_name` 보존·대상
    문서/WS 연결 (3.2, 8.2), (3) 소속 `workspace_id`가 대상 문서에서 확정되고 저장 파일이 `file_storage_root/
    {workspace_id}/` 하위에 격리됨을 파일시스템 관찰 (3.3, 8.3, INV-6), (4) viewer가 미보관 첨부 바이너리 조회 성공
    (스트리밍·content-type) (3.4), (5) 업로드=editor(viewer 403·비멤버 403·미인증 401)·서빙=viewer(비멤버 403)·미존재
    문서/첨부 404·admin bypass (3.5, INV-1·2·3)을 실제 세션 쿠키 자로 e2e+파일시스템 관찰로 검증. 판정은 s05 실제
    멤버십 데이터 위에서 이뤄짐. mock 없음
  - 관찰 가능 완료: 이미지 파일 저장·파일 첨부·WS 격리 저장·viewer 서빙·업로드/서빙 게이팅이 실제 결합에서 모두
    예상대로 통과/거부되고, 저장 파일이 WS별 경로에 격리됨이 파일시스템으로 확인된다
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - _Boundary: AttachmentLifecycleFlowSuite_
  - _Depends: 1.2_
- [x] 2.3 (P) 보관 이동↔완전삭제 결합 스위트 — deleted 관측 → 보관 이동·물리삭제 부재·멱등·묶음 범위 (8.6, INV-4)
  - `tests/integration_L5/test_purge_archive_combination.py`에: (1) 첨부 연결 문서를 trashed 후 `DELETE
    /trash/{bundleId}`(→ `purge_bundle`)로 `status=deleted` → `run_archival_sweep`/`archive_for_deleted_documents`
    실행 → 연결 미보관 첨부가 보관 폴더로 이동·`is_archived=true` DB·파일시스템 관찰 (4.1), (2) `now` 주입
    `RetentionSweepService`로 만료 묶음을 `deleted` 전이 → 아카이브 스윕 실행 → 만료 deleted 문서 첨부도 동일하게 보관
    이동(두 deleted 경로 모두 반응) (4.2), (3) 이동은 저장 파일을 `attachment_archive_root/{workspace_id}/`로 옮기는
    것이며 원본 저장 파일이 물리 삭제되지 않고 보관 경로에 존재함을 파일시스템 관찰 (4.3, INV-4), (4) s12가 deleted
    전이를 수행하지 않고 `document.status='deleted'` 관측으로 판정함(비deleted 문서 첨부는 미대상) (4.4), (5) 반복
    스윕에 이미 보관 첨부 skip(멱등)·완전삭제 묶음의 deleted 문서 첨부만 이동·다른(비deleted) 문서 첨부 불변(묶음 범위)
    (4.5)을 검증. deleted 유발은 실제 완전삭제·retention 스윕으로(임의 DB 조작 금지). 스윕·엔진 직접 호출은 실제
    s12·s10·s07 코드. mock 없음
  - 관찰 가능 완료: 완전삭제·보관 만료 두 경로 모두 deleted 관측 후 첨부 보관 이동·물리삭제 부재·관측 판정·멱등·묶음
    범위가 실제 결합에서 모두 통과하고, 보관 이동이 파일시스템·DB 부수효과로 확인된다(8.6)
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - _Boundary: PurgeArchiveCombinationSuite_
  - _Depends: 1.2_
- [x] 2.4 (P) 참조 소멸↔버전 저장 결합 스위트 — 이미지 보관 이동·붙여넣기 보호·현재참조 유지 미보관·이미지 한정 (8.7)
  - `tests/integration_L5/test_save_dereference_combination.py`에: (1) 이미지 참조를 포함한 본문으로 저장 → 참조를
    제거한 새 본문으로 재저장(s09 새 버전·current 갱신) → `run_archival_sweep`/`archive_dereferenced_images` 실행 →
    그 이미지가 보관 이동·`is_archived=true` (5.1), (2) 현재 버전 본문에 `/attachments/{id}` 토큰이 존재하면 보관하지
    않음(`ReferenceScanner`)·여전히 참조되는 이미지는 스윕 후에도 미보관 (5.2, 5.5 현재 참조 유지), (3)
    `attachment.created_at > current_version.created_at`(미저장 새 붙여넣기)이면 참조 소멸로 간주하지 않고 미보관
    (붙여넣기 보호; 붙여넣기→저장 순서·`now` 주입으로 경계 결정적 검증) (5.3), (4) s12가 저장·버전 생성을 수행하지 않고
    s09가 만든 현재 버전 참조를 관측(`load_current_content`)해 판정 (5.4), (5) 참조 소멸 스윕은 `kind=image`에만 적용·
    `kind=file`은 참조 소멸로 미보관·파일 첨부 보관 이동은 완전삭제 반응(8.6)으로만 (5.5, 이미지 한정)을 검증. 저장은
    실제 `POST /documents/{id}/save`로(임의 DB 조작 금지). 스윕·저장 직접 호출은 실제 s12·s09 코드. mock 없음
  - 관찰 가능 완료: 저장 참조 소멸 이미지 보관 이동·현재 참조 유지 미보관·붙여넣기 보호·이미지 한정이 실제 결합에서
    모두 통과하고, 참조 소멸 아카이브가 파일시스템·DB 부수효과로 확인된다(8.7)
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: SaveDereferenceCombinationSuite_
  - _Depends: 1.2_
- [x] 2.5 (P) 보관 격리·비노출 스위트 — role 무관 404(admin 포함·권한 이전)·복원 없음·보관 WS 격리·단조증가 (INV-7)
  - `tests/integration_L5/test_archive_isolation.py`에 8.6/8.7 실제 스윕으로 첨부를 보관 처리한 뒤: (1) 보관된 첨부를
    viewer·editor·owner가 `GET /attachments/{id}`로 조회하면 모두 404(role 무관) (6.1, 8.10), (2) admin도 404이며 이
    보관 차단이 `require_ws_role` 권한 판정에 도달하기 전에 적용됨(보관 첨부는 소속 WS 멤버 여부와 무관하게 404) (6.2,
    8.9), (3) 보관 파일이 `attachment_archive_root/{workspace_id}/` 하위에 격리되어 다른 WS 경로에 섞이지 않음 파일시스템
    관찰 (6.3, INV-6), (4) 보관 첨부를 active로 되돌리는 엔드포인트 부재·보관 후 조회가 어떤 role로도 미성공 (6.4,
    INV-7), (5) 반복 스윕 후에도 보관 파일이 자동 정리·삭제되지 않고 존속(단조 증가 수용) (6.5, 8.11)을 검증. 보관
    유발은 실제 8.6/8.7 스윕으로(임의 DB 조작 금지). mock 없음
  - 관찰 가능 완료: 보관 role 무관 404·admin 차단·권한 판정 이전 차단·보관 폴더 WS 격리·복원 경로 부재·단조 증가가
    실제 결합에서 모두 통과하고, 보관 이동이 영구삭제로 간주됨(INV-7)이 확인된다
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Boundary: ArchiveIsolationSuite_
  - _Depends: 1.2_
- [ ] 2.6 (P) 아래 계층 결합 엣지 스위트 — role별 접근 경계·admin override·WS 격리·삭제 사용자·물리삭제 부재 (INV-1·2·3·4·6)
  - `tests/integration_L5/test_combination_layer_edge.py`에: (1) owner/editor/viewer/비멤버/admin 세션으로 첨부 업로드·
    서빙 접근 경계 관찰 → viewer 업로드 거부(INV-2)·비멤버 차단(INV-1)·admin 비멤버 WS 첨부 업로드·서빙 접근 성공
    (INV-3)이 아래 계층(s02 세션·s05 멤버십) 결합 위에서 성립 (7.1), (2) 워크스페이스 A의 첨부를 B에만 소속된(A 비멤버)
    사용자가 `GET /attachments/{id}`로 요청하면 403(다른 WS 첨부 비노출, WS 격리) (7.2, INV-6), (3) 첨부를 업로드한
    사용자를 admin이 `is_deleted=true` 처리한 뒤 그 사용자가 업로드한 첨부 레코드·작성 문서 `created_by`가 물리 삭제
    없이 DB 보존(첨부 스키마에 업로더 FK 부재이므로 레코드 존속으로 관찰)·삭제 사용자의 후속 첨부 업로드·조회 401 로그인
    게이트 차단 (7.3, INV-4), (4) 첨부 업로드·서빙·보관 이동·참조 소멸 시나리오 전반에서 `attachment` 레코드 물리 삭제
    (DELETE row) 부재·보관은 항상 `is_archived=true` + 파일 이동으로만 표현 (7.4, INV-4)를 API+DB+파일시스템 관찰로
    검증. 계정 상태 전이 헬퍼는 s11 L4(및 L3/L2/L1) 헬퍼 재사용. mock 없음
  - 관찰 가능 완료: role별 접근 경계·admin override·WS 격리·삭제 사용자 첨부 레코드 보존·로그인 게이트·물리 삭제 부재가
    실제 DB·파일시스템 관찰로 모두 통과한다
  - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - _Boundary: CombinationLayerEdgeSuite_
  - _Depends: 1.2_

- [ ] 3. Validation: 게이트 판정 및 재검증 트리거
- [ ] 3.1 전체 스위트 결합 실행 및 게이트(L5→L6) 판정·재검증 트리거 기록
  - `uv run pytest tests/integration_L5` 전체를 실제 결합(마이그레이션 DB + 부팅 앱(s12 첨부 라우터·아카이브 스케줄러
    포함) + 실제 멤버십/문서/버전/첨부 데이터 + 실제 파일시스템 저장/보관 폴더 + 실제 `ArchivalSweepService` + 실제
    `RetentionSweepService` + 실제 `DocumentStateEngine`, mock 없음)에서 실행하여 Requirement 2~7 스위트가 전부
    통과하면 게이트(G-1 규칙) 통과(=L6 `s14-sharing` impl 착수 선행 조건 충족)로, 하나라도 실패하면 미통과(=L6 착수
    차단)로 판정. 검증 실패는 원인 spec(s01/s02/s03/s05/s07/s09/s10/s12)에서 수정 후 재실행하며 체크포인트에서 feature
    로직을 변경해 우회하지 않음. 검증 대상 환경(MySQL 8·부팅 앱·파일시스템 저장/보관 폴더·아카이브 스케줄러 결합)
    미충족은 스킵이 아니라 실패로 처리. 재검증 트리거(`s01`/`s02`/`s03`/`s05`/`s07`/`s09`/`s10`/`s12` 수정 시 이
    체크포인트 및 로드맵상 그 이후 모든 체크포인트 L6를 누적 집합 기준 재실행, `s01` 수정 시 모든 체크포인트 재실행)를
    스위트 문서/주석으로 명시
  - 관찰 가능 완료: `uv run pytest tests/integration_L5`가 전부 통과하여 게이트 통과가 성립하고, 재검증 트리거 대상과
    L6 착수 가부가 명확히 기록된다
  - _Requirements: 1.5, 8.1, 8.2, 8.3, 8.4_
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

## Implementation Notes

- 1.2: `DocumentVersionRead`(app/lock_version/schemas.py)에는 `content` 필드가 없다 — 저장 응답으로 본문 참조 유무를 단언하지 말 것(vacuous). 참조 소멸 판정은 `ArchivalSweepService`/`ReferenceScanner`가 현재 버전 본문(`load_current_content`)으로 하므로, 2.4 스위트는 스윕 부수효과(is_archived·파일 이동)로 관찰한다.
- 공통: 첨부 업로드 라우트는 **201 CREATED** 반환(`app/attachment/router.py`), tasks.md 스모크 서술의 "200"은 부정확 — 실제 계약(s01 카탈로그 32~33)·구현 기준 201로 단언. 계약 대조(2.1)는 s01 단일 소스 기준으로 드리프트를 판정.
