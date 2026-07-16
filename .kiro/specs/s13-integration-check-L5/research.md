# Research Log — s13-integration-check-L5

## Discovery 범위

L5 누적 통합 검증 체크포인트의 설계 근거를 정리한다. 이 체크포인트는 **애플리케이션 아키텍처를 확장하지 않는다.**
`backend/tests/integration_L5/` 하나의 테스트 계층만 추가하고, `s11-integration-check-L4`의 하네스
(`tests/integration_L4`, 그것이 재사용하는 L3/L2/L1 포함)를 재사용·확장한다. Discovery 유형은 **Extension
(integration-focused)** 이며, 신규 외부 의존성·라이브러리 조사는 없다(테스트 도구 + s12 조정 서비스·스토리지 소비만
사용).

## 조사 대상과 발견

### 1) 대조 기준 = s01 단일 소스 (개별 spec design 아님)

- `s01-contract-foundation/design.md`:
  - **§Physical Data Model `attachment`**: `workspace_id`·`document_id`·`file_path VARCHAR(1024)`·`original_name
    VARCHAR(255)`·`kind ENUM('image','file')`·`is_archived BOOLEAN DEFAULT FALSE`·`created_at`, INDEX
    `(workspace_id, is_archived)`·`(document_id)`. 업로더 FK(`created_by`)는 **없음** — 첨부 레코드 보존 관찰은
    레코드 존속 자체로 판정한다.
  - **§API Endpoint Catalog 행 32~33**: 32 `POST /documents/{id}/attachments`(editor, multipart
    `AttachmentCreate` → `AttachmentRead`, 8.1·8.2·8.3), 33 `GET /attachments/{id}`(viewer, → binary, 8.4).
    행 37(`GET /public/{token}/attachments/{aid}`, s14)은 **L6 범위** — L5 out of scope.
  - **§Invariants Catalog**: INV-1(권한 WS 단위)·INV-2(viewer 변경 불가)·INV-3(admin bypass)·INV-4(물리 삭제
    없음: `attachment.is_archived`)·INV-6(WS 경계: `attachment.workspace_id`)·INV-7(deleted 문서·보관 파일 복원
    경로 없음: `attachment.is_archived`).
  - **§Settings 스키마**: `file_storage_root`(첨부 파일 저장 루트, 기존). s12가 `attachment_archive_root`·
    `attachment_sweep_interval_seconds`·`attachment_max_bytes`를 **additive**로 확장.
- 결론: 계약 대조 스위트는 s12 design이 아니라 위 s01 요소에 대조한다(roadmap §게이트 규칙). 이는 여러 spec design을
  서로 대조할 때 생기는 드리프트를 막기 위한 로드맵의 핵심 선택이다.

### 2) 이번 계층 신규 경계와 계층 간 트리거

- `s12-attachment/design.md` 핵심: 두 생명주기 반응을 **동기 콜백이 아니라 관측 기반 조정(reconciliation)**으로
  구현. 하위 계층(s09/s10)은 s12를 import하지 않으므로, s12는 `document.status`와 현재 버전 참조라는 관측 가능한 DB
  상태를 스캔해 판정한다.
  - **8.6 완전삭제 반응 보관 이동**: `ArchivalSweepService.archive_for_deleted_documents(db)` — 미보관 첨부 중
    `document.status='deleted'`인 것을 열거해 `AttachmentStorage.move_to_archive` + `mark_archived`. 이미 보관된
    첨부는 스코프에서 제외(멱등).
  - **8.7 참조 소멸 아카이브**: `archive_dereferenced_images(db)` — 미보관 `kind='image'` 첨부 중 문서가 active/
    trashed이고 `current_version_id` 존재인 것을 열거 → **붙여넣기 보호**(`attachment.created_at >
    current_version.created_at`이면 skip) → `ReferenceScanner.is_referenced(content, id)`가 False면 보관 이동.
  - `sweep(db, now)`가 두 조정을 순서대로 수행, `run_archival_sweep()`이 `SessionLocal` 세션으로 1회 스윕(테스트·
    수동·외부 cron 엔트리포인트). `now` 주입으로 결정성 확보.
  - **서빙 차단 순서**: `GET /attachments/{id}`에서 `is_archived`이면 **권한 판정 이전에** role 무관 404(8.10,
    INV-7). admin도 예외 없음.
- 결론: L5는 (a) deleted 전이(s10 완전삭제/보관 만료)를 **실제로 유발**한 뒤 s12 스윕을 **실제로 실행**해 8.6을
  관찰하고, (b) s09 저장으로 참조를 소멸시킨 뒤 스윕을 실제로 실행해 8.7과 붙여넣기 보호를 관찰한다. 두 경우 모두
  파일시스템·DB 부수효과를 직접 관찰한다(mock 금지).

### 3) 하네스 재사용 전략 (L4 확장)

- `s11-integration-check-L4/design.md`: `tests/integration_L4/conftest.py`가 L3 하네스(마이그레이션·부팅·admin
  시드·세션 유지 `TestClient`·워크스페이스/멤버/role 세션·문서 트리·엔진 세션)를 재사용하고, **두 editor(A·B)**·
  잠금/휴지통 시나리오·`now` 주입 보관 스윕 호출(`RetentionSweepService.sweep_expired_bundles`/`run_sweep`)
  픽스처를 추가했다.
- L5는 이 L4 하네스를 재사용하고, **첨부 전용 픽스처만 신규 추가**한다:
  - multipart 첨부 업로드 헬퍼(`POST /documents/{id}/attachments`, image/file),
  - 첨부 바이너리 조회 헬퍼(`GET /attachments/{id}`),
  - 이미지 참조를 담은 본문으로 저장(`POST /documents/{id}/save`)해 현재 버전 참조를 만들거나 제거하는 시나리오
    헬퍼(s09 저장은 L4 helpers 재사용),
  - 부팅 앱과 동일 DB 세션으로 `ArchivalSweepService`(또는 `run_archival_sweep`)를 **`now` 주입**으로 호출하는
    아카이브 스윕 접근 픽스처,
  - 저장 파일·보관 파일의 존재를 파일시스템에서 관찰하는 헬퍼(`file_storage_root`/`attachment_archive_root` 기준).
- 완전삭제(deleted 전이)와 보관 만료 스윕은 L4 helpers(휴지통 완전삭제·`now` 주입 retention sweep)를 재사용해
  유발한다. 중복 신설 금지.

### 4) mock 금지 · 실 결합 원칙

- roadmap §게이트: "체크포인트는 오직 누적 upstream에 대한 계약·경계 정합 검증과 그 테스트(integration/e2e, mock
  없음)만 범위". `ArchivalSweepService`·`RetentionSweepService`·엔진 직접 호출은 실제 s12·s10·s07 코드 실행이므로
  허용된다(가짜 구현이 아님). 파일 저장·보관 이동은 실제 로컬 파일시스템에서 관찰한다.
- DB 미가용·부팅 실패·환경 미충족은 **스킵이 아니라 실패**로 처리(미검증이 게이트 통과로 오인되지 않도록).

## 아키텍처 패턴 평가

- **선택**: 테스트 전용 검증 계층(외부 관찰자 + s12 조정 서비스/스토리지·s10 스윕·s07 엔진 재사용 소비자). L4
  하네스를 재사용·확장.
- **대안 기각**:
  - *s12 단위 테스트로 대체*: 개별 spec 자체 테스트는 각 spec 소유. 체크포인트는 **결합·경계**(계층 간 트리거)만
    본다 — 단위 테스트로는 8.6/8.7의 하위 계층 결합을 관찰할 수 없다. 기각.
  - *조정 스윕을 mock으로 대체*: 사용자 지시·로드맵 규칙으로 명시 금지. 관측 기반 조정의 실제 DB/파일시스템
    부수효과가 검증 핵심이므로 mock은 검증을 무의미하게 만든다. 기각.
  - *새 하네스 신설*: L4 하네스와 중복. roadmap "중복 신설 금지". 기각 — 재사용·확장.

## 설계 결정 요약 (Synthesis)

- **Build vs Adopt**: 신규 애플리케이션 코드 0. `tests/integration_L5/`만 신설, 나머지는 L4 하네스·s12 공개 표면·
  s01 계약 요소를 **adopt**.
- **일반화**: 첨부 업로드/서빙/스윕 호출/파일시스템 관찰 래퍼를 `helpers.py`에 단일화하고 각 스위트가 재사용.
- **단순화**: 스케줄러 job 대기·실시간 sleep을 쓰지 않고 `run_archival_sweep`/`ArchivalSweepService.sweep(db, now)`를
  `now` 주입으로 직접 호출해 결정성 확보(L4의 retention sweep 패턴과 동일).

## 리스크와 완화

- **파일시스템 상태 오염**(테스트 간 저장/보관 경로 충돌): 테스트별 고유 워크스페이스·문서·첨부와 정리 픽스처로
  격리. `file_storage_root`/`attachment_archive_root`는 s01 `Settings`(테스트 설정) 재사용.
- **스윕 비결정성**(스케줄러 실기동): 테스트에서 스케줄러 job을 대기하지 않고 스윕을 직접 호출(`now` 주입).
- **deleted 유발 경로 혼동**(완전삭제 vs 보관 만료): 두 경로 모두 `document.status='deleted'`로 수렴하므로 8.6은
  두 경로 각각에서 관찰(REQ-4.1·4.2). retention 만료 경로는 L4 `now` 주입 스윕 헬퍼로 유발.
- **붙여넣기 보호 경계**(created_at 비교): `attachment.created_at`과 `current_version.created_at`의 상대 순서로
  판정되므로, 시나리오에서 붙여넣기→저장 순서를 명시적으로 구성해 경계(직전/직후)를 결정적으로 검증.

## 참조

- `docs/projects.md` §2.6, §3 REQ-8, §4.4, §5 INV-1·2·3·4·6·7
- `s01-contract-foundation/design.md`(§Physical Data Model `attachment` · §API Catalog 32~33 · §Errors ·
  §Invariants Catalog · §Settings · §Common/Permissions)
- `s12-attachment/design.md`(§AttachmentService · §AttachmentStorage · §ArchivalSweepService · §ReferenceScanner ·
  §ArchivalScheduler · Settings additive)
- `s11-integration-check-L4/design.md`(재사용·확장할 하네스 패턴)
- `.kiro/steering/roadmap.md`(게이트 G-1 · 재검증 트리거 · Shared seams to watch)
