# Implementation Plan — s15-integration-check-L6

> **통합 검증 체크포인트(L6, 최종 = 전체 시스템 e2e)** — feature 로직을 구현하지 않는다. 산출물은
> `backend/tests/integration_L6/`의 integration/e2e 테스트 자산과 게이트(G-1 규칙, L6 종단 = 전체 시스템 GO) 판정뿐이다.
> 모든 명령은 `backend/`에서 `uv run` 기준, 산출물 언어 한국어, 코드 식별자는 영어. **mock 금지**(실제 `s01`·`s02`·
> `s03`·`s05`·`s07`·`s09`·`s10`·`s12`·`s14` 구현 + 실제 workspace_member·document·document_version·attachment·
> share_link 데이터 + 실제 파일시스템 저장/보관 폴더 + 실제 `ShareInvalidationSweep` + 실제 `DocumentStateEngine`/
> `RetentionSweepService`/`ArchivalSweepService` 결합; 조정 서비스·스윕·엔진 직접 호출은 실제 s14·s10·s07·s12 코드
> 실행이므로 허용). 계약 대조 기준은 개별 spec design이 아니라 **`s01-contract-foundation` 단일 소스**다. 애플리케이션
> 코드(`app/*`)·`config.yml`·마이그레이션·하위 하네스(`tests/integration_L5/*`·`L4`·`L3`·`L2`·`L1`)는 수정하지 않는다 —
> L5 하네스는 **재사용·확장**한다.

- [ ] 1. Foundation: L6 실제 전체 결합 검증 하네스 (L5 재사용·확장)
- [x] 1.1 L6 통합 테스트 하네스 구성 (L5 하네스 재사용 + 공유 발급/토글·공개 렌더/공개 파일·무효화 스윕·게이트 토글·share_link 관찰 픽스처)
  - `tests/integration_L6/conftest.py`에서 `s13` `tests/integration_L5`의 하네스 픽스처(실제 MySQL 8에 `alembic
    upgrade head` 적용·`s01` `create_app()` 부팅·admin 시드·세션 유지 `TestClient` 팩토리·고유 login_id 생성기·
    워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트·문서 트리 생성·부팅 앱과 동일 `SessionLocal`/`get_db`
    세션의 `DocumentStateEngine` 접근·두 editor(A·B) 세션·잠금/저장·휴지통 삭제·복구·`now` 주입 `RetentionSweepService`·
    아카이브 스윕·첨부 업로드/서빙·파일시스템 관찰)를 재사용하고, 부팅 앱이 s02·s03·s05·s07·s09·s10·s12·**s14 공유
    라우터 + 무효화 스케줄러가 조립된 상태**(발급·토글·공개 렌더·링크 경유 파일 라우트 노출, lifespan 무효화 스케줄러
    훅 결합)임을 전제로 한다. 게이트 on 워크스페이스의 active 문서에 editor가 링크를 발급(`POST /documents/{id}/share`)·
    토글(`PATCH /documents/{id}/share`)하고 **비인증 공개 클라이언트**로 `GET /public/{token}`·`GET /public/{token}/
    attachments/{aid}`에 접근하는 공유 시나리오 픽스처, 공유 문서를 `DELETE /documents/{id}`(trashed)·`DELETE
    /trash/{bundleId}`(deleted)·`s05` 게이트 off·`POST /trash/{bundleId}/restore`(복구)로 전이시키는 무효 유발 픽스처
    (L5 헬퍼 재사용), 부팅 앱과 동일 DB 세션으로 `s14` `ShareInvalidationSweep.invalidate_by_observation` 또는
    `run_invalidation_sweep`를 호출하는 무효화 스윕 접근 픽스처(관측 기반, 문서 status·게이트를 실제로 만든 뒤 호출),
    `share_link.token`·`is_enabled`를 DB에서 읽어 retire(토큰 교체+비활성)·재발급(새 토큰)·물리 삭제 부재를 관찰하는
    share_link 관찰 픽스처를 신규 추가
  - mock·stub을 사용하지 않으며(조정 서비스·스윕·엔진 직접 호출은 실제 s14·s10·s07·s12 코드), DB·파일시스템 미가용·
    부팅 실패 시 스킵이 아니라 실패로 처리. 설정은 s01 `Settings` 재사용(additive `share_token_bytes`·
    `share_invalidation_sweep_interval_seconds`·`attachment_*` 포함), 애플리케이션 코드·`config.yml`·하위 하네스 자산은
    수정하지 않음(재사용만). 인증 세션과 익명 공개 클라이언트는 독립 쿠키 관리. 동일 하네스를 중복 신설하지 않음
  - 관찰 가능 완료: 픽스처가 마이그레이션된 DB + 부팅 앱(s14 공유 라우트·무효화 스케줄러 포함) + admin 시드 + role별·
    다중 WS·익명 공개 세션 클라이언트 + 구성된 워크스페이스/멤버/문서/첨부/공유 링크 + 무효화 스윕 호출 헬퍼 + 게이트
    토글 헬퍼 + share_link 관찰 헬퍼를 제공하고, editor가 `POST /documents/{id}/share`에서 200과 `ShareLinkRead`(토큰)을,
    익명 클라이언트가 `GET /public/{token}`에서 `PublicDocumentRead`를, 무효화 스윕 픽스처가 `run_invalidation_sweep`
    호출에서 결과를 반환하는 스모크 검증이 통과한다
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_
  - _Boundary: L6TestHarness_
- [x] 1.2 공유·무효화 스윕·공개 접근·게이트 토글 시나리오 헬퍼 구성 (호출 래퍼, L5 헬퍼 재사용)
  - `tests/integration_L6/helpers.py`에 공유 헬퍼(`POST /documents/{id}/share` 발급/재발급·`PATCH /documents/{id}/share`
    토글 래퍼·`ShareLinkRead` 관찰), 공개 접근 헬퍼(비인증 클라이언트로 `GET /public/{token}` 공개 렌더·`GET
    /public/{token}/attachments/{aid}` 링크 경유 파일 조회 래퍼, 상태코드·트리·바이너리·content-type 관찰), 게이트 토글
    헬퍼(`s05` owner/admin 경로로 워크스페이스 `is_shareable` true/false 설정), 무효화 스윕 헬퍼(하네스 세션으로
    `ShareInvalidationSweep.invalidate_by_observation(db)`/`run_invalidation_sweep()` 호출·retire 건수/`is_enabled`/
    `token` 교체 관찰), share_link 관찰 헬퍼(문서/토큰 기준 `token`·`is_enabled` 조회·물리 삭제 부재 확인)를 제공. 잠금·
    저장·휴지통 삭제·복구·완전삭제·`now` 주입 retention·아카이브 스윕·첨부 업로드/서빙·파일시스템 관찰·워크스페이스
    생성·멤버 추가(role)·role별 세션·계정 생성·로그인·상태 전이(비활동/삭제) 헬퍼는 `s13` L5 `helpers.py`(및 그것이
    재사용하는 L4/L3/L2/L1 헬퍼)를 재사용(중복 정의 금지)
  - 관찰 가능 완료: 헬퍼로 editor가 링크를 발급하고 익명 클라이언트가 `GET /public/{token}`에서 문서 트리를 받으며,
    문서를 trashed한 뒤 공개 접근이 404가 되고 무효화 스윕 헬퍼가 retire 건수를 반환하며 share_link 관찰 헬퍼가 토큰
    교체를 보고하고, 게이트 토글 헬퍼가 `is_shareable`를 전환하는 스모크 검증이 통과한다
  - _Requirements: 1.4, 3.1, 4.1, 5.1, 6.1, 7.1_
  - _Boundary: Helpers_
  - _Depends: 1.1_

- [ ] 2. Core: 계약 대조·공유흐름·무효화재발급·링크파일·전계층불변식·관통여정 검증 스위트
- [x] 2.1 (P) 누적 전체 계약 대조 스위트 — share_link 스키마·API(34~37)·전체 API 표면·ShareLinkRead/Update·PublicDocumentRead·에러·Base·Settings additive
  - `tests/integration_L6/test_cumulative_contract_conformance.py`에: (1) 마이그레이션된 `share_link` 컬럼(`id BIGINT
    PK`·`document_id BIGINT FK NOT NULL`·`token VARCHAR(64) NOT NULL UNIQUE`·`is_enabled BOOLEAN NOT NULL DEFAULT
    TRUE`·`created_at DATETIME NOT NULL`)과 UNIQUE 제약이 s01 물리 모델과 일치하고 s14가 새 마이그레이션을 추가하지
    않았음, (2) 부팅 앱 라우트가 s01 카탈로그 행 34~37(`POST /documents/{id}/share` editor·`PATCH /documents/{id}/share`
    editor·`GET /public/{token}` 공개·`GET /public/{token}/attachments/{aid}` 공개) 경로·메서드·요구 role대로 노출되고
    나아가 **전체 API 표면(행 1~37)** 이 계약대로 존재, (3) 미인증 401·viewer 발급 403·미존재 문서/링크 404·게이트 off
    발급/문서 비active 활성화 409·검증 실패 422를 실제 유발해 응답이 `ErrorResponse`(code/message/field_errors) 형태·
    상태 코드가 s01 에러 카탈로그와 일치하고 공개 경로(36~37)가 무효·부재·범위 밖을 정보 비노출 404로 통일(INV-8),
    (4) `ShareLinkRead`가 `TimestampedRead` 규약(`document_id`·`token`·`is_enabled`·`share_url`)·`ShareLinkUpdate`가
    (`is_enabled`)·`PublicDocumentRead`가 중첩 노드(읽기전용·내부 필드 비노출)·링크 경유 파일 응답이 스트리밍(binary),
    (5) s14 additive `share_token_bytes`·`share_invalidation_sweep_interval_seconds`가 존재하는 실제 결합 부팅에서
    `s01` `Settings`/`get_settings` 로딩 정상 성공·기존 필드(`file_storage_root`·`attachment_archive_root`·
    `default_trash_retention_days` 등) 보존·단일 접근자 유지, (6) 무효화 스케줄러 결합 부팅에서 `create_app()` 정상
    부팅·`share_invalidation_sweep_interval_seconds` `>0` 기동/`<=0` 미기동·기존 부팅 계약(s10 retention·s12 archival
    스케줄러 결합 포함) 무회귀를 검증. 대조 기준은 s01 단일 소스
  - 관찰 가능 완료: 스키마(share_link)·API 노출(34~37·전체 표면 1~37)·에러 형태(공개 경로 404 통일 포함)·Base 규약·
    Settings additive 로딩·스케줄러 결합 대조 그룹이 실제 결합 런타임에서 모두 통과하고, 불일치 시 어느 계약 요소가
    드리프트했는지 assertion 메시지가 지목한다
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Boundary: CumulativeContractConformanceSuite_
  - _Depends: 1.1_
- [x] 2.2 (P) 공유 발급·토글·공개 렌더·동적 하위 흐름 스위트 — 게이트·게이팅 (7.1~7.7, INV-1·2·3)
  - `tests/integration_L6/test_share_lifecycle_flow.py`에 게이트 on WS의 owner/editor/viewer/비멤버/admin 세션 + 익명
    공개 클라이언트로: (1) 게이트 on·문서 active면 editor 발급 200(`ShareLinkRead`·활성 토큰)·게이트 off면 발급 409·
    비활성 링크 활성화 토글 409 (3.1, 7.1·7.2·7.3), (2) 익명 클라이언트가 `GET /public/{token}`으로 문서+현재 active
    하위 계층을 안전 HTML 트리(`PublicDocumentRead`)로 조회·변경 동작 부재 (3.2, 7.4), (3) 공유 문서에 하위 추가 후
    재요청 시 새 하위 동적 포함·그 하위 trashed 시 트리 제외 (3.3, 7.5·7.6), (4) editor가 off 토글→동일 토큰 공개 404→
    on 토글→동일 토큰 공개 200(토큰 유지) (3.4, 7.7), (5) 발급/토글=editor(viewer 403·비멤버 403·미인증 401)·미존재
    문서/링크 404·admin bypass (3.5, INV-1·2·3)을 인증 세션 자·익명 클라이언트로 e2e 검증. 판정은 s05 실제 멤버십
    위에서. mock 없음
  - 관찰 가능 완료: 게이트 하 발급·게이트 off 거부·공개 읽기전용 렌더·동적 active 하위 포함/제외·토글 off/on 동일 토큰·
    발급/토글 게이팅이 실제 결합에서 모두 예상대로 통과/거부된다
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - _Boundary: ShareLifecycleFlowSuite_
  - _Depends: 1.2_
- [x] 2.3 (P) 무효화·재발급 결합 스위트 — 문서 trashed/복구·게이트 off/on·retire·재발급·멱등 (INV-8, 7.8~7.10)
  - `tests/integration_L6/test_invalidation_reissue.py`에: (1) 발급 후 `DELETE /documents/{id}`(trashed)·`DELETE
    /trash/{bundleId}`(deleted)로 문서 전이 → 익명 `GET /public/{token}` 즉시 404(실시간 게이트) (4.1, 7.8, trash L4
    결합), (2) `run_invalidation_sweep`/`invalidate_by_observation` 실행 → 무효 조건 활성 링크가 `is_enabled=false`+토큰
    교체(retire) DB 관찰·반복 실행 시 이미 무효화 링크 skip(멱등) (4.2, 5.6), (3) `POST /trash/{bundleId}/restore`
    복구 → 이전 토큰 여전히 404(자동 복원 없음) → 재발급(`POST /documents/{id}/share`)이 이전 토큰과 다른 새 토큰의
    활성 링크 발급 → 새 토큰만 200 (4.3, 7.9, INV-8), (4) `s05` 게이트 off → 익명 공개 즉시 404 → 스윕 retire → 게이트
    재 on 후에도 이전 토큰 404 → 재발급 새 토큰만 유효 (4.4, 7.10, INV-8), (5) s14가 상태 전이·게이트 설정을 수행하지
    않고 `document.status`·`is_shareable` 관측으로 판정·실시간 공개 게이트가 스윕 이전에도 무효 접근 차단(while-invalid
    스윕 주기 무관) (4.5)을 검증. 문서 전이·복구·게이트 설정·스윕 직접 호출은 실제 s10·s07·s05·s14 코드. 이전 토큰과
    재발급 토큰이 다름을 DB로 확인(임의 DB 조작 금지). mock 없음
  - 관찰 가능 완료: 문서 trashed/deleted·게이트 off 시 즉시 공개 404·retire 토큰 교체·복구/게이트 재활성 후 이전 토큰
    무효·재발급 새 토큰 200·멱등이 실제 결합에서 모두 통과하고, 무효화된 링크가 재발급 없이 되살아나지 않음(INV-8)이
    DB·공개 접근 관찰로 확인된다
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - _Boundary: InvalidationReissueSuite_
  - _Depends: 1.2_
- [x] 2.4 (P) 링크 경유 첨부 접근·연동 차단 스위트 — 스트리밍·게이트/status 차단·보관·범위/격리 (8.4·8.5, INV-6·7)
  - `tests/integration_L6/test_link_attachment_access.py`에: (1) 공유 문서(또는 active 하위)에 `s12`로 올린 첨부를 익명
    `GET /public/{token}/attachments/{aid}`로 조회 → 바이너리 반환(이미지 로딩·파일 다운로드)·공개 렌더 HTML의
    `/attachments/{id}` 참조가 `/public/{token}/attachments/{id}`로 재작성 (5.1, 8.4), (2) 게이트 off·문서 trashed 시
    링크 경유 첨부 접근도 공개 렌더와 동일하게 404로 함께 차단 (5.2, 8.5), (3) 보관된(`is_archived=true`) 첨부는 s12
    규약대로 role·경로 무관 404(보관 유발은 실제 아카이브 스윕으로) (5.3, INV-7), (4) 공유 서브트리 밖 문서 첨부·다른
    워크스페이스 첨부는 404(링크 범위 밖·다른 WS 비노출) (5.4, INV-6), (5) s14가 저장·격리·보관 판정을 재구현하지 않고
    s12 `serve_attachment`·`AttachmentRepository.get`을 재사용 (5.5)을 검증. 첨부 업로드·아카이브 스윕은 s12 실제 코드
    (L5 헬퍼 재사용). mock 없음
  - 관찰 가능 완료: 링크 경유 첨부 스트리밍(이미지/파일)·게이트 off·문서 trashed 연동 차단·보관 404·범위/격리 404가
    실제 결합에서 모두 통과하고, 링크 경유 파일 계층 간 트리거(s14↔s12)가 성립함(8.4·8.5)이 확인된다
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: LinkAttachmentAccessSuite_
  - _Depends: 1.2_
- [x] 2.5 (P) 전 계층 불변식 회귀 스위트 — INV-1~12 완전 조립 시스템 검증
  - `tests/integration_L6/test_full_stack_invariants.py`에 완전히 조립된 시스템에서: (1) 권한 WS 단위 판정·문서별 개별
    권한 부재(INV-1)·viewer 문서/휴지통/공유 링크 변경 불가(INV-2)·admin 비멤버 WS 문서/첨부/공유 접근·조작(INV-3)을
    실제 멤버십 세션으로 관찰 (6.1), (2) user(`is_deleted`)·document(`status`)·attachment(`is_archived`)·share_link
    (`is_enabled`+토큰 교체)에 물리 삭제(DELETE row) 부재를 DB 관찰(INV-4) (6.2), (3) `POST /documents/{id}/move` 순환
    거부(INV-5)·문서/이동/공유/링크 경유 파일 WS 경계 미월경(INV-6) (6.3), (4) deleted 문서·보관 첨부 복원 경로 부재
    (INV-7)·무효화 링크 재발급 없이 접근 불가(INV-8)·문서당 편집 잠금 최대 1인(INV-9, `lock_user_id` 단일) (6.4),
    (5) 삭제/복구/완전삭제 묶음 원자·비병합(INV-10)·자식 먼저 trash(INV-11, `child.trashed_at ≤ parent.trashed_at`)·
    묶음 보관 만료 각 `trashed_at` 독립 산정(INV-12) (6.5)을 실제 삭제·복구·보관 만료·잠금·이동 결합으로 검증. 상태
    전이·삭제·복구·보관 유발은 실제 s07/s09/s10/s12 코드(L5/L4 헬퍼 재사용). mock 없음
  - 관찰 가능 완료: 12개 불변식(INV-1~12)이 최상위 계층(공유) 결합 후 완전히 조립된 시스템에서 모두 성립함이 실제 DB·
    파일시스템·API 관찰로 통과하고, 계층 경계를 넘는 불변식 회귀가 없음이 확인된다
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Boundary: FullStackInvariantSuite_
  - _Depends: 1.2_
- [ ] 2.6 (P) 대표 전 계층 관통 e2e 여정 스위트 — auth → workspace → document → lock/version → trash → attachment → sharing
  - `tests/integration_L6/test_end_to_end_journey.py`에 하나의 사용자 여정으로: (1) admin이 사용자 생성(s03)→사용자
    로그인(s02)→owner로 워크스페이스·문서·하위문서 구성(s05·s07) (7.1), (2) 문서 편집 잠금(s09)→이미지 붙여넣기(s12)→
    저장(s09 새 버전)→게이트 on WS에서 공유 발급(s14)→익명 접근자가 `GET /public/{token}` 문서·`GET /public/{token}/
    attachments/{aid}` 첨부 열람(8.4) (7.2), (3) 하위 문서 삭제(s10 trashed)→묶음 포착→공개 렌더 트리 제외→그 하위 대상
    링크(있다면) 무효화 (7.3), (4) 삭제 하위 복구(s10 restore 위치 규칙)→그 문서 공유 재발급(이전 토큰과 다른 새 토큰)
    (7.4, INV-8), (5) 완전삭제(`DELETE /trash/{bundleId}`)→deleted→무효화 스윕 retire+아카이브 스윕 첨부 보관 이동
    (`is_archived=true`)·물리 삭제 부재(INV-4) 파일시스템·DB 관찰 (7.5)을 검증. 전 단계 실제 라우트·엔진·스윕 결합
    (L5/L4/L3/L2/L1 헬퍼 재사용). mock 없음
  - 관찰 가능 완료: 하나의 사용자 여정이 auth·admin·workspace·document·lock/version·trash·attachment·sharing 전체를
    관통해 실제 결합에서 성립하고, 각 단계에서 불변식이 유지됨이 확인되며, 실패 시 어느 계층 결합이 흐름에서 깨지는지
    여정 단계별 assertion이 지목한다
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  - _Boundary: EndToEndJourneySuite_
  - _Depends: 1.2_

- [ ] 3. Validation: 게이트 판정 및 재검증 트리거 (L6 종단 = 전체 시스템 GO)
- [ ] 3.1 전체 스위트 결합 실행 및 게이트(L6 종단) 판정·재검증 트리거 기록
  - `uv run pytest tests/integration_L6` 전체를 실제 전체 결합(마이그레이션 DB + 부팅 앱(s14 공유 라우터·무효화
    스케줄러 포함) + 실제 멤버십/문서/버전/첨부/공유 링크 데이터 + 실제 파일시스템 저장/보관 폴더 + 실제
    `ShareInvalidationSweep` + 실제 `DocumentStateEngine`/`RetentionSweepService`/`ArchivalSweepService`, mock 없음)
    에서 실행하여 Requirement 2~7 스위트가 전부 통과하면 게이트(G-1 규칙, L6 종단) 통과(=전체 시스템 GO, downstream
    없음)로, 하나라도 실패하면 미통과(=전체 시스템 GO 차단)로 판정. 검증 실패는 원인 spec(s01/s02/s03/s05/s07/s09/s10/
    s12/s14)에서 수정 후 재실행하며 체크포인트에서 feature 로직을 변경해 우회하지 않음. 검증 대상 환경(MySQL 8·부팅
    앱·파일시스템 저장/보관 폴더·전체 스케줄러 결합) 미충족은 스킵이 아니라 실패로 처리. 재검증 트리거(전체 upstream
    `s01`/`s02`/`s03`/`s05`/`s07`/`s09`/`s10`/`s12`/`s14` 중 어느 것이 수정되어도 이 최종 체크포인트를 항상 누적 집합
    기준 재실행 — 재검증 트리거의 종단, `s01` 수정 시 모든 체크포인트 재실행)를 스위트 문서/주석으로 명시
  - 관찰 가능 완료: `uv run pytest tests/integration_L6`가 전부 통과하여 게이트 통과 = 전체 시스템 GO가 성립하고,
    재검증 트리거 대상과 전체 시스템 GO 가부가 명확히 기록된다
  - _Requirements: 1.5, 8.1, 8.2, 8.3, 8.4_
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

## Implementation Notes
- **무효화 스윕 세션 바인딩 함정**: L1 하네스는 `app.dependency_overrides[get_db]` 만 override 하고
  `app.common.db.SessionLocal`(모듈 전역)은 개발 DB 에 그대로 묶여 있다(L1 conftest 주석 명시).
  `app.sharing.invalidation.run_invalidation_sweep()` 는 호출 시점에 `app.common.db.SessionLocal()`
  로 **자기 세션**을 열므로 그대로 호출하면 **테스트 DB 가 아니라 개발 DB** 를 친다. 따라서 L6
  무효화 스윕 접근은 L5 `ArchivalSweepAccess` 패턴을 그대로 답습해 `harness.session_local` 세션으로
  `ShareInvalidationSweep().invalidate_by_observation(db)` 를 직접 호출하고 commit 한다(부팅 앱과
  동일 세션 팩토리·커밋 경계 정렬). `run_invalidation_sweep()` 자체를 관측 경로로 쓰려면
  `app.common.db.SessionLocal` 을 `harness.session_local` 로 monkeypatch 해야 한다.
- **하네스/헬퍼 재사용 체인**: L6 conftest 는 `from tests.integration_L5.conftest import (…L5 __all__
  전체…)` 로 L1~L5 픽스처 계보를 한 번에 재-import 하고, L6 helpers 는 `from tests.integration_L5
  import helpers as l5_helpers` 후 `l4_helpers=l5_helpers.l4_helpers`(및 l3/l2/l1) 재바인딩한다.
- **게이트 토글 헬퍼**: 워크스페이스 `is_shareable` 는 `l2_helpers.update_settings(client, ws_id,
  is_shareable=True/False)`(PATCH /workspaces/{id}, owner) 로 설정한다(신규 라우트 불필요).
- **공유 발급/토글 응답 200**: `POST /documents/{id}/share`·`PATCH …/share` 는 계약상 **200**(upsert
  통일)이며 201 이 아니다. `ShareLinkRead` = TimestampedRead(id·created_at·updated_at=None) +
  document_id·token·is_enabled·share_url(`/public/{token}`). 공개 렌더 `PublicDocumentRead{root}`.
- **DATETIME(0) 초정밀도**: share_link.created_at 등 DATETIME 은 s01 마이그레이션상 초 정밀도이므로
  타임스탬프 비교 시 microsecond 를 0 으로 절삭해 비교한다(하위 하네스가 이미 답습).
- **Windows 파일 핸들 결정성 함정(아카이브 스윕)**: 아카이브 스윕은 `move_to_archive`(os.rename)로
  저장 파일을 보관 루트로 옮긴다. Windows 는 열린 핸들이 있는 파일의 rename 을 거부하므로, 스윕
  **직전**에 그 첨부를 `GET /public/{token}/attachments/{aid}`(또는 `GET /attachments/{aid}`)로
  서빙하면 `StreamingResponse` 가 남긴 파일 핸들이 간헐적으로 이동을 실패시켜 스윕이 그 첨부를
  건너뛴다(processed=0, 비결정). 보관 대상 첨부는 스윕 직전에 서빙하지 말 것(L5 결정적 아카이브
  스위트 규약). 보관 전 접근 200 은 별도 테스트로 독립 증명하고, 보관 격리(INV-7)는 공개 렌더 200
  (게이트·status 정상) + is_archived=true + 범위 안 첨부 → 링크 경유 404 로 격리한다.
