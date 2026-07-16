# Requirements Document

## Introduction

`s15-integration-check-L6`는 **계층 6(L6)의 누적 통합 검증 체크포인트이자 전체 시스템의 최종 e2e 체크포인트**다.
계층 6(sharing)이 완성된 시점 = 전체 시스템 완성이므로, 이 체크포인트는 지금까지 완성된 upstream 누적 집합
전체(`s01-contract-foundation` ⊕ `s02-auth` ⊕ `s03-admin-account` ⊕ `s05-workspace` ⊕ `s07-document-core`
⊕ `s09-lock-version` ⊕ `s10-trash` ⊕ `s12-attachment` ⊕ `s14-sharing` = **전체 시스템**)이 공유 계약과
정합하는지, 그리고 이번 계층에서 처음 결합되는 **경계(공유 링크 생명주기·무효화·재발급 ↔ 문서 status·워크스페이스
게이트 ↔ 링크 경유 첨부 접근)** 와 **전 계층 결합**이 실제 결합 상태에서 성립하는지 mock 없이 검증한다. 이는
로드맵에서 가장 넓은 누적 검증 범위이며, 통과 시 전체 시스템이 GO 상태가 된다.

이 체크포인트는 **feature 로직을 구현하지 않는다.** 새 엔드포인트·서비스·스키마·마이그레이션·상태 엔진·조정
서비스·스케줄러를 추가하지 않으며, 오직 (1) 전체 누적 upstream의 계약·경계 정합 검증과 (2) 그 검증을 실제 구현
결합으로 실행하는 integration/e2e 테스트만 소유한다. 검증의 유일한 대조 기준은 개별 spec(s02·s03·s05·s07·s09·
s10·s12·s14)의 design이 아니라 **`s01-contract-foundation`의 단일 소스**(전체 인터페이스 · 데이터 스키마 · API
엔드포인트 카탈로그 행 34~37을 포함한 전체 카탈로그 · 공통 에러 모델 · 세션/권한 resolver 계약 · Settings 스키마 ·
불변식 카탈로그 INV-1~12)다.

L6의 검증 초점은 최상위 계층(공유)이 처음 결합하는 경계와 전 계층 관통 결합이다.
1. **공유 링크 무효화·재발급 결합(INV-8)**: `s10`/`s07`이 문서를 trashed/deleted로 전이시키거나(7.8) `s05`가
   워크스페이스 `is_shareable` 게이트를 off로 두면(7.10), `s14`가 그 **관측 가능한 결과**를 근거로 활성 링크를
   실시간 게이트로 즉시 차단하고 조정 스윕으로 영구 무효화(retire=비활성+토큰 교체)한다. 문서 복구·게이트 재활성
   후에도 이전 토큰은 되살아나지 않으며 재발급(새 토큰)만이 다시 공유를 가능케 한다(7.9·7.10·INV-8). 사용자 조작
   토글(on/off)만 동일 토큰을 유지하는 유일한 상태 기반 예외다(7.7).
2. **링크 경유 첨부 접근·연동 차단 결합(L5↔L6)**: 활성 링크로 공유 문서(및 현재 active 하위)에 포함된 이미지·파일
   첨부를 링크 경유로 조회할 수 있으나(8.4), 게이트 off·문서 trashed 시 파일 접근도 함께 차단되고(8.5), 보관된
   첨부는 `s12` 규약대로 role·경로 무관 404이며, 공유 서브트리 밖·다른 워크스페이스의 첨부는 404로 차단된다(INV-6).
3. **문서 status·WS `is_shareable` ↔ 공유 링크 상호작용(7.8~7.10)**: 위 두 결합이 문서 status·게이트라는 관측
   가능한 결과에만 근거해 성립하며, 하위 계층(s05·s07·s10)은 상위 계층(s14)을 알지 못한다(의존 방향 준수).
4. **전 계층 결합 e2e**: 하나의 사용자 여정이 auth → workspace → document → lock/version → trash → attachment →
   sharing 전체를 관통하며, 그 과정에서 12개 불변식(INV-1~12)이 완전히 조립된 시스템에서 모두 성립한다.

이 체크포인트는 로드맵의 **게이트(G-1 규칙)의 종단**이다: 이 체크포인트가 통과하면 전체 시스템 GO다. 또한 upstream
(s01·s02·s03·s05·s07·s09·s10·s12·s14) 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행하는 **재검증
트리거의 최종 종단**이다(어떤 계층 수정 시에도 이 최종 체크포인트는 항상 재실행). `s01`(계약) 수정 시에는 모든
체크포인트를 재실행한다.

산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md` §3 REQ-7·REQ-8.4·8.5, §4.5 재발급 통일, §5 INV-1~12,
`s01-contract-foundation/design.md`(§Physical Data Model `share_link`(`document_id`·`token` UNIQUE·`is_enabled`·
`created_at`) · §API Endpoint Catalog 행 34~37 및 전체 카탈로그 · §Errors · §Invariants Catalog INV-1~12 ·
§Settings 스키마 · §Common/Permissions `Role`·`require_ws_role`·admin bypass · §Base Schemas),
`s14-sharing/design.md`(§ShareLinkService·§PublicShareService·§ShareInvalidationSweep·§ShareInvalidationScheduler·
Settings additive 확장), `s13-integration-check-L5/design.md`(재사용·확장할 통합 테스트 하네스 `tests/integration_L5`
패턴 — 그것이 재사용하는 L4/L3/L2/L1 하네스 포함), `.kiro/steering/roadmap.md`(게이트·재검증 트리거·Shared seams
to watch)를 참조한다.

## Boundary Context

- **In scope (이 체크포인트가 소유)**:
  - **전체 계약 대조 검증**: 실제 결합된 전체 시스템의 `share_link` 스키마(`document_id`·`token VARCHAR(64) UNIQUE`·
    `is_enabled BOOLEAN DEFAULT TRUE`·`created_at`), 공유 API(`s01` 카탈로그 행 34~37: `POST /documents/{id}/share`
    (editor)·`PATCH /documents/{id}/share`(editor)·`GET /public/{token}`(공개)·`GET /public/{token}/attachments/{aid}`
    (공개)), 응답/요청 스키마(`ShareLinkRead`·`ShareLinkUpdate`·`PublicDocumentRead`), 공개 접근 계약, 공통 에러
    모델이 `s01` 단일 소스와 일치하는지 대조. **전체 API 표면(행 1~37)** 이 부팅된 앱에서 계약대로 노출되는지 최종
    확인. **Settings additive 확장 조정 항목**: `s14`가 추가한 `share_token_bytes`·
    `share_invalidation_sweep_interval_seconds`가 `s01` `Settings` 계약 로딩을 깨지 않고 기존 필드가 보존되며 무효화
    스케줄러가 lifespan에 결합되는지 확인.
  - **공유 링크 발급·토글·공개 렌더 흐름 검증(이번 계층 신규 경계 = 공유)**: 워크스페이스 `is_shareable` 게이트
    하(7.1·7.2)에서 editor 이상이 active 문서에 링크를 발급(7.3)하고, 활성 링크로 공개 읽기 전용 접근 시 문서와
    현재 active 하위 계층이 표시(7.4·7.5)되며, 새 하위가 추가되면 동적으로 포함(7.6)되고, 토글 off/on이 동일
    토큰으로 동작(7.7)함. viewer 발급 403(INV-2)·비멤버 차단(INV-1)·미인증 401·admin bypass(INV-3).
  - **공유 링크 무효화·재발급 결합 검증(INV-8, 7.8·7.9·7.10)**: 문서가 trashed/deleted로 전이되면(`s10` 삭제·
    `s07` 엔진) 그 문서의 링크 공개 접근이 즉시 무효(7.8)가 되고, 무효화 조정 스윕이 링크를 retire(비활성+토큰
    교체)하며, 문서 복구 후에도 이전 토큰은 무효이고 재발급(새 토큰)만 유효(7.9). 워크스페이스 게이트가 off되면
    즉시 무효, 게이트 재활성 후에도 이전 토큰 무효이며 재발급 필요(7.10). 무효화 판정은 문서 status·게이트라는 관측
    가능한 결과에만 근거하며 s14가 상태 전이·게이트 설정을 수행하지 않고 멱등하게 동작함.
  - **링크 경유 첨부 접근·연동 차단 검증(8.4·8.5, L5↔L6)**: 활성 링크로 공유 문서(및 active 하위)에 포함된 첨부
    바이너리를 `GET /public/{token}/attachments/{aid}`로 조회해 이미지 로딩·파일 다운로드가 성립(8.4)하고, 게이트
    off·문서 trashed 시 링크 경유 파일 접근도 함께 404로 차단(8.5)되며, 보관된 첨부는 `s12` 규약대로 role·경로 무관
    404, 공유 서브트리 밖·다른 워크스페이스 첨부는 404(INV-6)로 차단됨. s14는 저장·격리·보관 판정을 재구현하지 않고
    `s12` 서빙을 재사용함.
  - **전 계층 불변식 회귀 검증(INV-1~12 최종 결합)**: 완전히 조립된 시스템에서 권한 워크스페이스 단위 판정(INV-1)·
    viewer 읽기 전용(INV-2)·admin override(INV-3)·물리 삭제 부재(INV-4, user·document·attachment·share_link)·
    문서 이동 사이클 없음(INV-5)·WS 경계(INV-6, 문서·이동·공유·링크 경유 파일)·deleted/보관 복원 없음(INV-7)·
    무효화 링크 재발급 없이 접근 불가(INV-8)·문서당 잠금 최대 1인(INV-9)·묶음 원자성·비병합(INV-10)·자식 먼저
    trash(INV-11)·묶음 보관 만료 독립 산정(INV-12)이 모두 성립함.
  - **대표 전 계층 관통 e2e 여정 검증**: admin이 사용자 생성 → owner가 워크스페이스·문서·하위문서 구성 → 편집 잠금·
    저장(버전) → 이미지 붙여넣기 → 공유 링크 발급·외부 열람(첨부 포함) → 하위 문서 삭제(묶음·링크 무효) →
    복구(위치 규칙)·재발급 → 완전삭제(첨부 보관 이동)의 한 여정이 auth·admin·workspace·document·lock/version·trash·
    attachment·sharing 전체를 관통해 실제 결합에서 성립함.
  - **게이트·재검증 판정**: 위 검증 전부가 mock 없이 통과함을 게이트(G-1 규칙, L6 종단 = 전체 시스템 GO) 통과
    조건으로 기록하고, 재검증 트리거 대상(전체 upstream)을 명시.
- **Out of scope (이 체크포인트가 소유하지 않음)**:
  - 새로운 feature 동작·엔드포인트·서비스·스키마·마이그레이션·상태 엔진·조정 서비스·스케줄러 구현(모두
    s01·s02·s03·s05·s07·s09·s10·s12·s14 소유, 이미 완료 가정).
  - 검증 중 발견된 계약 위반의 **수정** — 원인 spec에서 고쳐야 하며, 체크포인트는 회귀를 포착·보고만 한다.
  - **범위 밖 기능**(`docs/projects.md` §6): 문서 검색, 과거버전 rollback, lock 자동 타임아웃, 실시간 동시편집
    (CRDT), self sign-up/SSO/OAuth, 보관 폴더 자동 정리, 다중 admin, 자식→부모 자동 재중첩. 이들은 검증 대상이
    아니다.
  - 개별 spec 단위 검증의 재실행(각 spec의 자체 테스트 소유). 체크포인트는 **결합·경계**만 본다.
  - **후속 계층**: 없음. L6은 최종 체크포인트이며 downstream이 없다.
- **Adjacent expectations (인접 spec/계약에 대한 기대)**:
  - `s01`이 `share_link` 스키마, 전체 엔드포인트 카탈로그(행 34~37 공유 포함), `WorkspaceRoleResolver`/
    `require_ws_role`/`Role`(위계 판정·admin bypass), 세션 인증(`get_current_user`/`AuthContext`), 공통 에러 모델,
    Base Schemas(`ORMReadModel`·`TimestampedRead`·`Page`), `Settings` 스키마, 불변식 카탈로그(INV-1~12), INV-8
    (무효화 링크는 재발급 없이 접근 불가)을 단일 소스로 제공한다.
  - `s05`가 워크스페이스 `is_shareable` 게이트를 owner/admin이 설정하도록 소유하고 `workspace_member`로
    `require_ws_role`을 실동작시켜 배치되어 있다. `s14`는 게이트 값·resolver를 소비한다.
  - `s07`이 문서 status·`active_descendants`·안전 HTML 렌더 규약(`MarkdownRenderer`)·문서→WS 어댑터
    (`ws_role_for_document`)를 구현하여 배치되어 있고, `s09`가 편집 잠금·저장 시 버전 생성을, `s10`이 휴지통·복구·
    완전삭제·보관 만료로 문서 status를 전이시켜 배치되어 있으며, `s14`는 이 결과(문서 status·게이트)를 **관측**할 뿐
    상태 전이·게이트 설정을 수행하지 않는다(의존 방향 준수).
  - `s12`가 첨부 저장·워크스페이스 격리·보관 이동·첨부 조회 서빙을 구현하여 배치되어 있고, `s14`는 링크 경유 파일
    접근에서 이를 재사용한다.
  - `s14`가 카탈로그 행 34~37의 동작(발급·토글·공개 렌더·링크 경유 파일)과 `ShareLinkService`·`PublicShareService`·
    `ShareInvalidationSweep`·`ShareInvalidationScheduler`(`run_invalidation_sweep`)를 구현하여 배치되어 있고,
    `s01` `Settings`에 `share_token_bytes`·`share_invalidation_sweep_interval_seconds`를 additive로 확장하되 새 DB
    마이그레이션은 추가하지 않는다.
  - `s13-integration-check-L5`의 통합 테스트 하네스(`tests/integration_L5` — L4/L3/L2/L1 하네스 재사용 + 첨부 업로드/
    서빙·아카이브 스윕·파일시스템 관찰 픽스처)가 존재하며, 이 체크포인트는 그 패턴을 **확장·재사용**한다(중복 신설
    금지).

## Requirements

### Requirement 1: 검증 방법론 및 대조 기준 (mock 없는 전체 실제 결합 · s01 단일 소스 · 전체 누적 집합 · L5 하네스 확장)

**Objective:** As a L6 최종 통합 체크포인트, I want 전체 시스템을 실제 구현으로 결합한 상태에서 단일 계약 소스에 대조
검증하기를, so that 공유 링크 무효화·재발급·링크 경유 파일 접근과 전 계층 관통 결합의 회귀가 전체 시스템 GO 이전에
최종적으로 포착된다.

#### Acceptance Criteria

1. The L6 Integration Checkpoint shall 모든 검증을 mock·stub·가짜 구현 없이 실제 `s01`·`s02`·`s03`·`s05`·`s07`·
   `s09`·`s10`·`s12`·`s14` 구현을 결합한 상태(마이그레이션 적용된 실제 DB + 실제 부팅된 애플리케이션(공유 라우터·
   무효화 스케줄러 포함) + 실제 서명 쿠키 세션 + 실제 workspace_member 데이터 + 실제 파일시스템 저장/보관 폴더 +
   실제 `ShareInvalidationSweep` + 실제 `DocumentStateEngine`/`RetentionSweepService`)에서 수행한다.
2. The L6 Integration Checkpoint shall 계약 정합의 대조 기준을 항상 `s01-contract-foundation`의 단일 소스
   (`share_link` 스키마·전체 엔드포인트 카탈로그(행 34~37 포함)·권한 resolver 계약·공통 에러 모델·Settings 스키마·
   불변식 카탈로그 INV-1~12)로 삼으며, 개별 spec(s02·s03·s05·s07·s09·s10·s12·s14)의 design을 기준으로 삼지 않는다.
3. The L6 Integration Checkpoint shall 어떤 feature 동작·엔드포인트·서비스·스키마·마이그레이션·상태 엔진·조정
   서비스·스케줄러도 신규로 구현하지 않고 검증 및 그 테스트 자산만 산출한다.
4. The L6 Integration Checkpoint shall `s13-integration-check-L5`의 통합 테스트 하네스 패턴(마이그레이션·앱 부팅·
   admin 시드·세션 유지 클라이언트·워크스페이스/멤버/role 세션·문서 트리 구성·엔진 세션 접근·두 editor 세션·잠금/
   저장/휴지통 헬퍼·`now` 주입 스윕 호출·첨부 업로드/서빙·파일시스템 관찰 픽스처)을 재사용·확장하며 동일한 하네스를
   중복 신설하지 않는다.
5. If 검증 대상 시스템에 계약을 위반하는 결합 회귀가 발견되면, the L6 Integration Checkpoint shall 이를 실패로
   보고하되 원인 spec에서의 수정을 유발할 뿐 체크포인트 내부에서 feature 로직을 변경하여 우회하지 않는다.
6. The L6 Integration Checkpoint shall 무효화 조정 스윕(INV-8)을 실제 DB 상태에 대해 실제로 실행
   (`ShareInvalidationSweep.invalidate_by_observation`·`run_invalidation_sweep` 직접 호출)하여 관측 가능한 DB
   부수효과(`is_enabled=false` + 토큰 교체)를 남기는지 확인하며, 스윕을 mock으로 대체하지 않는다. 실시간 공개 게이트도
   실제 공개 요청으로 관찰한다.

### Requirement 2: 계약 대조 — share_link 스키마 · 카탈로그(행 34~37) · ShareLinkRead/Update · PublicDocumentRead · Settings additive · 전체 API 표면 · 에러 모델

**Objective:** As a L6 최종 통합 체크포인트, I want 결합된 전체 시스템의 공유 스키마·공유 API·공개 접근 계약·Settings
확장·에러 형태와 전체 API 표면이 `s01` 단일 소스와 일치함을 확인하기를, so that s14가 계약을 벗어난 드리프트 없이
전체 계약 위에 얹혀 있고 additive Settings 확장이 기존 계약을 깨지 않으며 전체 API 표면이 계약과 정합함을 보장한다.

#### Acceptance Criteria

1. The L6 Integration Checkpoint shall 마이그레이션이 적용된 실제 DB의 `share_link` 테이블(`id BIGINT PK`,
   `document_id BIGINT FK NOT NULL`, `token VARCHAR(64) NOT NULL UNIQUE`, `is_enabled BOOLEAN NOT NULL DEFAULT
   TRUE`, `created_at DATETIME NOT NULL`)이 `s01` 물리 데이터 모델과 컬럼·제약·UNIQUE 인덱스 면에서 일치하고,
   `s14`가 새 DB 마이그레이션을 추가하지 않았음을 확인한다.
2. The L6 Integration Checkpoint shall 부팅된 애플리케이션에 `s01` 엔드포인트 카탈로그 행 34~37(`POST
   /documents/{id}/share`(editor)·`PATCH /documents/{id}/share`(editor)·`GET /public/{token}`(공개)·`GET
   /public/{token}/attachments/{aid}`(공개))이 카탈로그가 정한 경로·메서드·요구 role(공개 경로는 인증 우회)대로
   노출되고, 나아가 **전체 API 표면(행 1~37)** 이 계약대로 앱 라우트에 존재함을 확인한다.
3. When 결합된 시스템의 공유 발급·토글·공개 엔드포인트가 오류를 반환하면, the L6 Integration Checkpoint shall
   응답이 `s01` 공통 에러 응답 형태(`code`·`message`·선택적 `field_errors`)이고 상태 코드가 에러 코드 카탈로그
   (401/403/404/409/422)와 일치하며, 공개 경로(행 36~37)가 무효·부재·범위 밖을 정보 비노출 목적으로 일관되게 404로
   처리함을 확인한다(INV-8 정보 비노출).
4. The L6 Integration Checkpoint shall 공유 발급/토글 응답 본문 `ShareLinkRead`가 `s01` Base Schemas 규약
   (`TimestampedRead` 상속, `document_id`·`token`·`is_enabled`·`share_url` 포함)을, 토글 요청 `ShareLinkUpdate`가
   (`is_enabled`) 규약을, 공개 렌더 응답 `PublicDocumentRead`가 중첩 노드(읽기 전용, `workspace_id` 등 내부 필드
   비노출) 규약을 따르며, 링크 경유 파일 응답이 스키마 본문이 아니라 스트리밍(binary)임을 확인한다.
5. The L6 Integration Checkpoint shall `s14`가 `s01` `Settings`에 additive로 추가한 `share_token_bytes`·
   `share_invalidation_sweep_interval_seconds` 필드가 존재하는 실제 결합 부팅에서 `s01` `Settings`/`get_settings`
   로딩이 정상 성공하고(부팅 실패 없음), 기존 필드(`file_storage_root`·`attachment_archive_root`·
   `default_trash_retention_days` 등)가 보존되며, 설정 접근이 여전히 단일 `Settings`/`get_settings` 경유임을
   확인한다(모듈별 설정 파일·`os.environ` 직접 접근 부재).
6. The L6 Integration Checkpoint shall 무효화 스케줄러 어댑터가 부팅에 결합된 상태에서 `s01` `create_app()`이 정상
   부팅되고, `share_invalidation_sweep_interval_seconds`가 `>0`이면 스케줄러가 기동·`<=0`이면 미기동되며, 이 결합이
   기존 앱 부팅 계약(s10 retention·s12 archival 스케줄러 결합 포함)을 회귀시키지 않음을 확인한다.

### Requirement 3: 공유 링크 발급·토글·공개 렌더 흐름 결합 (7.1·7.2·7.3·7.4·7.5·7.6·7.7, INV-1·2·3)

**Objective:** As a L6 최종 통합 체크포인트, I want is_shareable 게이트 하 발급·토글·공개 읽기 전용 렌더·동적 하위
포함이 실제 API 결합에서 계약대로 동작하고 워크스페이스 단위로 게이팅됨을 확인하기를, so that 공유 도메인(s14)이
s01 계약·s05 게이트/권한·s07 문서 상태/렌더 위에서 권한·게이트 불변식(INV-1·2·3)을 유지함을 보장한다.

#### Acceptance Criteria

1. While 문서 소속 워크스페이스의 `is_shareable`가 false인 동안, the L6 Integration Checkpoint shall 그 문서에 대한
   발급 요청과 비활성 링크의 활성화 토글 요청이 409로 거부됨을 확인하고(7.1·7.2), 게이트가 true이고 문서가 active일
   때 editor 이상의 발급이 활성 링크(토큰)와 `ShareLinkRead`를 반환함을 확인한다(7.3).
2. When 활성 공유 링크의 토큰으로 `GET /public/{token}` 공개 접근이 요청되면, the L6 Integration Checkpoint shall
   인증 없이 그 문서와 현재 active 하위 계층이 `s07` 안전 HTML 렌더 규약으로 렌더된 읽기 전용 트리(`PublicDocumentRead`)
   로 반환되고, 변경 동작이 제공되지 않음을 확인한다(7.4).
3. When 공유 문서에 새 하위 문서가 추가된 이후 공개 접근이 재요청되면, the L6 Integration Checkpoint shall 그 시점의
   현재 active 하위가 트리에 동적으로 포함되고(7.5·7.6), 그 하위를 trashed로 전이시키면 트리에서 제외됨을 확인한다.
4. When editor 이상 사용자가 활성 링크를 비활성으로 토글한 뒤 다시 활성으로 토글하면, the L6 Integration Checkpoint
   shall 동일 토큰이 유지된 채 상태만 전환되어 off 시 동일 토큰 공개 접근이 404·on 시 동일 토큰 공개 접근이 200임을
   확인한다(7.7, 재발급 통일 원칙의 유일한 상태 기반 예외).
5. The L6 Integration Checkpoint shall 발급·토글이 `require_ws_role(EDITOR)`(문서→WS 어댑터 경유)로 게이팅되어
   viewer의 발급·토글 403(INV-2)·비멤버 차단(INV-1)·미인증 401·미존재 문서/링크 404이며 admin이 비멤버 WS에서도
   bypass(INV-3)함을 실제 세션 결합으로 확인한다.

### Requirement 4: 공유 링크 무효화·재발급 결합 (INV-8, 7.8·7.9·7.10, L4↔L6 · 관측 기반 조정 · 멱등)

**Objective:** As a L6 최종 통합 체크포인트·보안 검증자, I want 문서가 휴지통으로 가거나 워크스페이스 게이트가 꺼지면
공유 링크가 즉시 무효화되고 복구·게이트 재활성 후에는 재발급해야만 다시 공유됨을 확인하기를, so that 무효화된 링크가
재발급 없이 되살아나지 않는 재발급 통일 원칙(INV-8)이 실제 전 계층 결합에서 성립함을 보장한다.

#### Acceptance Criteria

1. When editor가 공유 문서를 `DELETE /documents/{id}`로 trashed(또는 `DELETE /trash/{bundleId}`로 deleted)로
   전이시킨 뒤 그 문서의 토큰으로 `GET /public/{token}`이 요청되면, the L6 Integration Checkpoint shall 즉시 404가
   반환되어 공개 접근이 무효로 처리됨을 확인한다(7.8, 실시간 게이트, trash L4 결합).
2. When 문서 status·게이트 관측 무효화 스윕(`ShareInvalidationSweep.invalidate_by_observation`/
   `run_invalidation_sweep`)이 실행되면, the L6 Integration Checkpoint shall 무효 조건에 해당하는 활성 링크가
   retire(비활성 + 토큰 교체)되어 이전 토큰이 영구 무효화됨을 DB 관찰로 확인하고, 반복 실행 시 이미 무효화된 링크가
   다시 무효화되거나 오류를 내지 않고 건너뛰어짐(멱등)을 확인한다(5.6).
3. When 무효화된 문서가 `POST /trash/{bundleId}/restore`로 복구된 뒤 이전 토큰으로 공개 접근이 재요청되면, the L6
   Integration Checkpoint shall 이전 토큰이 여전히 404이고(자동 복원 없음) 재발급(`POST /documents/{id}/share`)이
   이전 토큰과 다른 **새 토큰**의 활성 링크를 발급해 그 새 토큰으로만 200이 반환됨을 확인한다(7.9, INV-8).
4. When owner/admin이 `s05` 경로로 워크스페이스 `is_shareable`를 false로 두면, the L6 Integration Checkpoint shall
   그 워크스페이스 문서의 토큰 공개 접근이 즉시 404가 되고, 게이트를 다시 true로 두어도 이전 토큰은 여전히 404이며
   재발급(새 토큰)만이 다시 공유를 가능케 함을 확인한다(7.10, INV-8).
5. The L6 Integration Checkpoint shall `s14`가 문서 상태 전이·게이트 설정을 스스로 수행하지 않고 `document.status`·
   `workspace.is_shareable`라는 관측 가능한 결과에만 근거하여 무효화를 판정함을 확인한다(관측 기반 조정, s14는 상태
   전이·게이트 설정 미수행). 실시간 공개 게이트가 스윕 이전에도 무효 접근을 차단하므로 while-invalid 보장이 스윕
   주기에 의존하지 않음을 확인한다.

### Requirement 5: 링크 경유 첨부 접근 및 연동 차단 (8.4·8.5, L5↔L6, INV-6·7)

**Objective:** As a L6 최종 통합 체크포인트, I want 공유 문서에 포함된 이미지·첨부 파일을 링크 경유로 조회하되 게이트·
문서 status·보관·WS 격리에 따라 함께 차단됨을 확인하기를, so that 링크 경유 파일 접근(8.4)과 무효화·격리 규약이 파일
접근에도 일관되게 적용되는 계층 간 트리거(8.5, L5↔L6)가 실제 결합에서 성립함을 보장한다.

#### Acceptance Criteria

1. When 활성 공유 링크의 토큰으로 그 공유 문서 또는 문서의 현재 active 하위에 포함된 첨부 바이너리가 `GET
   /public/{token}/attachments/{aid}`로 요청되면, the L6 Integration Checkpoint shall 인증 없이 그 첨부 파일
   바이너리가 스트리밍 반환되어 이미지 로딩·파일 다운로드가 허용됨을 확인하고, 공개 렌더 HTML의 첨부 참조가 링크
   스코프 경로(`/public/{token}/attachments/{aid}`)로 재작성됨을 확인한다(8.4).
2. While 문서 소속 워크스페이스의 `is_shareable`가 false이거나 공유 문서가 trashed·deleted 상태인 동안, the L6
   Integration Checkpoint shall 링크 경유 첨부 접근이 공개 렌더와 동일하게 404로 함께 차단됨을 확인한다(8.5, 게이트·
   status 연동 차단).
3. If 요청된 첨부가 보관(archived)된 상태이면, the L6 Integration Checkpoint shall `s12` 규약에 따라 링크 경유
   접근에서도 role·경로와 무관하게 404로 처리되어 보관 파일이 노출되지 않음을 확인한다(INV-7).
4. If 요청된 첨부가 공유 문서 또는 그 현재 active 하위에 속하지 않거나 다른 워크스페이스의 첨부이면, the L6
   Integration Checkpoint shall 그 요청이 404로 처리되어 링크 범위 밖·다른 WS 파일이 노출되지 않음을 확인한다(INV-6).
5. The L6 Integration Checkpoint shall `s14`가 첨부 저장·격리·보관 판정을 재구현하지 않고 `s12` 첨부 서빙
   (`serve_attachment`)·소속 검사(`AttachmentRepository.get`)를 재사용해 링크 경유 파일 서빙을 수행함을 확인한다.

### Requirement 6: 전 계층 불변식 회귀 — INV-1~12 최종 결합 검증

**Objective:** As a L6 최종 통합 체크포인트, I want 12개 불변식이 완전히 조립된 전체 시스템에서 모두 성립함을 확인하기를,
so that 계층 경계를 넘는 불변식이 최상위 계층 결합 후에도 회귀 없이 유지되어 전체 시스템이 안전하게 GO됨을 보장한다.

#### Acceptance Criteria

1. The L6 Integration Checkpoint shall 권한 판정이 워크스페이스 단위로만 이뤄지고 문서별 개별 권한이 없음(INV-1),
   viewer가 문서·휴지통·공유 링크 변경을 할 수 없음(INV-2), admin이 어떤 권한 검사로도 차단되지 않고 비멤버 WS의
   문서·첨부·공유를 접근·조작함(INV-3)을 실제 멤버십 세션 결합으로 확인한다.
2. The L6 Integration Checkpoint shall user·document·attachment·share_link에 예기치 않은 물리 삭제(DELETE row)가
   없고(INV-4), 비활동/삭제/보관/무효화가 각각 `is_active`/`is_deleted`/`status`/`is_archived`/`is_enabled`+토큰 교체
   플래그 전환으로만 표현됨을 DB 관찰로 확인한다.
3. The L6 Integration Checkpoint shall 문서 이동이 사이클을 만들지 않고(INV-5, `POST /documents/{id}/move` 순환
   거부), 문서·이동·공유·링크 경유 파일 접근이 워크스페이스 경계를 넘지 않음(INV-6)을 확인한다.
4. The L6 Integration Checkpoint shall deleted 문서·보관 첨부에 복원 경로가 없고(INV-7), 무효화된 공유 링크가 재발급
   없이 접근되지 않음(INV-8), 문서당 편집 잠금이 최대 1인임(INV-9, `s09` 잠금 단일성)을 실제 결합으로 확인한다.
5. The L6 Integration Checkpoint shall 삭제/복구/완전삭제가 묶음 단위로 원자적이고 서로 다른 시점의 묶음이 병합되지
   않음(INV-10), 독립 묶음의 자식이 부모보다 먼저 trash됨(INV-11, `child.trashed_at ≤ parent.trashed_at`), 묶음
   보관 만료가 각 `trashed_at` 기준으로 독립 산정됨(INV-12)을 실제 삭제·복구·보관 만료 결합으로 확인한다.

### Requirement 7: 대표 전 계층 관통 e2e 여정 (auth → workspace → document → lock/version → trash → attachment → sharing)

**Objective:** As a L6 최종 통합 체크포인트, I want 하나의 사용자 여정이 전 계층을 관통해 성립함을 확인하기를, so that
개별 경계 검증을 넘어 전체 시스템이 하나의 실제 사용자 흐름으로 결합해 동작함을 최종적으로 보장한다.

#### Acceptance Criteria

1. When admin이 사용자를 생성(`s03`)하고 그 사용자가 로그인(`s02`)한 뒤 owner로서 워크스페이스와 문서·하위문서를
   구성(`s05`·`s07`)하면, the L6 Integration Checkpoint shall 각 단계가 실제 세션·멤버십·문서 트리로 성립함을
   확인한다.
2. When 사용자가 문서 편집 잠금을 획득하고 이미지를 붙여넣어(`s12`) 첨부를 만든 뒤 저장(`s09` 새 버전)하고, 공유
   가능 워크스페이스에서 공유 링크를 발급(`s14`)해 익명 접근자가 `GET /public/{token}`으로 문서와 링크 경유 첨부
   (`GET /public/{token}/attachments/{aid}`)를 열람하면, the L6 Integration Checkpoint shall 잠금·저장(버전)·이미지
   저장·공유 발급·외부 열람(첨부 포함)이 하나의 여정으로 성립함을 확인한다.
3. When 하위 문서를 삭제(`s10` trashed)하면, the L6 Integration Checkpoint shall 그 삭제가 묶음으로 포착되고 그
   하위가 공개 렌더 트리에서 제외되며 그 하위 대상 공유 링크(있다면)가 무효화됨을 확인한다.
4. When 삭제된 하위 문서를 복구(`s10` restore, 위치 규칙)하고 그 문서에 대해 공유 링크를 재발급하면, the L6
   Integration Checkpoint shall 복구가 위치 규칙대로 성립하고 재발급이 이전 토큰과 다른 새 토큰을 발급함을
   확인한다(INV-8).
5. When 문서를 완전삭제(`DELETE /trash/{bundleId}`)한 뒤 무효화 스윕과 아카이브 스윕을 실행하면, the L6 Integration
   Checkpoint shall 완전삭제된 문서의 공유 링크가 무효화(retire)되고 연결 첨부가 보관 폴더로 이동(`is_archived=true`)
   되며 물리 삭제가 없음(INV-4)을 파일시스템·DB 관찰로 확인한다.

### Requirement 8: 게이트 G-1 판정 및 재검증 트리거 (누적 종단, L6 = 전체 시스템 GO)

**Objective:** As a 로드맵 게이트 관리자, I want L6 검증 결과가 전체 시스템 GO 가부와 재검증 대상을 명확히 산출하기를,
so that 전체 시스템의 릴리스 가부와 upstream 변경 시 재실행 범위를 예측 가능하게 통제할 수 있다.

#### Acceptance Criteria

1. When Requirement 2~7의 모든 검증이 실제 결합 상태에서 통과하면, the L6 Integration Checkpoint shall 게이트를
   통과로 판정하여 전체 시스템 GO(downstream 없음, 전체 spec 구현 완료 정합)를 기록한다.
2. If Requirement 2~7 중 하나라도 실패하면, the L6 Integration Checkpoint shall 게이트를 미통과로 판정하고 전체
   시스템 GO를 차단 상태로 표시한다.
3. The L6 Integration Checkpoint shall 재검증 트리거 대상을 명시한다: 어떤 계층(`s01`·`s02`·`s03`·`s05`·`s07`·
   `s09`·`s10`·`s12`·`s14`) 중 하나라도 수정되면 이 최종 체크포인트를 **항상** 누적 집합 기준으로 재실행해야 하며
   (재검증 트리거의 종단), `s01`(계약) 수정 시에는 모든 체크포인트를 재실행해야 한다.
4. If 검증 대상 환경(마이그레이션된 MySQL 8·부팅 앱(공유 라우터·무효화 스케줄러 포함)·파일시스템 저장/보관 폴더·
   전체 스케줄러 결합)이 미충족이면, the L6 Integration Checkpoint shall 이를 스킵이 아니라 실패로 처리하여 미검증이
   게이트 통과로 오인되지 않게 한다.
