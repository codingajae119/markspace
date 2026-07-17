# L5 누적 통합 검증 체크포인트 (s13-integration-check-L5)

> 게이트 **G-1** 산출 지점(계층 5). 이 문서는 게이트 판정 기준과 재검증 트리거를 기록하는 참조 문서다.
> **판정은 이 문서가 선언하지 않는다.** 판정은 오직 `uv run pytest tests/integration_L5`의
> 재현 가능한 실행 결과로만 산출된다(design.md §GateVerdict: "게이트 판정 결과는 테스트 실행 결과로
> 산출된다 — 전부 통과 = 게이트 통과, 수동 선언 금지"). 아래 서술은 그 명령이 권위(authority)이며,
> 이 문서는 그 명령의 기준·범위·후속 조치를 기록할 뿐이다.

## 1. 이 체크포인트는 무엇인가

L5 계층 경계에서 수행하는 **누적 통합 검증 체크포인트**다. 이 시점까지 완성된 upstream 누적 집합
**s01-contract-foundation ⊕ s02-auth ⊕ s03-admin-account ⊕ s05-workspace ⊕ s07-document-core ⊕
s09-lock-version ⊕ s10-trash ⊕ s12-attachment**를 대상으로 다음을 검증한다. (주의: 이번 계층에서
**s12**(첨부·이미지 파일 생명주기)가 새로 결합되며, `s04-integration-check-L1`·`s06-integration-check-L2`·
`s08-integration-check-L3`·`s11-integration-check-L4`는 이 체크포인트가 **재사용**하는 하네스일 뿐 검증 대상
feature 코드가 아니다 — s04/s06/s08/s11의 feature 코드는 존재하지 않는다.)

L5의 검증 초점은 두 개의 **계층 간 트리거**와 격리·비노출 축이다.

- **보관 이동↔완전삭제(8.6, L4↔L5)**: `s10`이 완전삭제(`purge_bundle`)나 보관 만료 스윕으로 문서를
  `deleted`로 전이시키면 `s12` `ArchivalSweepService`가 그 관측 가능한 결과를 스캔해 연결된 미보관 첨부를
  워크스페이스 보관 폴더로 **이동**(`is_archived=true`)하되 물리 삭제는 없다(INV-4). deleted 전이는 s10/s07이
  수행하고 s12는 관측·조정만 한다(의존 방향 준수).
- **참조 소멸↔버전 저장(8.7, L4↔L5)**: `s09`가 새 버전을 저장해 현재 버전 본문이 이미지 참조를 잃으면 `s12`가
  현재 버전 참조를 관측해 그 이미지를 보관 이동하되, 아직 어떤 저장 버전에도 반영되지 않은 새 붙여넣기
  (`attachment.created_at > current_version.created_at`)는 오아카이브하지 않는 **붙여넣기 보호**를 지킨다.
- **격리·비노출 축**: 첨부 저장·보관 폴더의 WS 격리(8.3·8.8, INV-6)와 **보관된 첨부의 role 무관 404**(권한
  판정 이전 차단, admin 포함, 8.9·8.10, INV-7)를 관찰한다. 조정 항목으로 `s12`가 `s01` `Settings`에 additive로
  추가한 `attachment_archive_root`·`attachment_sweep_interval_seconds`·`attachment_max_bytes`와 아카이브
  스케줄러 lifespan 결합이 `s01` Settings 로딩·앱 부팅을 회귀시키지 않는지 실제 부팅으로 확인한다.

대조의 유일한 기준은 개별 spec(s02·s03·s05·s07·s09·s10·s12) design이 아니라 **s01 단일 소스**
(§Physical Data Model `attachment`(`workspace_id`·`document_id`·`file_path`·`original_name`·
`kind ENUM('image','file')`·`is_archived`·인덱스) · §API Endpoint Catalog 32~33 · §Errors 코드 카탈로그 ·
§Invariants Catalog INV-1·2·3·4·6·7 · §Common/Permissions `Role`·`require_ws_role`·admin bypass ·
§Base Schemas `ORMReadModel`·`Page` · §Settings `file_storage_root` + additive 확장)다(Req 1.2).

**mock 없음(Req 1.1)**: 모든 검증은 실제 결합 상태 — 마이그레이션이 적용된 실제 MySQL 8 +
`create_app()`로 부팅된 실제 애플리케이션(s02·s03·s05·s07·s09·s10 + **s12 첨부 라우터 + 아카이브 스케줄러
조립**) + 실제 서명 쿠키 세션 + 실제 `workspace_member`·`document`·`document_version`·`attachment` 데이터 +
실제 파일시스템 저장/보관 폴더(`file_storage_root`·`attachment_archive_root`) + 실제 `DocumentStateEngine` +
실제 `RetentionSweepService` + 실제 `ArchivalSweepService` — 에서 수행한다. stub·가짜 구현을 쓰지 않는다.
조정 서비스·스윕·엔진 직접 호출(`now` 주입 포함)은 실제 s12·s10·s07 코드 실행이므로 mock이 아니다(Req 1.6).

**feature 미구현(Req 1.3)**: 이 체크포인트는 어떤 엔드포인트·서비스·스키마·마이그레이션·상태 엔진·조정
서비스·스케줄러도 신규로 구현하지 않는다. 소유물은 `tests/integration_L5/` 테스트 자산과 본 문서(게이트
기록)뿐이며, `s11` `tests/integration_L4/`(및 그것이 재사용하는 L3/L2/L1) 하네스는 **재사용·확장**한다(하위
하네스 무수정, Req 1.4).

## 2. 검증되는 것 (Req 2~7 스위트)

| 요구 | 태스크 | 검증 관심사 | 스위트 파일 |
|------|--------|-------------|-------------|
| Req 2 | 2.1 | 누적 계약 대조(attachment 스키마·API 32~33·`AttachmentRead`/`AttachmentCreate`·에러 모델·Base 규약·참조 URL·Settings additive 로딩·아카이브 스케줄러 결합 부팅) | `test_cumulative_contract_conformance.py` |
| Req 3 | 2.2 | 첨부 생성·서빙·WS 격리 흐름(이미지 붙여넣기 파일 저장 8.1·파일 첨부 8.2·WS 격리 저장 8.3·viewer 서빙·업로드/서빙 게이팅 INV-1·2·6) | `test_attachment_lifecycle_flow.py` |
| Req 4 | 2.3 | 보관 이동↔완전삭제 8.6(완전삭제·보관 만료 → deleted 관측 → 보관 이동·물리삭제 부재 INV-4·관측 판정·멱등·묶음 범위) | `test_purge_archive_combination.py` |
| Req 5 | 2.4 | 참조 소멸↔버전 저장 8.7(저장 참조 소멸 이미지 보관 이동·현재참조 유지 미보관·붙여넣기 보호·관측 판정·이미지 한정) | `test_save_dereference_combination.py` |
| Req 6 | 2.5 | 보관 격리·비노출 INV-7(role 무관 404·admin 포함·권한 판정 이전 차단·보관 WS 격리·복원 경로 부재·단조 증가) | `test_archive_isolation.py` |
| Req 7 | 2.6 | 아래 계층 결합 엣지(role별 접근 경계·admin override·WS 격리 INV-6·삭제 사용자 첨부 보존·로그인 게이트·물리 삭제 부재 INV-4) | `test_combination_layer_edge.py` |

> 위 6개 스위트가 Req 2~7을 담당하며, `test_harness_smoke.py`·`test_helpers_smoke.py`는 L5 하네스(L4 하네스
> 재사용·확장 + 첨부 업로드/서빙 시나리오·`now` 주입 아카이브 스윕·파일시스템 관찰 픽스처, 첨부 업로드·조회·
> 이미지 참조 저장·아카이브 스윕·파일 관찰 헬퍼)의 자체 점검이다. 게이트 판정은 스위트 전체(전체
> `tests/integration_L5`)의 실행 결과로 집계된다.

현 시점 테스트 분포(관측값, 총 **56**): 계약 대조 24 · 첨부 생명주기 흐름 6 · 보관 이동↔완전삭제 4 · 참조
소멸↔버전 저장 5 · 보관 격리·비노출 5 · 아래 계층 결합 엣지 4 · 하네스 스모크 5 · 헬퍼 스모크 3.

## 3. 실행 방법

```bash
# backend/ 디렉터리에서
uv run pytest tests/integration_L5
```

**전제 조건(env prerequisites)**:
- 실제 MySQL 8이 가용해야 하며 Alembic 마이그레이션(`uv run alembic upgrade head` 상당)이
  하네스(`conftest.py` — L4/L3/L2/L1 하네스 재사용)에 의해 적용된다.
- 부팅 앱은 s02·s03·s05·s07·s09·s10 + **s12 첨부 라우터 + 아카이브 스케줄러가 조립된 상태**여야 한다
  (첨부 업로드·서빙 라우트 노출, lifespan 아카이브 스케줄러 훅 결합).
- 실제 파일시스템 저장/보관 폴더(`Settings.file_storage_root`·`attachment_archive_root`)가 가용해야 한다
  (저장/보관 파일 존재·부재·WS 경로 격리 관찰).
- 실제 `DocumentStateEngine`·`RetentionSweepService`·`ArchivalSweepService`를 부팅 앱과 동일 DB 세션으로 직접
  호출한다(스윕은 `now` 주입으로 결정성 확보, 스케줄러 job 대기·실시간 sleep 없음). **mock 금지.**

**DB 미가용·부팅 앱 미충족·파일시스템 미가용·아카이브 스케줄러 결합 미충족은 스킵이 아니라 실패(FAILURE)로
처리한다** — 미검증이 통과로 오인되는 것을 막기 위함이다(Req 8.4, §4.4·design §GateVerdict · Testing Strategy).

## 4. G-1 게이트 판정 기준

### 4.1 통과/미통과 조건 (Req 8.1, 8.2)

- **G-1 통과 조건**: `uv run pytest tests/integration_L5` 전체(Requirement 2~7 스위트 — §2 표의 6개 스위트 +
  하네스/헬퍼 스모크)가 **전부 green**이면 G-1 통과다(Req 8.1).
- **G-1 미통과 조건**: 위 실행에서 **하나라도 실패하면** G-1 미통과이며, L6(`s14-sharing`) impl 착수는
  **차단**된다(Req 8.2).
- **판정의 권위**: 판정은 이 문서의 선언이 아니라 위 명령의 실행 결과에서 **파생(derived)**된다. 전부 통과한
  실행 그 자체가 곧 판정이다(design §GateVerdict — 수동 선언 금지).

### 4.2 L6 게이팅 (roadmap §게이트 G-1)

- **G-1 통과 = L6 착수 선행 조건 충족**: L6(`s14-sharing`) impl 착수의 전제 조건이 충족된다. 특히 s14는
  L5에서 검증된 s12의 첨부 저장·서빙·격리 계약(카탈로그 32~33·`/attachments/{id}` 참조 URL·보관=비노출) 위에
  공유 링크 경유 파일 접근(8.4·8.5, 카탈로그 행 37)을 얹으므로, 이 게이트 통과는 그 소비 계약이 라우터·스윕·
  보관 경계 밖에서 불변식을 유지함을 확인한 상태를 보장한다.
- **G-1 미통과 = L6 착수 차단**: 위 스위트 중 하나라도 실패하면 L6 impl 착수가 금지된다.
- roadmap 원칙(§게이트): 각 `integration-check-L{n}`은 바로 위 계층(`n+1`) impl 착수의 선행 조건이다.

### 4.3 실패 처리 원칙 — origin-spec 수정 (Req 1.5 · design §Out of Boundary)

검증이 실패하면 **원인 upstream spec(s01/s02/s03/s05/s07/s09/s10/s12)에서 수정하고 재실행**한다. 체크포인트는
계약·경계 회귀를 **포착·보고만** 하며, 위반을 우회하기 위해 feature 로직이나 테스트 기대치를 바꾸지 않는다.
실패 유형별 지목:

- 계약 드리프트(attachment 컬럼·인덱스/카탈로그 32~33/에러 형태/`AttachmentRead`·참조 URL/Settings additive
  로딩·스케줄러 결합 부팅 불일치) → 계약 대조 스위트 실패 → s01(스키마·카탈로그) 또는 원인 spec(s12) 수정.
- 첨부 흐름 회귀(이미지 base64 인라인 저장·`kind` 오기록·WS 격리 저장 누락·서빙 게이팅 오작동·문서 기준 WS
  확정 미준수) → 첨부 생명주기 스위트 실패 → s12(저장·서빙·게이트)·s07(문서→WS 어댑터)·s05(멤버십) 중 원인 수정.
- 보관 이동↔완전삭제 회귀(deleted 문서 첨부 미이동·물리 삭제 발생·비deleted 문서 첨부 오이동·멱등 위반·묶음
  범위 누출) → 보관 이동↔완전삭제 스위트 실패 → s12(스윕)·s10(완전삭제/보관 만료)·s07(엔진) 중 원인 수정.
- 참조 소멸↔버전 저장 회귀(현재 참조 이미지 오아카이브·붙여넣기 보호 미준수·참조 유지 이미지 오이동·파일 첨부
  오이동) → 참조 소멸↔저장 스위트 실패 → s12(`ReferenceScanner`·스윕)·s09(저장=버전 생성) 중 원인 수정.
- 보관 격리·비노출 회귀(보관 첨부 노출·role별 응답 분기·권한 판정 이후 차단·보관 WS 경로 누출·복원 경로 존재·
  자동 정리) → 보관 격리 스위트 실패 → s12(보관 비노출·영구성 규약) 수정.
- 결합 엣지 회귀(role 경계 불성립·admin override 실패·다른 WS 첨부 노출·삭제 사용자 첨부 소실·로그인 게이트
  미차단·물리 삭제 발생) → 엣지 스위트 실패 → s02/s03/s05(세션·계정·멤버십)·s12(첨부→WS 어댑터) 중 원인 수정.

### 4.4 환경 미충족 = 실패, 스킵 아님 (Req 8.4)

검증 대상 환경(마이그레이션된 MySQL 8 · 부팅 앱 · 파일시스템 저장/보관 폴더 · 아카이브 스케줄러 결합)이
미충족이면 이를 **스킵이 아니라 실패로 처리**한다. 미검증(unverified)이 게이트 통과로 오인되어서는 안 된다.
하네스는 DB 미가용·부팅 실패·파일시스템 미가용·스케줄러 결합 실패 시 에러/실패로 노출하며, 그런 실행은 G-1
통과 근거가 될 수 없다.

## 5. 재검증 트리거 (Req 8.3 · design §Revalidation Triggers · roadmap §재검증 트리거)

`s01`·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·`s12` 중 **하나라도 아래 계약 표면이 수정되면**, 이 체크포인트 **및
로드맵상 이후 모든 체크포인트(L6)**를 누적 집합 기준으로 **재실행**해야 한다. 재실행 시에도 mock 없이 실제
구현을 결합한 상태로 검증한다. **s01(계약) 수정 시에는 모든 체크포인트(L1~L6)를 재실행**한다.

- **s01(계약) 수정 시** — 모든 체크포인트 재실행:
  - `attachment` 스키마(컬럼·인덱스·`kind ENUM('image','file')`·`is_archived`·`file_path`·`original_name`·FK)
  - 카탈로그 행 32~33 경로·메서드·요구 role·요청/응답 스키마 이름(`AttachmentCreate`·`AttachmentRead`)·참조
    URL 규약(`/attachments/{id}`)
  - 권한 resolver(`Role` 위계·`require_ws_role`·admin bypass) 시그니처·판정 규칙
  - 세션 인증 의존성(`get_current_user`/`AuthContext`)
  - 공통 에러 응답·에러 코드 카탈로그(401/403/404/422)
  - `Settings` 스키마(특히 `file_storage_root` 및 additive `attachment_archive_root`·
    `attachment_sweep_interval_seconds`·`attachment_max_bytes` 확장 계약)·단일 접근자
  - 불변식 카탈로그(INV-1·2·3·4·6·7)
- **s12(attachment) 수정 시** — L5 및 이후 체크포인트 재실행:
  - 첨부 엔드포인트(행 32~33) 계약, 첨부 참조 URL 규약(`/attachments/{id}`)
  - 완전삭제 반응 보관 이동(8.6) 판정 기준(deleted 관측), 참조 소멸 아카이브(8.7) 판정 기준(현재 버전 참조·
    붙여넣기 보호 `created_at` 경계)
  - 보관 폴더 격리·비노출·영구성 규약(보관 첨부 서빙 차단·복원 불가·role 무관 404·권한 판정 이전 차단)
  - `attachment_archive_root`·`attachment_sweep_interval_seconds`·`attachment_max_bytes` Settings 필드 규약,
    아카이브 스케줄러 결합(lifespan 기동/미기동, `>0`/`<=0` 분기)
- **s09(lock-version) 수정 시** — 해당 계층 이후 모든 체크포인트 재실행:
  - 저장 = 새 `document_version` 생성·`current_version_id` 갱신 계약(8.7 참조 관측 근거)
- **s10(trash) 수정 시** — 해당 계층 이후 모든 체크포인트 재실행:
  - 완전삭제(`purge_bundle`)·보관 만료의 `deleted` 전이 규약(8.6 관측 근거), retention 스윕 계약
- **s07(document-core) 수정 시** — 해당 계층 이후 모든 체크포인트 재실행:
  - 문서→WS 어댑터·`DocumentRepository.load_current_content`/`get_workspace_id`, 상태 엔진 primitive
    (`purge_bundle`·`identify_bundles` 등 deleted 유발 경로)
- **s02(auth) 수정 시** — 해당 계층 이후 모든 체크포인트 재실행:
  - 로그인/세션 게이트(삭제 사용자 후속 첨부 요청 401 차단에 영향)·세션 write/clear·payload 키
- **s03(admin-account) 수정 시** — 해당 계층 이후 모든 체크포인트 재실행:
  - 계정 상태(`is_active`/`is_deleted`) 표현·전이 동작(첨부 업로더 삭제 후 레코드 보존 검증에 영향)
- **s05(workspace) 수정 시** — 해당 계층 이후 모든 체크포인트 재실행:
  - `workspace_member` role 판정 데이터 계약 · resolver 활성화 방식(첨부 업로드·서빙 게이팅 판정 근거)

## 6. 현재 판정 (verdict, 2026-07-18 관측)

**게이트 통과 — 56 passed.** L6(`s14-sharing`) impl 착수 선행 조건 충족.

| 실행 | 명령 | 요약 |
|------|------|------|
| L5 게이트 run 1(권위) | `uv run pytest tests/integration_L5` | `56 passed, 472 warnings in 58.04s` |
| L5 게이트 run 2(안정성 재확인) | `uv run pytest tests/integration_L5` | `56 passed, 472 warnings in 58.52s` |

두 차례 연속 전량 green으로 게이트 통과가 안정적으로 재현됨을 확인했다(계약 대조 24 · 첨부 생명주기 흐름 6 ·
보관 이동↔완전삭제 4 · 참조 소멸↔버전 저장 5 · 보관 격리·비노출 5 · 아래 계층 결합 엣지 4 · 하네스 스모크 5 ·
헬퍼 스모크 3 = 56). 이 수치는 선언이 아니라 명령 재실행으로 재현·갱신되는 **관측값**이다. upstream
(s01·s02·s03·s05·s07·s09·s10·s12) 수정 시 §5 재검증 트리거에 따라 재실행하고 본 §6 판정을 최신 관측으로
갱신한다.

## 참조

- 요구사항: `.kiro/specs/s13-integration-check-L5/requirements.md` (Req 1.5, 8.1, 8.2, 8.3, 8.4)
- 설계: `.kiro/specs/s13-integration-check-L5/design.md`
  (§Components → GateVerdict, §Boundary Commitments → Revalidation Triggers, §Testing Strategy)
- 대조 기준 단일 소스: `.kiro/specs/s01-contract-foundation/design.md`
  (§Physical Data Model `attachment` · §API Endpoint Catalog 32~33 · §Errors · §Invariants Catalog
  INV-1·2·3·4·6·7 · §Common/Permissions · §Base Schemas · §Settings `file_storage_root`)
- 검증 대상 동작: `.kiro/specs/s12-attachment/design.md`(첨부 업로드·서빙·`AttachmentStorage`·
  `ArchivalSweepService`(8.6·8.7)·`ReferenceScanner`·`ArchivalScheduler`·Settings additive 확장)·
  `.kiro/specs/s10-trash/design.md`(완전삭제·보관 만료 deleted 전이)·`.kiro/specs/s09-lock-version/design.md`
  (저장=버전 생성)·`.kiro/specs/s07-document-core/design.md`(`DocumentStateEngine`·문서→WS 어댑터)
- 재사용 하네스: `.kiro/specs/s11-integration-check-L4/design.md`·`backend/tests/integration_L4/`,
  및 그것이 재사용하는 L3(`backend/tests/integration_L3/`)·L2(`backend/tests/integration_L2/`)·
  L1(`backend/tests/integration_L1/`) 하네스
- 게이트·재검증 트리거: `.kiro/steering/roadmap.md` (§게이트 · §재검증 트리거 · §Shared seams to watch)
