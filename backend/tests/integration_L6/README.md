# L6 누적 통합 검증 체크포인트 (s15-integration-check-L6) — 최종 = 전체 시스템 e2e

> 게이트 **G-1 의 종단**(계층 6, sharing). 이 문서는 게이트 판정 기준과 재검증 트리거를 기록하는 참조 문서다.
> **판정은 이 문서가 선언하지 않는다.** 판정은 오직 `uv run pytest tests/integration_L6`의 재현 가능한
> 실행 결과로만 산출된다(design.md §GateVerdict: "게이트 판정 결과는 테스트 실행 결과로 산출된다 — 전부
> 통과 = 게이트 통과 = 전체 시스템 GO, 수동 선언 금지"). 아래 서술은 그 명령이 권위(authority)이며, 이
> 문서는 그 명령의 기준·범위·후속 조치를 기록할 뿐이다.

## 1. 이 체크포인트는 무엇인가

L6 계층 경계에서 수행하는 **누적 통합 검증 체크포인트이자 전체 시스템의 최종 e2e 체크포인트**다. 계층 6
(sharing) 완성 = 전체 시스템 완성이므로, 이 시점까지 완성된 upstream 누적 집합 전체
**s01-contract-foundation ⊕ s02-auth ⊕ s03-admin-account ⊕ s05-workspace ⊕ s07-document-core ⊕
s09-lock-version ⊕ s10-trash ⊕ s12-attachment ⊕ s14-sharing = 전체 시스템**을 대상으로 검증한다. (주의:
이번 계층에서 **s14**(문서 단위 읽기 전용 공유 링크)가 새로 결합되며, `s04`·`s06`·`s08`·`s11`·`s13`은 이
체크포인트가 **재사용**하는 하네스일 뿐 검증 대상 feature 코드가 아니다 — 이들의 feature 코드는 존재하지
않는다.)

L6의 검증 초점은 최상위 계층(공유)이 처음 결합하는 경계와 전 계층 관통 결합이다.

- **공유 링크 무효화·재발급 결합(INV-8, 7.8·7.9·7.10)**: `s10`/`s07`이 문서를 trashed/deleted 로
  전이시키거나 `s05`가 워크스페이스 `is_shareable` 게이트를 off 로 두면, `s14`가 그 **관측 가능한 결과**를
  근거로 활성 링크를 **실시간 게이트**로 즉시 차단하고 조정 스윕(`ShareInvalidationSweep`)으로 영구
  무효화(retire=비활성+토큰 교체)한다. 문서 복구·게이트 재활성 후에도 이전 토큰은 되살아나지 않으며
  재발급(새 토큰)만이 다시 공유를 가능케 한다. 사용자 조작 토글(on/off)만 동일 토큰을 유지하는 유일한 상태
  기반 예외다(7.7). **두 무효화 경로**(공개 접근 시 lazy retire ↔ 관측 스윕 `is_enabled=true`-only 스코프)의
  상호작용을 정확히 관찰한다.
- **링크 경유 첨부 접근·연동 차단 결합(8.4·8.5, L5↔L6)**: 활성 링크로 공유 문서(및 현재 active 하위)에 속한
  이미지·파일 첨부를 링크 경유로 스트리밍하되(8.4), 게이트 off·문서 trashed 시 파일 접근도 함께 404(8.5)이고
  보관 첨부는 role·경로 무관 404(INV-7), 서브트리 밖·다른 WS 첨부는 404(INV-6)다. `s14`는 저장·격리·보관
  판정을 재구현하지 않고 `s12` 서빙을 재사용한다.
- **문서 status·WS `is_shareable` ↔ 공유 링크 상호작용(7.8~7.10)**: 위 결합이 문서 status·게이트라는 관측
  가능한 결과에만 근거해 성립하며, 하위 계층(s05·s07·s10)은 상위 계층(s14)을 알지 못한다(의존 방향 준수).
- **전 계층 관통 e2e**: 하나의 사용자 여정이 auth → workspace → document → lock/version → trash →
  attachment → sharing 전체를 관통하며, 그 과정에서 12개 불변식(INV-1~12)이 완전히 조립된 시스템에서 모두
  성립한다.

대조의 유일한 기준은 개별 spec(s02·s03·s05·s07·s09·s10·s12·s14) design이 아니라 **s01 단일 소스**
(§Physical Data Model `share_link`(`document_id`·`token VARCHAR(64) UNIQUE`·`is_enabled`·`created_at`) ·
§API Endpoint Catalog 행 34~37 및 **전체 카탈로그(행 1~37)** · §Errors 코드 카탈로그 · §Invariants
Catalog INV-1~12 · §Common/Permissions `Role`·`require_ws_role`·admin bypass · §Base Schemas
`ORMReadModel`·`TimestampedRead`·`Page` · §Settings 스키마 + additive 확장)다(Req 1.2).

**mock 없음(Req 1.1)**: 모든 검증은 실제 결합 상태 — 마이그레이션이 적용된 실제 MySQL 8 + `create_app()`로
부팅된 실제 애플리케이션(s02~s12 + **s14 공유 라우터 + 무효화 스케줄러 조립**) + 실제 서명 쿠키 세션 + 실제
`workspace_member`·`document`·`document_version`·`attachment`·`share_link` 데이터 + 실제 파일시스템 저장/보관
폴더 + 실제 `ShareInvalidationSweep` + 실제 `DocumentStateEngine`·`RetentionSweepService`·
`ArchivalSweepService` — 에서 수행한다. stub·가짜 구현을 쓰지 않는다. 조정 서비스·스윕·엔진 직접
호출(`invalidate_by_observation`·`sweep` 등)은 실제 s14·s10·s07·s12 코드 실행이므로 mock 이 아니다(Req 1.6).

**feature 미구현(Req 1.3)**: 이 체크포인트는 어떤 엔드포인트·서비스·스키마·마이그레이션·상태 엔진·조정
서비스·스케줄러도 신규로 구현하지 않는다. 소유물은 `tests/integration_L6/` 테스트 자산과 본 문서(게이트
기록)뿐이며, `s13` `tests/integration_L5/`(및 그것이 재사용하는 L4/L3/L2/L1) 하네스는 **재사용·확장**한다(하위
하네스 무수정, Req 1.4).

## 2. 검증되는 것 (Req 2~7 스위트)

| 요구 | 태스크 | 검증 관심사 | 스위트 파일 |
|------|--------|-------------|-------------|
| Req 2 | 2.1 | 누적 전체 계약 대조(share_link 스키마·API 34~37·**전체 표면 1~37**·`ShareLinkRead`/`ShareLinkUpdate`/`PublicDocumentRead`·에러 모델·공개 경로 404 통일 INV-8·Base 규약·Settings additive 로딩·무효화 스케줄러 결합 부팅) | `test_cumulative_contract_conformance.py` |
| Req 3 | 2.2 | 공유 발급·토글·공개 렌더·동적 하위 흐름(게이트 하 발급 7.1·7.3·공개 읽기전용 렌더 7.4·동적 active 하위 7.5·7.6·토글 off/on 동일 토큰 7.7·게이팅 INV-1·2·3) | `test_share_lifecycle_flow.py` |
| Req 4 | 2.3 | 무효화·재발급 결합(문서 trashed/deleted·게이트 off 관측 → 실시간 게이트 즉시 404 → retire 토큰 교체 → 복구·재활성 후 이전 토큰 무효·재발급 새 토큰·멱등, INV-8, 7.8~7.10) | `test_invalidation_reissue.py` |
| Req 5 | 2.4 | 링크 경유 첨부 접근·연동 차단(스트리밍·참조 재작성 8.4·게이트/status 연동 차단 8.5·보관 404 INV-7·서브트리 밖/다른 WS 404 INV-6·s12 서빙 재사용) | `test_link_attachment_access.py` |
| Req 6 | 2.5 | 전 계층 불변식 회귀(완전 조립 시스템에서 INV-1~12 전부 성립) | `test_full_stack_invariants.py` |
| Req 7 | 2.6 | 대표 전 계층 관통 e2e 여정(auth→admin→workspace→document→lock/version→trash→attachment→sharing 한 흐름) | `test_end_to_end_journey.py` |

> 위 6개 스위트가 Req 2~7을 담당하며, `test_harness_smoke.py`·`test_helpers_smoke.py`는 L6 하네스(L5 하네스
> 재사용·확장 + 공유 발급/토글·공개 렌더/공개 파일·무효화 스윕 접근·게이트 토글·share_link 관찰 픽스처, 및 그
> 시나리오 래퍼 헬퍼)의 자체 점검이다. 게이트 판정은 스위트 전체(전체 `tests/integration_L6`)의 실행 결과로
> 집계된다.

현 시점 테스트 분포(관측값, 총 **84**): 계약 대조 27 · 공유 흐름 14 · 무효화·재발급 9 · 링크 경유 첨부 8 ·
전 계층 불변식 14 · 관통 여정 1 · 하네스 스모크 6 · 헬퍼 스모크 5.

## 3. 실행 방법

```bash
# backend/ 디렉터리에서
uv run pytest tests/integration_L6
```

> **직렬 실행 필수**: 이 스위트는 공유 `notion_lite_test` MySQL DB 를 function-scope 하네스로 쓰므로
> **직렬로만** 실행한다. `tests/integration_L6` 에 대해 두 번째 pytest 프로세스를 동시 기동하면
> 하네스 setup 충돌로 허위 ERROR 가 발생한다(테스트 결함이 아니라 동시 DB 경합). 게이트 판정은
> 단일 직렬 실행 결과로 산출한다.

**전제 조건(env prerequisites)**:
- 실제 MySQL 8이 가용해야 하며 Alembic 마이그레이션(`uv run alembic upgrade head` 상당)이 하네스가
  적용한다(L5→L4→L3→L2→L1 하네스 재사용).
- 부팅 앱은 s02·s03·s05·s07·s09·s10·s12 + **s14 공유 라우터 + 무효화 스케줄러가 조립된 상태**여야 한다(공유
  발급·토글·공개 렌더·링크 경유 파일 라우트 노출, lifespan 무효화 스케줄러 훅 결합).
- 실제 파일시스템 저장/보관 폴더(`Settings.file_storage_root`·`attachment_archive_root`)가 가용해야 한다.
- 실제 `ShareInvalidationSweep`·`DocumentStateEngine`·`RetentionSweepService`·`ArchivalSweepService`를 부팅 앱과
  동일 DB 세션으로 직접 호출한다. **mock 금지.**
  - **무효화 스윕 세션 바인딩 주의**: `app.sharing.invalidation.run_invalidation_sweep()`는 호출 시점에
    `app.common.db.SessionLocal`(개발 DB 에 묶임)로 자기 세션을 연다. L6 하네스는 이를 그대로 쓰지 않고
    `harness.session_local` 세션으로 `ShareInvalidationSweep().invalidate_by_observation(db)`를 직접 호출한다(부팅
    앱과 동일 세션 팩토리·커밋 경계 정렬).

**DB 미가용·부팅 앱 미충족·파일시스템 미가용·무효화 스케줄러 결합 미충족은 스킵이 아니라 실패(FAILURE)로
처리한다** — 미검증이 통과로 오인되는 것을 막기 위함이다(Req 8.4, §4.4·design §GateVerdict).

## 4. G-1 게이트 판정 기준 (L6 종단 = 전체 시스템 GO)

### 4.1 통과/미통과 조건 (Req 8.1, 8.2)

- **G-1 통과 조건**: `uv run pytest tests/integration_L6` 전체(Requirement 2~7 스위트 6개 + 하네스/헬퍼
  스모크)가 **전부 green**이면 게이트 통과 = **전체 시스템 GO**다(downstream 없음, 전체 spec 구현 완료 정합,
  Req 8.1).
- **G-1 미통과 조건**: 위 실행에서 **하나라도 실패하면** 게이트 미통과이며 전체 시스템 GO가 **차단**된다(Req
  8.2).
- **판정의 권위**: 판정은 이 문서의 선언이 아니라 위 명령의 실행 결과에서 **파생(derived)**된다. 전부 통과한
  실행 그 자체가 곧 판정이다(design §GateVerdict — 수동 선언 금지).
- **후속 계층 없음**: L6은 로드맵 게이트(G-1)의 **종단**이다. 이 체크포인트 통과 = 전체 시스템 GO이며
  downstream 체크포인트가 없다.

### 4.2 실패 처리 원칙 — origin-spec 수정 (Req 1.5 · design §Out of Boundary)

검증이 실패하면 **원인 upstream spec(s01/s02/s03/s05/s07/s09/s10/s12/s14)에서 수정하고 재실행**한다.
체크포인트는 계약·경계 회귀를 **포착·보고만** 하며, 위반을 우회하기 위해 feature 로직이나 테스트 기대치를
바꾸지 않는다. 실패 유형별 지목:

- 계약 드리프트(share_link 컬럼/카탈로그 34~37·전체 표면/에러 형태/`ShareLinkRead`·`PublicDocumentRead`/Settings
  additive 로딩·무효화 스케줄러 결합 부팅 불일치) → 계약 대조 스위트 실패 → s01(스키마·카탈로그) 또는
  원인 spec(s14) 수정.
- 공유 흐름 회귀(게이트 하 발급 오작동·공개 렌더 변경 노출·동적 하위 미반영·토글 토큰 교체·게이팅 오작동) →
  공유 흐름 스위트 실패 → s14(발급/토글/공개 렌더)·s05(게이트/멤버십)·s07(active_descendants/렌더) 중 원인 수정.
- 무효화·재발급 회귀(실시간 게이트 미차단·retire 토큰 미교체·복구 후 이전 토큰 부활·재발급 동일 토큰·멱등
  위반) → 무효화·재발급 스위트 실패 → s14(무효화 스윕/lazy retire/재발급 통일)·s10/s07(status 전이)·s05(게이트)
  중 원인 수정.
- 링크 경유 파일 회귀(스트리밍 실패·참조 미재작성·게이트/status 연동 미차단·보관 노출·서브트리/WS 누출) →
  링크 파일 스위트 실패 → s14(링크 경유 서빙·참조 재작성·소속/격리)·s12(serve_attachment/보관 404) 중 원인 수정.
- 전 계층 불변식 회귀(INV-1~12 중 하나라도 불성립) → 불변식 스위트 실패 → 해당 불변식 소유 spec 수정.
- 관통 여정 회귀(어느 계층 결합이 흐름에서 깨짐) → 여정 스위트 실패 → 해당 단계 소유 spec 수정.

### 4.3 환경 미충족 = 실패, 스킵 아님 (Req 8.4)

검증 대상 환경(마이그레이션된 MySQL 8 · 부팅 앱(공유 라우터·무효화 스케줄러 포함) · 파일시스템 저장/보관 폴더
· 전체 스케줄러 결합)이 미충족이면 이를 **스킵이 아니라 실패로 처리**한다. 미검증(unverified)이 게이트 통과로
오인되어서는 안 된다.

## 5. 재검증 트리거 (Req 8.3 · design §Revalidation Triggers · roadmap §재검증 트리거)

이 체크포인트는 **재검증 트리거의 종단**이다. `s01`·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·`s12`·`s14` 중
**하나라도 아래 계약 표면이 수정되면**, 이 최종 체크포인트를 **항상** 누적 집합 기준으로 **재실행**해야 한다.
재실행 시에도 mock 없이 실제 구현을 결합한 상태로 검증한다. **s01(계약) 수정 시에는 모든 체크포인트(L1~L6)를
재실행**한다.

- **s01(계약) 수정 시** — 모든 체크포인트 재실행: `share_link` 스키마(컬럼·`token` UNIQUE·`is_enabled`), 카탈로그
  행 34~37(및 전체 1~37) 경로·메서드·요구 role·요청/응답 스키마 이름, 권한 resolver(`Role` 위계·`require_ws_role`·
  admin bypass), 세션 인증 의존성, 공통 에러 카탈로그, `Settings` 스키마(additive 확장 계약), 불변식
  카탈로그(INV-1~12, 특히 INV-6·8).
- **s14(sharing) 수정 시** — 이 체크포인트 재실행: 공유 엔드포인트(행 34~37) 계약, 무효화 판정 기준(문서 status·
  게이트 관측)·retire=비활성+토큰 교체·재발급 통일(토글=상태 기반 예외) 구현, 공개 렌더 동적 active 하위·참조
  재작성 규약, 링크 경유 첨부 소속/WS 격리/보관 차단 판정, `share_token_bytes`·
  `share_invalidation_sweep_interval_seconds` Settings 필드·무효화 스케줄러 결합.
- **s12(attachment) 수정 시**: 첨부 서빙(`serve_attachment`)·보관 404 규약·저장 격리(링크 경유 파일 접근 근거).
- **s09(lock-version) 수정 시**: 편집 잠금 단일성(INV-9)·저장 시 버전 생성 계약(공개 렌더 현재 버전 근거).
- **s10(trash) 수정 시**: 완전삭제·보관 만료의 deleted 전이·복구 위치 규칙·묶음 규약(무효화 관측 근거, INV-10~12).
- **s07(document-core) 수정 시**: 문서→WS 어댑터·`active_descendants`·`MarkdownRenderer`·상태 엔진 primitive(공개
  렌더·동적 하위 근거).
- **s02·s03·s05 수정 시**: 로그인/세션 게이트, 계정 상태 전이·보존, 워크스페이스/멤버십 role 판정·게이트 설정.

## 6. 현재 판정 (verdict, 2026-07-18 관측)

**게이트 통과 — 84 passed. 전체 시스템 GO.** (downstream 없음, 전체 spec 구현 완료 정합.)

| 실행 | 명령 | 요약 |
|------|------|------|
| L6 게이트 run 1(권위) | `uv run pytest tests/integration_L6` | `84 passed, 859 warnings in 95.80s` |
| L6 게이트 run 2(안정성 재확인) | `uv run pytest tests/integration_L6` | `84 passed, 859 warnings in 95.05s` |
| L6 게이트 run 3(권위 재확인) | `uv run pytest tests/integration_L6` | `84 passed, 859 warnings in 94.79s` |

세 차례 연속 전량 green 으로 게이트 통과가 안정적으로 재현됨을 확인했다(계약 대조 27 · 공유 흐름 14 ·
무효화·재발급 9 · 링크 경유 첨부 8 · 전 계층 불변식 14 · 관통 여정 1 · 하네스 스모크 6 · 헬퍼 스모크 5 =
84). 이 수치는 선언이 아니라 명령 재실행으로 재현·갱신되는 **관측값**이다. upstream(s01·s02·s03·s05·s07·s09·
s10·s12·s14) 수정 시 §5 재검증 트리거에 따라 재실행하고 본 §6 판정을 최신 관측으로 갱신한다.

> warning 859건은 전부 하위 spec 애플리케이션 코드의 기존 `datetime.utcnow()` DeprecationWarning 으로, 이
> 체크포인트가 소유·수정하지 않는 upstream 코드에서 발생한다(테스트 결과에 영향 없음).

## 참조

- 요구사항: `.kiro/specs/s15-integration-check-L6/requirements.md` (Req 1.5, 8.1, 8.2, 8.3, 8.4)
- 설계: `.kiro/specs/s15-integration-check-L6/design.md`
  (§Components → GateVerdict, §Boundary Commitments → Revalidation Triggers, §Testing Strategy)
- 대조 기준 단일 소스: `.kiro/specs/s01-contract-foundation/design.md`
  (§Physical Data Model `share_link` · §API Endpoint Catalog 행 1~37 · §Errors · §Invariants Catalog
  INV-1~12 · §Common/Permissions · §Base Schemas · §Settings)
- 검증 대상 동작: `.kiro/specs/s14-sharing/design.md`(발급/토글·공개 렌더·`ShareInvalidationSweep`·
  `ShareInvalidationScheduler`·Settings additive)·`s12`/`s10`/`s09`/`s07`/`s05`/`s03`/`s02` design
- 재사용 하네스: `.kiro/specs/s13-integration-check-L5/design.md`·`backend/tests/integration_L5/`,
  및 그것이 재사용하는 L4/L3/L2/L1 하네스
- 게이트·재검증 트리거: `.kiro/steering/roadmap.md` (§게이트 · §재검증 트리거 · §Shared seams to watch)
