# Research & Design Decisions — s10-trash

## Summary
- **Feature**: `s10-trash`
- **Discovery Scope**: Extension (s07 `DocumentStateEngine` 위에 얹는 얇은 API/UX + 배치 레이어)
- **Key Findings**:
  - 휴지통 상태 전이(복구·완전삭제·묶음 식별)는 이미 s07 엔진에 단일 구현으로 존재한다. s10은 규칙을
    **재구현하지 않고** primitive(`identify_bundles`·`get_bundle`·`restore_bundle`·`purge_bundle`)를 호출한다.
  - 묶음 = **루트 문서 id**(s07 규약). 카탈로그의 `{bundleId}`는 곧 묶음 루트 문서 id이므로, 권한 게이팅용
    workspace_id는 문서 id → workspace_id 매핑으로 확정된다(s07가 이미 제공하는 조회를 재사용).
  - 보관 만료는 각 묶음 `trashed_at` + 워크스페이스 `trash_retention_days`(s01 Settings `default_trash_retention_days`
    기본 30, s05가 워크스페이스별로 설정)로 **묶음별 독립** 산정(INV-12). 새 스키마·마이그레이션 불필요.

## Research Log

### 상태 전이 규칙의 소유권 경계 (s07 ↔ s10)
- **Context**: s10이 복구/완전삭제/목록을 제공하려면 상태 전이가 필요하나, roadmap의 "shared seam"은
  document-core status/bundle 엔진 ↔ trash를 재검증 집중 대상으로 지목한다(INV-10~12, 6.5 복구 위치).
- **Sources Consulted**: `.kiro/specs/s07-document-core/design.md`(§DocumentStateEngine, Data Contracts),
  `docs/projects.md` §4.2·§5 INV-10·11·12, `.kiro/steering/structure.md`(코드 조직 원칙).
- **Findings**:
  - s07 `DocumentStateEngine`가 `trash_document`·`active_descendants`·`identify_bundles`·`get_bundle`·
    `restore_bundle`·`purge_bundle`와 `Bundle` DTO(`root_document_id`·`trashed_at`·`members`)를 안정 계약으로 노출.
  - s07 design은 "s10은 이 primitive를 호출만 하고 규칙을 재구현하지 않는다"를 명시(엔진 Boundary).
- **Implications**: s10 서비스는 상태 전이를 **직접 쓰지 않고** 엔진에 위임한다. 복구 위치(6.5)·순서 복원(6.7)·
  비흡수(6.2.1)·완전삭제 원자성(8.x)은 전부 엔진 책임. s10은 목록 표현·권한 게이트·보관 배치 스케줄만 소유.

### 완전삭제 확인 절차(6.10)의 표현 위치
- **Context**: REQ-6.10 "완전 삭제는 되돌릴 수 없으므로 UI는 확인 절차를 제공한다." 확인을 API에 강제할지 UX에 둘지 결정.
- **Sources Consulted**: `s01` 카탈로그 행 31(`DELETE /trash/{bundleId}`, Request 없음), `docs/projects.md` 6.10.
- **Findings**: 6.10은 **UI 확인 절차**를 요구하며, s01 계약상 완전삭제 엔드포인트는 요청 본문이 없다. 확인은
  프론트엔드(사용자 확인 다이얼로그) 책임이고, 백엔드는 되돌릴 수 없는 조작임을 문서화한다.
- **Implications**: API 계약을 s01 행 31대로 유지(본문 없음). 확인 절차는 프론트엔드 UX 계약으로 명시하고,
  백엔드는 멱등하지 않은 파괴적 조작임을 라우터 문서·OpenAPI 설명에 표기. 계약 변경(추가 확인 토큰) 없이 진행.

### 보관 만료 자동 영구삭제 실행 메커니즘
- **Context**: 묶음별 독립 타이머로 만료 묶음을 주기적으로 자동 deleted 전환해야 한다(6.8, INV-12). FastAPI +
  MySQL(uv) 스택에서 스케줄 실행 수단을 선택한다.
- **Sources Consulted**: `.kiro/steering/tech.md`(FastAPI·MySQL·uv, 별도 인프라 없음), `s01` Settings(단일 설정),
  `docs/projects.md` §6(보관 폴더 자동 정리는 범위 밖 — 단, 문서 보관 타이머는 6.8로 범위 내).
- **Findings / 평가**: 아래 "Architecture Pattern Evaluation" 표 참조. 핵심 제약은 (1) 스윕 **핵심 로직을 스케줄러와
  분리**해 단위/통합 테스트로 직접 호출 가능해야 하고, (2) 새 중량 인프라(Redis·Celery broker)를 도입하지 않으며,
  (3) 멱등해야 한다(반복 실행·다중 워커 안전).
- **Implications**: 스윕 로직은 순수 서비스(`RetentionSweepService.sweep_expired_bundles(db, now)`)로 구현하고,
  주기 실행은 **APScheduler `BackgroundScheduler`**를 FastAPI lifespan에서 기동하는 얇은 어댑터로 분리한다.
  동일 스윕을 **독립 실행 엔트리포인트**로도 노출해 테스트·수동/외부 cron 실행이 가능하게 한다.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| APScheduler BackgroundScheduler (선택) | 인프로세스 백그라운드 스레드 스케줄러를 lifespan에서 기동, 주기적으로 스윕 서비스 호출 | 추가 브로커 불필요, 앱과 함께 기동, 스윕 로직과 스케줄러 분리 용이, 스레드 기반이라 sync SQLAlchemy와 호환 | 다중 워커 시 워커마다 스케줄러 → 중복 스윕(멱등으로 완화). 프로세스 재시작 시 미실행분은 다음 주기에 처리 | 소규모 폐쇄형·단일 워커 기본 가정에 적합. `trash_sweep_interval_seconds<=0`로 비활성화 후 외부 cron 사용 가능 |
| asyncio 루프 태스크(lifespan) | 의존성 없이 `asyncio.create_task`로 sleep 루프 | 신규 의존성 0 | sync 세션을 async 루프에서 다루는 정합·취소 처리 수작업, cron식 스케줄 부재 | 최소 의존성이 최우선이면 대안. 스케줄 표현력 낮음 |
| 외부 OS cron + `uv run` 엔트리포인트만 | 앱 밖에서 주기 실행 | 앱 프로세스와 완전 분리, 다중 워커 중복 없음 | 배포 환경에 cron 설정 의존(스터디 환경 자동화 저하) | 인프로세스 스케줄러의 **폴백**으로 동일 엔트리포인트 재사용 |
| Celery/APScheduler+Redis 등 브로커 | 분산 작업 큐 | 확장성·재시도 | Redis 등 중량 인프라 도입 — 범위 과다 | 기각(steering 범위 초과) |

## Design Decisions

### Decision: s07 엔진 primitive 소비(상태 전이 무재구현)
- **Context**: 휴지통 복구/완전삭제/목록에 상태 전이가 필요하나 규칙은 s07 소유.
- **Alternatives Considered**:
  1. s10에서 status·trashed_at을 직접 갱신 — 규칙 중복·드리프트 위험, INV-10~12 회귀.
  2. s07 엔진 primitive 호출 — 규칙 단일 구현 유지.
- **Selected Approach**: s10 `TrashService`·`RetentionSweepService`가 `DocumentStateEngine`의
  `identify_bundles`/`get_bundle`/`restore_bundle`/`purge_bundle`를 호출한다. s10은 status/trashed_at을 직접 쓰지 않는다.
- **Rationale**: steering structure.md "묶음/상태 규칙은 document-core 서비스에 단일 구현, trash가 재사용" 준수.
- **Trade-offs**: s07 엔진 계약에 결합(계약 변경 시 s10 재검증). 대신 불변식 일관성 확보.
- **Follow-up**: s11(L4) 체크포인트에서 엔진↔trash 결합·묶음 타이머를 mock 없이 재검증.

### Decision: 묶음 id = 루트 문서 id → 문서 id 기반 권한 게이트
- **Context**: `/trash/{bundleId}/restore`·`DELETE /trash/{bundleId}`의 권한 판정에 workspace_id가 필요.
- **Alternatives Considered**:
  1. bundleId를 별도 식별자로 신설 — s07 규약(루트 문서 id) 위반, 새 매핑 필요.
  2. bundleId = 루트 문서 id로 두고 문서 id → workspace_id 매핑으로 게이트 — s07 규약과 정합.
- **Selected Approach**: `{bundleId}`를 루트 문서 id로 해석하고, 문서 id → workspace_id 조회로
  `require_ws_role(EDITOR)`에 주입한다. workspace_id 조회는 s07 `DocumentRepository.get_workspace_id`를 재사용.
  묶음 루트 유효성(trashed 묶음 루트인지)은 엔진 `get_bundle`/`restore_bundle`/`purge_bundle`가 404로 판정.
- **Rationale**: s07 묶음 식별 규약 준수, doc→ws 매핑 중복 회피(단일 조회 재사용).
- **Trade-offs**: 권한 게이트는 "문서 존재"만 확인하고, "묶음 루트 유효성"은 서비스/엔진 단계에서 404로 표면화(2단계).
- **Follow-up**: 존재하지 않는 문서 id → 게이트 단계 404, 존재하나 묶음 루트 아님 → 엔진 404 경로 테스트.

### Decision: 보관 스윕 로직과 스케줄러 분리 + 인프로세스 스케줄러 채택
- **Context**: 6.8 자동 영구삭제를 묶음별 독립 타이머로 주기 실행하되 테스트 가능해야 한다.
- **Alternatives Considered**: (평가표 참조) asyncio 루프 / 외부 cron / 브로커 큐 / APScheduler.
- **Selected Approach**: 순수 `RetentionSweepService.sweep_expired_bundles(db, now)`(엔진 `identify_bundles`로
  워크스페이스별 묶음 열거 → 각 묶음 `trashed_at + retention_days <= now`면 `purge_bundle`)를 핵심 로직으로 두고,
  APScheduler `BackgroundScheduler`를 lifespan에서 기동하는 얇은 어댑터(`scheduler.py`)가 이를 자기 세션으로
  주기 호출한다. 동일 스윕을 `run_sweep()` 엔트리포인트로도 노출.
- **Rationale**: 테스트에서 `now`를 주입해 만료 경계를 결정적으로 검증. 스케줄러는 교체 가능한 어댑터.
- **Trade-offs**: APScheduler 1개 의존성 추가(`uv add`). 다중 워커 중복은 멱등성(purge는 deleted 종착이라 재적용
  무해)으로 완화, 필요 시 `trash_sweep_interval_seconds<=0`로 인프로세스 스케줄러를 끄고 외부 cron으로 `run_sweep` 실행.
- **Follow-up**: 스윕 멱등성(이미 deleted/복구된 묶음 skip)·`now` 주입 만료 경계·다른 묶음 타이머 불간섭 테스트.

### Decision: 배치 실행 주기 설정을 단일 Settings에 additive 확장
- **Context**: 스케줄 주기 값이 필요하나 모듈별 설정 파일 신설은 steering 금지.
- **Alternatives Considered**:
  1. s10 모듈 로컬 상수/별도 설정 파일 — steering 위반.
  2. `s01` 단일 Settings에 `trash_sweep_interval_seconds`(기본 3600) additive 추가.
- **Selected Approach**: `config.yml` + 공용 `Settings`에 `trash_sweep_interval_seconds`(기본 3600, `<=0`이면
  인프로세스 스케줄러 비활성화)를 additive로 추가. 보관일 기본값은 기존 `default_trash_retention_days`(30) 재사용.
- **Rationale**: tech.md "새 설정 항목은 config.yml + 공용 Settings 스키마 확장" 준수. 기본값이 있는 additive 필드라
  기존 계약 의미를 바꾸지 않음.
- **Trade-offs**: Settings 스키마에 필드 1개 추가(기본값 존재, 비파괴적). s01 Settings 단일 소스를 건드리므로
  s01 소유자와의 조정 지점으로 명시. 새 마이그레이션·새 설정 파일은 없음.
- **Follow-up**: Settings 확장이 기존 부팅·기존 필드 계약을 바꾸지 않음을 부팅/로드 테스트로 확인.

## Risks & Mitigations
- **다중 워커 중복 스윕** — 멱등 스윕(deleted 종착·복구/삭제된 묶음 skip)으로 무해화. 다중 워커 배포 시
  인프로세스 스케줄러 off + 외부 cron 단일 실행 권장(문서화).
- **DATETIME 초 단위 정밀도로 인한 묶음 오병합(이론)** — s07 design Risk에 기록됨. s10은 엔진 식별 결과만
  소비하므로 신규 위험 없음(관측 시 s01 계약 정밀도 승격은 s07/s01 소관).
- **보관일 변경 타이밍** — 워크스페이스 `trash_retention_days`가 스윕 시점 값으로 평가되므로 설정 변경이 이후
  스윕부터 반영됨(예측 가능). 이미 deleted된 묶음은 소급 영향 없음.
- **s07 엔진 계약 변경** — primitive 시그니처·묶음 식별 규약 변경은 s10 재검증 트리거(§Revalidation).

## References
- 상태 엔진 primitive·`Bundle` DTO·묶음 식별 규약: `.kiro/specs/s07-document-core/design.md`.
- 계약 단일 소스(카탈로그 행 29~31·에러 모델·Base Schemas·resolver·Settings·스키마): `.kiro/specs/s01-contract-foundation/design.md`.
- 보관일·retention 설정 소유·`require_ws_role` 실동작: `.kiro/specs/s05-workspace/design.md`.
- 상위 계약 근거: `docs/projects.md` §3 REQ-6.8~6.11, §4.1~4.2, §5 INV-2·3·4·7·10·11·12.
- APScheduler: https://apscheduler.readthedocs.io/ — BackgroundScheduler(스레드 기반) 주기 실행.
