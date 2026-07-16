# Research / Discovery Log — s15-integration-check-L6

## Feature Classification
- **유형**: Extension(Integration-focused) — 최종 통합 검증 체크포인트. 신규 도메인 코드 없음. 기존 부팅 앱·조정
  서비스·스윕·엔진·마이그레이션 DB·파일시스템과 하위 통합 하네스(L5/L4/L3/L2/L1)를 결합·관찰하는 테스트 계층만 추가.
- **Discovery 범위**: light(integration points·existing patterns·compatibility 중심). 신규 아키텍처 탐색 불필요.

## Key Decisions

### D1. 대조 기준은 항상 s01 단일 소스
- **결정**: 계약 정합 대조 기준을 개별 spec(s02~s14) design이 아니라 `s01-contract-foundation` 단일 소스(share_link
  스키마·API 카탈로그 행 34~37 및 전체 1~37·에러 모델·Settings 스키마·resolver·INV-1~12)로 고정.
- **근거**: roadmap §게이트 규칙 "검증 기준은 항상 s01 단일 소스". 개별 design N개 상호 대조는 드리프트 추적 불가.
- **기각 대안**: s14 design을 기준으로 삼기 → s14는 검증 대상이지 기준이 아님(순환 검증). 기각.

### D2. L5 하네스 재사용·확장(중복 신설 금지)
- **결정**: `tests/integration_L6/`는 `s13` `integration_L5` 하네스(및 그것이 재사용하는 L4/L3/L2/L1)를 재사용하고,
  공유 발급/토글·공개 렌더/공개 파일(비인증)·무효화 스윕·게이트 토글·share_link 관찰 픽스처만 신규 추가.
- **근거**: roadmap "L5 하네스는 재사용", steering 단일화 원칙. 마이그레이션·부팅·admin 시드·세션·문서 트리·잠금·휴지통·
  복구·retention·아카이브·첨부·파일시스템 관찰이 이미 L5까지 존재.
- **기각 대안**: L6 전용 하네스 신설 → 중복·드리프트. 기각.

### D3. 무효화는 관측 기반 직접 호출 + 실시간 게이트 이중 관찰
- **결정**: 무효화(INV-8)를 (1) 공개 접근 시점 실시간 게이트(즉시 404)와 (2) 관측 기반 조정 스윕(`run_invalidation_sweep`
  직접 호출로 retire=토큰 교체) 두 축으로 관찰. 문서 status·게이트 상태를 실제로 만든 뒤 스윕을 호출(임의 DB 조작 금지).
- **근거**: s14 design의 이중 구조(while-invalid 보장은 스윕 주기 무관). L5의 `now` 주입 아카이브 스윕과 달리, 무효화는
  관측 기반이므로 시간 경계가 아니라 문서 status·게이트 상태가 트리거. 따라서 상태를 실제로 만든 뒤 스윕 호출.
- **기각 대안**: 스케줄러 job 실기동 대기 → 비결정적. 직접 호출로 결정적 관찰. 기각.

### D4. 공개 경로는 비인증 클라이언트로 관찰
- **결정**: `GET /public/{token}`·`GET /public/{token}/attachments/{aid}`(행 36~37)는 인증 우회이므로 별도 익명
  `TestClient`로 접근하고, 발급/토글(행 34~35)은 인증 세션 클라이언트로 접근. 두 클라이언트 쿠키 독립 관리.
- **근거**: s14 design — 공개 경로는 토큰·게이트·문서 status·WS 격리로만 접근 제한(인증 게이트 없음).

### D5. 전 계층 불변식 + 관통 여정을 별도 스위트로 분리
- **결정**: INV-1~12 회귀(`FullStackInvariantSuite`)와 대표 관통 e2e 여정(`EndToEndJourneySuite`)을 별도 스위트로 분리.
- **근거**: 전자는 각 불변식을 축으로 조립 시스템을 점검, 후자는 하나의 사용자 흐름으로 전 계층 결합을 관통. 관심사 분리로
  실패 지점 국소화. brief의 "대표 e2e 흐름"과 "전 계층 회귀 재확인"이 각각 대응.

## Integration Points (관찰·호출 대상, 실제 구현)
- `s14`: `ShareLinkService.issue_link/toggle_link`, `PublicShareService.render_public_document/serve_public_attachment`,
  `ShareInvalidationSweep.invalidate_by_observation`, `run_invalidation_sweep`, `ShareInvalidationScheduler`.
- `s10`: `DELETE /documents/{id}`(trashed), `DELETE /trash/{bundleId}`(deleted), `POST /trash/{bundleId}/restore`(복구),
  `RetentionSweepService`(보관 만료).
- `s07`: `DocumentStateEngine.active_descendants`, 복구 위치 규칙, `POST /documents/{id}/move`(순환 거부, INV-5).
- `s05`: 워크스페이스 `is_shareable` 게이트 설정(owner/admin).
- `s12`: `AttachmentService.serve_attachment`(보관 404), `ArchivalSweepService`(첨부 보관 이동).
- `s09`: 편집 잠금(INV-9)·저장 시 버전 생성.
- `s01`: `create_app`·마이그레이션·`Settings`(additive `share_token_bytes`·`share_invalidation_sweep_interval_seconds`)·
  모델·resolver.

## Compatibility / Settings additive
- s14가 `s01` `Settings`에 `share_token_bytes`(기본 32)·`share_invalidation_sweep_interval_seconds`(기본 3600) 추가.
  기존 필드(`file_storage_root`·`attachment_archive_root`·`attachment_sweep_interval_seconds`·
  `default_trash_retention_days`·`trash_sweep_interval_seconds`·`db_*`·`session_*`) 보존·부팅 무회귀를 실제 부팅으로 확인.
- 새 DB 마이그레이션 부재(s14는 s01 share_link 스키마만 사용) 확인.

## Risks & Mitigations
- **토큰 교체 관찰 비결정성** → `run_invalidation_sweep` 직접 호출 후 DB에서 `token`·`is_enabled` 값 비교(결정적).
- **인증/공개 클라이언트 쿠키 혼선** → 클라이언트 분리(인증 세션 vs 익명).
- **환경 미충족(DB·파일시스템·부팅)** → 스킵이 아니라 실패 처리(미검증 게이트 오통과 방지).
- **묶음·복구 위치 규칙 결합 비결정성** → 삭제·복구·완전삭제를 실제 라우트로 수행하고 `trashed_at`·status를 DB 관찰.

## Out of Scope (재확인)
- feature 구현 일체(s01~s14 소유), 검증 실패 코드 수정(원인 spec), `docs/projects.md` §6 범위 밖 기능(검색·rollback·
  CRDT·자동 정리 등). L6은 downstream이 없는 최종 체크포인트.
