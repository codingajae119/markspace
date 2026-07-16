# Research & Design Decisions — s12-attachment

## Summary
- **Feature**: `s12-attachment`
- **Discovery Scope**: Extension (하위 계층 s07 문서·s09 버전·s10 완전삭제 위에 얹는 첨부 저장·격리·생명주기 레이어)
- **Key Findings**:
  - 첨부 저장·격리·생명주기의 두 핵심 seam(8.6 완전삭제 반응 보관 이동, 8.7 저장 참조 소멸 아카이브)은 각각
    `s10` deleted 전이와 `s09` 버전 저장의 **결과**에 대한 반응이다. 그러나 의존 방향(항상 아래층을 향함)상
    하위 계층은 상위 계층(s12)을 import할 수 없고, `s01`에는 이벤트 버스가 없으며, s07/s09/s10 설계는 이미
    확정(frozen)되어 s12로의 동기 콜백을 노출하지 않는다. 따라서 s12는 **관측 가능한 DB 상태(문서 status·현재
    버전 참조)를 스캔하는 조정(reconciliation) 방식**으로 두 사건에 반응한다. s09/s10 설계가 명시한 "관찰
    (observe)"이 정확히 이 방식이다.
  - 첨부 스키마(`workspace_id`·`document_id`·`file_path`·`kind`·`is_archived`)와 저장 루트 Settings
    (`file_storage_root`)는 `s01`이 이미 소유. 새 마이그레이션 불필요. 보관 폴더 루트·배치 주기·업로드 한도만
    `s01` 단일 Settings에 additive 확장.
  - 보관 이동은 물리 삭제가 아니라 파일 이동 + `is_archived=true`(INV-4). 보관=영구삭제로 간주되어 admin 포함
    조회 불가·복원 없음(INV-7). 보관 폴더는 단조 증가 수용(8.11, 자동 정리는 steering 범위 밖).

## Research Log

### 두 생명주기 seam(8.6·8.7)의 반응 메커니즘 — 관측 기반 조정 vs 동기 콜백
- **Context**: roadmap "Shared seams to watch"가 (a) lock/version ↔ attachment 참조 소멸 아카이브(8.7), (b) trash
  완전삭제 ↔ attachment 보관 이동(8.6)을 `s13(L5)` 재검증 집중 대상으로 지목한다. 두 반응을 s12가 소유하되
  하위 계층을 침범하지 않아야 한다.
- **Sources Consulted**: `.kiro/specs/s07-document-core/design.md`(엔진 `purge_bundle`는 상태 전이만·첨부 아카이브
  미소유 8.5), `.kiro/specs/s09-lock-version/design.md`(저장=버전 생성 이벤트, "s12가 관찰해 8.7 판정"),
  `.kiro/specs/s10-trash/design.md`("s12가 deleted 전이를 관찰해 8.6 수행", s10은 deleted 전이만 트리거),
  `.kiro/specs/s01-contract-foundation/design.md`(이벤트 버스 없음, 의존 방향 강제), `.kiro/steering/structure.md`.
- **Findings**:
  - s07/s10 엔진 `purge_bundle`은 "상태 전이만 수행하고 첨부 아카이브(s12)는 소유하지 않는다"(8.5)를 명시.
    s09 저장은 버전 생성만 소유. 세 spec 모두 s12를 import하지 않으며 s12로의 콜백/이벤트를 노출하지 않는다.
  - `s01`은 세션/에러/권한 인프라만 제공하고 도메인 이벤트 버스를 제공하지 않는다. 상위 계층으로의 통지 계약이
    존재하지 않는다.
- **Implications**: s12가 두 사건에 동기 콜백으로 반응하려면 하위 계층이 s12를 호출해야 하나 이는 의존 방향
  위반이며 frozen 계약 변경을 요구한다. 대신 s12는 하위 계층이 남긴 **관측 가능한 결과**(문서
  `status='deleted'`; `current_version_id`→본문 참조)를 스캔하는 조정 서비스로 반응한다. 이는 s09/s10 설계가
  쓴 "관찰"과 정합하고, `s10`이 이미 검증한 스윕/스케줄러 분리 패턴을 재사용한다. 결과적 일관성(eventual)이나
  하위 계약 무변경·의존 방향 준수·테스트 가능성을 확보한다.

### 8.7 참조 소멸 판정 — 현재 버전 참조 관측과 붙여넣기 보호
- **Context**: "저장으로 과거 버전만 참조하게 된 이미지"를 아카이브해야 한다(8.7). 참조 카운팅 대상과, 편집 중
  붙여넣었으나 아직 저장 안 된 이미지의 오아카이브 방지가 쟁점.
- **Sources Consulted**: 브리프 8.1·8.7, `s09` design(저장 시 `current_version_id` 갱신·버전 append), `s07`
  design(`load_current_content`로 현재 버전 본문 로드), 카탈로그 행 32~33.
- **Findings / 결정**:
  - 참조 기준은 **현재 버전 본문**뿐이다. 과거 버전이 텍스트로 참조를 담고 있어도 현재 버전이 참조하지 않으면
    "참조 소멸"로 본다(8.7 문언). 판정은 현재 버전 본문에 `/attachments/{id}` 토큰 존재 여부(`ReferenceScanner`).
  - **붙여넣기 보호**: 붙여넣기(행 32 image)는 첨부를 즉시 생성하지만 참조는 클라이언트 편집 버퍼에만 있고
    저장 전까지 어떤 버전에도 없다. 스윕이 저장 전에 돌면 "현재 버전 미참조"로 오판해 방금 붙여넣은 이미지를
    아카이브할 수 있다. 이를 막기 위해 **`attachment.created_at <= current_version.created_at`인 이미지만** 참조
    소멸 후보로 삼는다. 즉 첨부보다 나중에 저장된 현재 버전이 그 첨부를 떨어뜨린 경우에만 아카이브한다.
  - 대상은 이미지 종류에 한정(8.7 문언 "이미지"). 일반 파일 첨부의 보관 이동은 완전삭제 반응(8.6)으로만 처리.
- **Implications**: 붙여넣기→저장(참조 포함) 흐름에서 이미지는 유지되고, 이후 저장에서 제거되면 그때 아카이브.
  붙여넣기→미저장 이탈 이미지는 8.7로 아카이브되지 않으며(created_at > 현재 버전), 문서가 완전삭제되면 8.6으로
  정리된다. 판정이 결정적이라 단위·통합 테스트로 경계를 검증 가능.

### 첨부 참조 URL 규약
- **Context**: 붙여넣기 이미지가 문서에서 참조되려면 안정 참조가 필요하고(8.1), 8.7 판정·s07 렌더·s14 링크
  접근이 같은 규약을 공유해야 한다.
- **Sources Consulted**: 카탈로그 행 33(`GET /attachments/{id}`), 행 37(s14 공개 링크 첨부), `s07` 렌더 규약.
- **Findings**: 서빙 경로와 동일한 `/attachments/{id}`를 문서 본문 참조 규약으로 채택한다. 업로드 응답 `url`이
  이 값을 반환하고, 편집기는 이를 markdown에 삽입, 저장 시 현재 버전 본문에 남는다. 8.7 스캔·s07 렌더는 이 토큰을
  공유한다.
- **Implications**: 참조 URL 규약 변경은 8.7·s07 렌더·s14 접근에 동시 영향 → `s13` 재검증 트리거로 명시. 스캐너는
  id 경계(`/attachments/12` ≠ `/attachments/123`)를 정확히 구분해야 한다.

### 보관 비노출·영구성(8.9·8.10, INV-7)의 표현
- **Context**: 보관=영구삭제 간주, admin 포함 조회 불가, 복원 없음.
- **Sources Consulted**: 브리프 8.9·8.10, `s01` INV-7(deleted 문서·보관 파일 복원 경로 없음), 카탈로그 행 33.
- **Findings**: `GET /attachments/{id}`에서 `is_archived=true`이면 **권한 판정 이전에 role 무관 404**로 차단한다.
  admin bypass는 권한 검사에만 적용되므로, 보관 차단을 권한 검사보다 앞에 둬 admin에게도 노출하지 않는다.
  410/403이 아닌 404로 두어 존재 여부를 드러내지 않는다. 애플리케이션에 보관→active 복원 API를 두지 않는다.
- **Implications**: 서비스가 보관 상태를 최우선 게이트로 검사. 어댑터/권한 resolver는 관여하지 않는다(보관은
  권한 문제가 아니라 존재-비노출 문제).

### 파일 저장·보관 디렉터리 격리와 물리 삭제 없음(INV-4·6)
- **Context**: 저장·보관 모두 WS 격리(8.3·8.8)하고 물리 삭제 없이 보관 이동만 수행(INV-4).
- **Sources Consulted**: `.kiro/steering/tech.md`(파일 저장 루트는 config.yml), `s01` Settings `file_storage_root`,
  INV-4·6.
- **Findings / 결정**: 저장은 `{file_storage_root}/{workspace_id}/...`, 보관은 `{attachment_archive_root}/
  {workspace_id}/...`로 WS별 분리. 보관 이동은 파일 rename/move + `is_archived=true` + `file_path` 갱신이며 파일을
  삭제하지 않는다(INV-4). 저장 파일명은 서버 생성(경로 트래버설 방지), 원본명은 DB `original_name`에만 보존.
  attachment.workspace_id는 클라이언트 입력이 아닌 대상 문서에서 확정(위조 방지, INV-6).
- **Implications**: `AttachmentStorage`가 저장/보관 경로 규약·이동을 단일 소유. 보관 폴더 자동 정리는 없음(8.11
  단조 증가 수용, steering 범위 밖).

### 보관 배치 실행 메커니즘 — s10 스윕/스케줄러 패턴 재사용
- **Context**: 두 조정(8.6·8.7)을 주기적으로 관측·수행해야 한다. FastAPI + MySQL(uv) 스택에서 실행 수단 선택.
- **Sources Consulted**: `.kiro/specs/s10-trash/design.md`·`research.md`(APScheduler BackgroundScheduler +
  스윕/스케줄러 분리 + 독립 엔트리포인트), `.kiro/steering/tech.md`.
- **Findings / 평가**: 아래 "Architecture Pattern Evaluation" 참조. 핵심 제약은 (1) 조정 **핵심 로직을 스케줄러와
  분리**해 테스트에서 직접 호출·`now` 주입 가능, (2) 새 중량 인프라 미도입, (3) 멱등(스코프가 항상
  `is_archived=false`만 대상). `s10`이 이미 APScheduler를 `uv add`했으므로 **신규 의존성 없이 재사용**한다.
- **Implications**: 조정 로직은 순수 `ArchivalSweepService.sweep(db, now)`, 주기 실행은 lifespan에서 기동하는 얇은
  `ArchivalScheduler`로 분리하고 `run_archival_sweep()` 엔트리포인트도 노출(테스트·수동/외부 cron). `s10`과 동일
  패턴이라 `s13` 검증·운영 일관성 확보.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 관측 기반 조정 스윕(선택) | 문서 status·현재 버전 참조를 스캔해 8.6·8.7 판정, 스윕으로 주기 실행 | 하위 계층 무변경·의존 방향 준수, frozen 계약 무침범, 멱등·테스트 용이, s10 패턴 재사용 | 결과적 일관성(스윕 주기 만큼 지연). 대량 첨부 시 스캔 비용(인덱스 `(workspace_id,is_archived)`로 완화) | 하위 계층이 s12를 모르는 제약에서 유일하게 건전한 결합. s09/s10 "관찰" 문언과 정합 |
| 하위 계층 동기 콜백 | s09 저장·s10 완전삭제가 s12 아카이브를 직접 호출 | 즉시성(동기) | **의존 방향 위반**(하위→상위 import), frozen s07/s09/s10 계약 변경 필요, 순환 결합 | 기각(아키텍처·계약 위반) |
| s01 이벤트 버스 도입 | s01에 도메인 이벤트 발행/구독 추가, s12 구독 | 즉시성·역방향 결합 회피 | s01 계약 확장 → **모든 체크포인트 재검증**, 범위 과다(현 스택 미보유) | 기각(범위 초과, s01 소유 변경) |
| 외부 OS cron + 엔트리포인트만 | 앱 밖에서 `run_archival_sweep` 주기 실행 | 앱 프로세스 분리, 다중 워커 중복 없음 | 배포 cron 의존(스터디 환경 자동화 저하) | 인프로세스 스케줄러의 폴백(`attachment_sweep_interval_seconds<=0`)으로 동일 엔트리포인트 재사용 |

## Design Decisions

### Decision: 두 seam(8.6·8.7)을 관측 기반 조정으로 구현(동기 콜백·이벤트 버스 회피)
- **Context**: s12가 완전삭제·저장 사건에 반응해 첨부를 보관 이동해야 하나 하위 계층은 s12를 import할 수 없다.
- **Alternatives Considered**: (평가표 참조) 동기 콜백 / s01 이벤트 버스 / 관측 조정.
- **Selected Approach**: `ArchivalSweepService`가 `document.status='deleted'`(8.6)와 현재 버전 본문 참조(8.7)를
  스캔해 판정하고, `AttachmentStorage.move_to_archive` + `AttachmentRepository.mark_archived`로 보관 이동한다.
  주기 실행은 lifespan 스케줄러 + `run_archival_sweep` 엔트리포인트.
- **Rationale**: 의존 방향(항상 아래층) 준수, frozen s07/s09/s10 계약 무변경, s09/s10 설계의 "관찰" 문언과 정합,
  s10 스윕 패턴 재사용으로 일관성·테스트 용이.
- **Trade-offs**: 결과적 일관성(스윕 주기 지연). 멱등 스코프(`is_archived=false`)로 반복 안전. 즉시성이 필요하면
  주기를 짧게 설정하거나 저장·삭제 흐름 밖에서 엔트리포인트를 호출한다.
- **Follow-up**: `s13(L5)` 체크포인트에서 완전삭제↔보관 이동·저장↔참조 소멸을 mock 없이 재검증.

### Decision: 8.7 참조 소멸 판정에 붙여넣기 보호 가드(created_at 비교)
- **Context**: 붙여넣기 이미지는 저장 전까지 어떤 버전에도 참조가 없어 스윕이 오아카이브할 수 있다.
- **Alternatives Considered**:
  1. 현재 버전 미참조면 무조건 아카이브 — 방금 붙여넣은 미저장 이미지 오아카이브.
  2. `attachment.created_at <= current_version.created_at`인 이미지만 후보 — 저장이 그 이미지를 떨어뜨린 경우로 한정.
- **Selected Approach**: 대안 2. 첨부보다 나중에 생성된 현재 버전이 미참조일 때만 아카이브한다.
- **Rationale**: "저장으로 과거 버전만 참조하게 된"(8.7)의 정확한 해석 — 저장이 참조를 떨어뜨린 경우로 한정.
- **Trade-offs**: 붙여넣고 저장하지 않은 이미지는 8.7로 정리되지 않으나(문서 완전삭제 시 8.6으로 정리), 편집 중
  오아카이브를 확실히 방지한다.
- **Follow-up**: 붙여넣기→저장(유지)→재저장(제거→아카이브)·붙여넣기 후 미저장(유지) 경계 테스트.

### Decision: 첨부 참조 URL 규약 = 서빙 경로 `/attachments/{id}`
- **Context**: 붙여넣기 참조(8.1)·8.7 판정·s07 렌더·s14 링크 접근이 같은 규약을 공유해야 한다.
- **Selected Approach**: 서빙 경로와 동일한 `/attachments/{id}`를 문서 본문 참조 규약으로 채택하고 업로드 응답
  `url`로 반환한다.
- **Rationale**: 단일 규약으로 저장·참조·렌더·링크 접근을 일치. 별도 참조 식별자 신설 회피.
- **Trade-offs**: 규약 변경이 다수 소비자에 영향 → 재검증 트리거로 명시. 스캐너의 id 경계 정확성 필요.
- **Follow-up**: `ReferenceScanner` 경계 오탐 테스트, s14 소비 정합 확인(`s15` e2e).

### Decision: 보관 비노출을 권한 판정 이전 role 무관 404로 처리(INV-7)
- **Context**: 보관=영구삭제 간주, admin 포함 조회 불가(8.9·8.10).
- **Selected Approach**: `serve_attachment`에서 `is_archived=true`이면 권한 검사 전에 404를 반환한다. admin bypass는
  권한 검사에만 적용되므로 보관 차단이 그보다 앞서 admin에게도 노출되지 않는다.
- **Rationale**: 보관은 권한 문제가 아니라 존재-비노출 문제. 404로 존재 여부도 드러내지 않는다.
- **Trade-offs**: 어댑터/resolver는 보관을 알 필요 없음(관심사 분리). 복원 API 부재로 되돌릴 수 없음(INV-7 의도).
- **Follow-up**: 보관 첨부 조회가 admin 포함 404임을 통합 테스트로 확인.

### Decision: 보관 폴더 루트·배치 주기·업로드 한도를 단일 Settings에 additive 확장
- **Context**: 저장 루트(`file_storage_root`)는 s01 소유이나 보관 루트·배치 주기·크기 한도가 추가로 필요.
- **Selected Approach**: `config.yml` + 공용 `Settings`에 `attachment_archive_root`(str)·
  `attachment_sweep_interval_seconds`(int, 기본 3600, `<=0`이면 인프로세스 스케줄러 비활성)·`attachment_max_bytes`
  (int, 기본값) additive 추가. 저장 루트는 기존 `file_storage_root` 재사용.
- **Rationale**: tech.md "새 설정 항목은 config.yml + 공용 Settings 스키마 확장" 준수. 기본값 있는 additive라 기존
  계약 의미 불변. 모듈별 설정 파일 신설 금지.
- **Trade-offs**: s01 Settings 단일 소스를 건드리므로 s01 소유자와의 조정 지점으로 명시. 새 마이그레이션 없음.
- **Follow-up**: Settings 확장이 기존 부팅·필드 계약을 바꾸지 않음을 부팅/로드 테스트로 확인.

## Risks & Mitigations
- **결과적 일관성 지연** — 스윕 주기만큼 보관 이동이 지연된다. 멱등·안전(보관은 종착)하며 주기를 짧게 하거나
  엔트리포인트 호출로 조기 실행 가능. `s13`에서 스윕 실행 후 상태를 검증(즉시 검증은 엔트리포인트 직접 호출).
- **다중 워커 중복 스윕** — 멱등 스코프(`is_archived=false`만 대상, 보관은 종착)로 무해화. 다중 워커 배포 시
  인프로세스 스케줄러 off + 외부 cron 단일 실행 권장(문서화, s10과 동일).
- **참조 스캔 오탐(id 경계)** — `/attachments/12`가 `/attachments/123`을 매칭하지 않도록 스캐너가 경계를 구분.
  테스트로 고정.
- **대량 첨부 스캔 비용** — `attachment(workspace_id, is_archived)`·`(document_id)` 인덱스로 스코프 축소. 소규모
  폐쇄형 가정에 적합. 필요 시 WS별 배치로 분할(계약 불변).
- **하위 계층 계약 변경** — s07 문서→WS/현재 버전 로드, s09 `current_version_id` 의미, s10 deleted 전이 규약 변경은
  해당 spec이 상위 트리거이며 s12도 `s13` 재검증 대상(§Revalidation Triggers).

## References
- 계약 단일 소스(attachment·document·document_version·카탈로그 행 32~33·에러·Base Schemas·resolver·
  `file_storage_root`·INV-4·6·7): `.kiro/specs/s01-contract-foundation/design.md`.
- 문서→WS 어댑터·`load_current_content`·문서 status: `.kiro/specs/s07-document-core/design.md`.
- 저장=버전 생성·`current_version_id` 갱신(8.7 관측 근거): `.kiro/specs/s09-lock-version/design.md`.
- 완전삭제 deleted 전이(8.6 관측 근거)·스윕/스케줄러 분리·APScheduler 도입: `.kiro/specs/s10-trash/design.md`·`research.md`.
- 상위 계약 근거: `docs/projects.md` §2.6 attachment, §3 REQ-8, §4.4 보관 이동, §5 INV-4·6·7.
- APScheduler: https://apscheduler.readthedocs.io/ — BackgroundScheduler(스레드 기반) 주기 실행(s10이 도입).
