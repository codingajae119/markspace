# Research & Design Decisions — s14-sharing

## Summary
- **Feature**: `s14-sharing`
- **Discovery Scope**: Complex Integration (최상위 L6 — 계약 s01·게이트 s05·문서 상태/렌더 s07·첨부 서빙 s12를 결합한 종단)
- **Key Findings**:
  - 재발급 통일 원칙(INV-8·§4.5)의 구현 핵심은 **"토글만 상태 기반 예외, 그 외 무효화는 새 토큰 재발급"** 을
    단일 boolean(`is_enabled`)으로는 구분할 수 없다는 점이다. 토글 off와 상태/게이트 무효화가 모두 `is_enabled=false`
    이면 재활성 시 이전 URL이 되살아나 7.9(복구 시 재발급 필요)를 위반한다. 해결책은 **무효화(retire) 시 토큰을
    교체**해 이전 URL을 물리적으로 소멸시키는 것이다. 토글은 토큰을 유지하고, retire·재발급은 새 토큰을 만든다.
  - 무효화 판정은 s12와 동일한 제약을 받는다: 하위 계층(s05 게이트·s07/s10 상태 전이)은 상위 계층(s14)을 import할
    수 없고 s01에 이벤트 버스가 없다. 따라서 s14는 문서 `status`·워크스페이스 `is_shareable`라는 **관측 가능한 결과**
    를 근거로 무효화한다. 다만 공유는 **실시간 보안**이 필요하므로(공개 GET), 관측을 **공개 접근 시점 실시간 게이트**
    + **주기 조정 스윕(retire 영구화)** 의 이중 구조로 구현한다.
  - `share_link` 스키마(`document_id`·`token` UNIQUE·`is_enabled`·`created_at`)·카탈로그 행 34~37·INV-8은 `s01`이
    이미 소유. 문서 active 하위 질의(`active_descendants`)·안전 렌더(`MarkdownRenderer`)는 `s07`, 첨부 서빙·보관
    404는 `s12`가 소유. 새 마이그레이션 불필요. 토큰 바이트 길이·무효화 스윕 주기만 `s01` 단일 Settings에 additive 확장.

## Research Log

### 재발급 통일 원칙(INV-8·§4.5)을 단일 boolean 스키마로 구현하는 방법
- **Context**: 브리프가 "토글만 상태 기반, 그 외는 재발급"을 명시하고, 7.7(토글 동일 링크)·7.8(trashed 즉시 무효)·
  7.9(복구 시 재발급)·7.10(게이트 off 즉시 무효·재 on 시 재발급)·INV-8(무효화 링크 재발급 없이 접근 불가)을 요구한다.
  `s01` `share_link` 스키마에는 `is_enabled`(단일 boolean) + `token` + `created_at`만 있고 "retired" 컬럼이 없다.
- **Sources Consulted**: `.kiro/specs/s01-contract-foundation/design.md`(share_link 스키마·INV-8 매핑 "is_enabled +
  재발급 계약 §4.5"), 브리프 §Approach·§Constraints, `docs/projects.md` §4.5 재발급 통일.
- **Findings**:
  - 토글 off(`is_enabled=false`, 토큰 유지)와 상태/게이트 무효화가 모두 `is_enabled=false`로만 표현되면, 재활성
    가능성에서 둘을 구분할 수 없다. 무효화 후 문서가 복구되고 게이트가 켜진 뒤 토글 on을 하면 **이전(발행된) 토큰**이
    되살아나 7.9·INV-8을 위반한다.
  - 스키마에 컬럼을 추가하면 `s01` 계약 변경(모든 체크포인트 재검증 트리거). 회피가 바람직.
- **Findings / 결정**: **무효화(retire) 시 `is_enabled=false` + 토큰 교체**로 이전 토큰을 물리적으로 소멸시킨다.
  이후 문서 복구·게이트 재활성 시에도 이전 URL은 DB에 존재하지 않아 어떤 조작으로도 되살아나지 않는다(INV-8). 다시
  공유하려면 발급(POST)이 **새 토큰**을 만든다(재발급). 토글(PATCH)은 토큰을 유지한 채 `is_enabled`만 전환하는
  유일한 상태 기반 예외(7.7)이며, retire된 링크는 이전 토큰이 이미 소멸했으므로 토글로 이전 URL을 되살릴 수 없다.
- **Implications**: `ShareLinkRepository`에 `upsert_reissue`(새 토큰)·`set_enabled`(토큰 유지)·`retire`(토큰 교체)를
  분리 소유. 컬럼 추가·마이그레이션 없이 INV-8을 만족. 재발급/토글/무효화의 토큰 정책이 계약(재검증 트리거)이 된다.

### 무효화 판정 메커니즘 — 실시간 게이트 + 관측 기반 조정 스윕(이중 구조)
- **Context**: 7.8·7.10은 문서 trashed·게이트 off 시 **즉시** 무효를 요구(보안). 그러나 s05/s07/s10은 s14를 모른다.
  s12는 동일 제약에서 결과적 일관성(스윕) 조정을 택했으나, 공유는 공개 GET의 실시간 접근 차단이 보안상 필수다.
- **Sources Consulted**: `.kiro/specs/s12-attachment/design.md`·`research.md`(관측 기반 조정 vs 동기 콜백·이벤트 버스
  기각), `.kiro/specs/s07-document-core/design.md`(`active_descendants`·엔진은 s14를 import 안 함), `.kiro/specs/
  s05-workspace/design.md`(게이트 소유), `.kiro/specs/s01-contract-foundation/design.md`(이벤트 버스 없음).
- **Findings / 결정**:
  - **실시간 게이트(공개 접근 시점)**: `GET /public/{token}`·`GET /public/{token}/attachments/{aid}`에서 유효성 =
    `is_enabled` AND 문서 status=active AND 게이트 on을 **접근마다 라이브로 관측**한다. 문서 trashed·게이트 off면
    스윕 주기와 무관하게 즉시 404(7.8·7.10·8.5, INV-8 while-invalid).
  - **lazy retire**: 공개 접근이 무효 조건(문서 비active·게이트 off)을 관측하면, 그 자리에서 `retire`(토큰 교체)로
    영구화한다. 접근이 없는 무효화 창을 닫기 위해 **주기 조정 스윕**(`ShareInvalidationSweep`)도 동일 조건을 스캔해
    활성 링크를 retire한다(멱등). 둘 다 같은 `retire` primitive를 쓴다.
  - 재활성 방향: retire가 토큰을 교체하므로 복구·게이트 재 on 후에도 이전 토큰은 소멸해 있고, 재공유는 발급(POST)
    재발급으로만 가능(7.9·7.10).
- **Implications**: while-invalid 보장(INV-8의 핵심)은 실시간 게이트가 스윕 주기와 무관하게 보장한다. "재발급 필요"
  영구화(7.9·7.10)는 lazy retire + 조정 스윕이 담당한다. 스윕/스케줄러 분리·엔트리포인트는 `s10`/`s12` 패턴 재사용
  (신규 의존성 없음). 미세 경합(무효화 창 안에서 접근이 전혀 없고 스윕 이전에 복구되는 경우)은 다음 스윕/접근에서
  영구화되며, while-invalid 접근 차단은 이미 실시간으로 보장된다.

### 동적 active 하위 계층 노출(7.5·7.6)
- **Context**: 공개 접근 시 문서 + 현재 active 하위를 표시하고, 하위 추가를 동적으로 반영해야 한다.
- **Sources Consulted**: `.kiro/specs/s07-document-core/design.md`(`DocumentStateEngine.active_descendants`는 삭제
  캐스케이드와 s14 공유 렌더가 공용하는 primitive, 9.3), 카탈로그 행 36.
- **Findings / 결정**: s14는 별도 스냅샷을 저장하지 않고 **접근 시점**에 `s07` `active_descendants(root)`로 현재
  active 하위를 동적 수집한다. 새 하위가 추가되면 다음 접근에서 자동 포함되고, 하위가 trashed되면 자동 제외된다
  (7.5·7.6). 본문은 `s07` `MarkdownRenderer`로 안전 렌더(3.2).
- **Implications**: 공유 범위는 별도 테이블·컬럼이 아니라 s07 primitive의 파생 질의. `active_descendants` 규약 변경은
  s14 소비에 영향(s07 상위 트리거).

### 공개 렌더의 첨부 참조 URL 재작성(8.4)
- **Context**: `s07` 렌더는 첨부를 `s12` 규약 `/attachments/{id}`(인증 필요)로 참조한다. 공개 링크에서는 인증 없이
  이미지가 로딩돼야 한다(8.4).
- **Sources Consulted**: `.kiro/specs/s12-attachment/design.md`(참조 URL 규약 `/attachments/{id}`·`ReferenceScanner`
  경계), 카탈로그 행 33·37.
- **Findings / 결정**: 공개 렌더 시 `content_html`의 `/attachments/{id}` 참조를 **링크 스코프 경로**
  `/public/{token}/attachments/{id}`로 재작성한다. 그러면 공개 이미지가 행 37 경로로 로딩되어 링크 유효성·서브트리
  소속·보관 규약이 파일에도 일관 적용된다(8.4·8.5). id 경계(`/attachments/12` ≠ `/attachments/123`)를 정확히 구분한다.
- **Implications**: `PublicShareService`가 재작성 규약을 소유. 원 규약(`/attachments/{id}`)은 `s12` 소유이며 s14는
  소비·재작성만 한다. 재작성 규약 변경은 s14 재검증 트리거.

### 링크 경유 첨부 서빙 — s12 재사용과 서브트리·격리 검사(8.4·8.5·INV-6)
- **Context**: 공유 문서(및 active 하위)에 속한 첨부만 링크 경유로 서빙하되, 게이트·문서 status·보관·WS 격리로 차단.
- **Sources Consulted**: `.kiro/specs/s12-attachment/design.md`(`AttachmentService.serve_attachment`는 보관·부재를
  role·경로 무관 404로 처리·스트리밍, `AttachmentRepository.get`), 카탈로그 행 37, INV-6.
- **Findings / 결정**: s14는 (1) 링크 유효성(게이트·status)을 실시간 검사(무효→404, 8.5), (2) 첨부가 공유 문서 또는
  그 현재 active 하위에 속하고 동일 워크스페이스인지 검사(범위·격리→404, INV-6), (3) 실제 바이너리·보관 차단은
  `s12` `serve_attachment`에 위임한다(보관 404 재사용, 8.5). 저장·격리·보관 판정은 재구현하지 않는다(7.7).
- **Implications**: 보관 차단(8.5의 archived 부분)을 s12 규약 그대로 상속. s14는 공개 authorization(토큰·서브트리·
  격리)만 추가. s12 서빙 계약 변경은 s14 재검증 대상.

### 공개 경로 정보 비노출(INV-8)
- **Context**: 공개 경로가 무효 링크·미존재 토큰·범위 밖 첨부를 구분해 응답하면 토큰·문서 존재를 추정당할 수 있다.
- **Findings / 결정**: 공개 경로(행 36~37)의 모든 접근 거부(무효 링크·미존재 토큰·범위 밖·보관 첨부·부재)를 **일관되게
  404**로 매핑한다. 410/403을 쓰지 않아 존재·무효 사유를 드러내지 않는다.
- **Implications**: `PublicShareService`가 거부를 단일 404로 통일. 발급/토글(인증 경로)만 403/409/401을 세분한다.

### 토큰 생성·설정
- **Context**: 추측 불가한 공유 토큰이 필요하고 `token VARCHAR(64)` 한도에 맞아야 한다.
- **Findings / 결정**: `secrets.token_urlsafe(share_token_bytes)`(기본 32바이트 → base64url 약 43자)로 생성해 64자
  한도 내에 든다. `share_token_bytes`·`share_invalidation_sweep_interval_seconds`(기본 3600, `<=0`이면 인프로세스
  스케줄러 비활성)를 `config.yml` + 공용 Settings에 additive 확장. UNIQUE 충돌 시 재생성.
- **Implications**: `ShareLinkRepository`가 토큰 생성을 단일 소유. 설정은 단일 Settings 경유(모듈별 파일 금지, 7.6).

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 실시간 게이트 + 관측 조정 스윕(선택) | 공개 접근마다 status·게이트 라이브 관측(즉시 차단) + 주기 스윕으로 retire 영구화 | while-invalid 보안을 스윕 주기와 무관하게 즉시 보장, 하위 계층 무변경·의존 방향 준수, s10/s12 스윕 패턴 재사용, 멱등 | 재활성 영구화(7.9)는 lazy retire+스윕에 의존(미세 경합은 다음 스윕/접근에 수렴) | 공개 보안 실시간성과 무효화 영구성을 모두 만족하는 유일 조합 |
| 관측 조정 스윕만(s12식) | 주기 스윕으로만 무효화 | 단순, s12와 동일 | **공개 GET 실시간 차단 불가**(스윕 이전 무효 문서/게이트 접근 노출) → 7.8·7.10·INV-8 위반 | 보안상 부적합. 기각 |
| retire 없이 is_enabled만 무효화 | 무효화도 토큰 유지·`is_enabled=false` | 스키마 단순 | 토글 off와 구분 불가 → 재활성 시 이전 URL 부활, 7.9·INV-8 위반 | 기각(재발급 통일 원칙 위배) |
| 하위 계층 동기 콜백 | s10/s07/s05가 s14 무효화를 직접 호출 | 즉시성 | **의존 방향 위반**, frozen 계약 변경, 순환 결합 | 기각(아키텍처·계약 위반) |
| s01 이벤트 버스 도입 | s01 이벤트 발행/구독, s14 구독 | 즉시성·역방향 회피 | s01 계약 확장 → **모든 체크포인트 재검증**, 범위 과다 | 기각(범위 초과, s01 소유 변경) |

## Design Decisions

### Decision: 재발급 통일 원칙을 retire=토큰 교체로 구현(스키마 무변경)
- **Context**: 토글(상태 기반 예외)과 상태/게이트 무효화(재발급 필수)를 단일 `is_enabled` boolean으로 구분해야 하나
  구분 정보가 없다. 스키마 컬럼 추가는 s01 계약 변경.
- **Alternatives Considered**: (평가표 참조) is_enabled만 무효화 / 컬럼 추가 / retire=토큰 교체.
- **Selected Approach**: 무효화 시 `is_enabled=false` + **토큰 교체**(`retire`). 발급/재발급은 새 토큰(`upsert_reissue`).
  토글은 토큰 유지(`set_enabled`). 이전 토큰은 retire로 소멸해 어떤 조작으로도 부활하지 않는다.
- **Rationale**: 컬럼 추가·마이그레이션 없이 INV-8·§4.5·7.7·7.9를 동시 만족. 토큰 교체가 "이전 URL 물리 소멸"을
  보장해 재활성 방향을 재발급으로만 한정.
- **Trade-offs**: retire된 링크는 비활성+미발행 토큰 상태로 남는다(물리 삭제 없음, INV-4). 재공유는 POST 재발급.
- **Follow-up**: 재발급 토큰이 이전 토큰과 다름·토글이 토큰을 유지함을 단위·통합 테스트로 고정(`s15` e2e).

### Decision: 무효화를 실시간 게이트 + 관측 조정 스윕의 이중 구조로 구현
- **Context**: 공개 접근은 실시간 보안 차단이 필수(7.8·7.10·8.5)이나 하위 계층은 s14를 import할 수 없다.
- **Alternatives Considered**: (평가표) 조정 스윕만 / 동기 콜백 / 이벤트 버스 / 이중 구조.
- **Selected Approach**: 공개 접근마다 `is_enabled`·문서 status·게이트를 라이브 관측해 즉시 차단(+lazy retire), 주기
  `ShareInvalidationSweep`이 동일 조건을 스캔해 활성 링크를 retire로 영구화. 스케줄러/엔트리포인트는 s10/s12 패턴 재사용.
- **Rationale**: while-invalid 보안을 스윕 주기와 무관하게 즉시 보장하면서, 재발급 필요 영구화도 확보. 의존 방향 준수·
  frozen 계약 무변경.
- **Trade-offs**: 재활성 영구화는 lazy retire+스윕에 의존(미세 경합은 다음 스윕/접근에 수렴). while-invalid 차단은 이미
  실시간 보장이므로 보안 리스크 없음.
- **Follow-up**: `s15(L6)` 체크포인트에서 무효화·재발급·링크 파일 접근을 mock 없이 e2e 재검증.

### Decision: 동적 active 하위·안전 렌더·첨부 서빙은 s07/s12 primitive 재사용
- **Context**: 상태 하위 질의·XSS 안전 렌더·첨부 보관 차단을 s14가 재구현하면 드리프트·중복이 발생한다.
- **Selected Approach**: 하위 계층은 `s07` `active_descendants`(동적 하위)·`load_current_content`·`MarkdownRenderer`
  (안전 렌더)·`s12` `AttachmentService.serve_attachment`(보관 404·스트리밍)·`AttachmentRepository.get`를 재사용.
  공개 HTML의 `/attachments/{id}` 참조만 s14가 `/public/{token}/attachments/{id}`로 재작성.
- **Rationale**: structure.md 코드 조직 원칙(상태/렌더/첨부 규칙 단일 구현 소비). INV-1·6·7 일관.
- **Trade-offs**: 상위 계약(s07/s12) 변경 시 s14 재검증. 참조 재작성 규약만 s14 신규 소유.
- **Follow-up**: 재작성 id 경계 오탐·서브트리 소속·격리·보관 차단 경계 테스트.

### Decision: 공개 경로 거부를 단일 404로 통일(정보 비노출)
- **Context**: 무효 링크·미존재 토큰·범위 밖 첨부를 구분해 응답하면 존재 추정이 가능.
- **Selected Approach**: 공개 경로(행 36~37)의 모든 거부를 404로 통일. 발급/토글(인증 경로)만 401/403/409 세분.
- **Rationale**: INV-8 정보 비노출. 토큰·문서 존재를 추정할 수 없게 한다.
- **Trade-offs**: 클라이언트가 사유를 구분하지 못하나(의도), 보안상 바람직.
- **Follow-up**: 무효/부재/범위밖이 동일 404임을 통합 테스트로 확인.

### Decision: 토큰 생성·무효화 스윕 주기를 단일 Settings에 additive 확장
- **Context**: 추측 불가 토큰과 스윕 주기 설정이 필요.
- **Selected Approach**: `config.yml` + 공용 `Settings`에 `share_token_bytes`(기본 32)·
  `share_invalidation_sweep_interval_seconds`(기본 3600, `<=0`이면 인프로세스 스케줄러 비활성) additive 추가.
  `secrets.token_urlsafe(share_token_bytes)`로 토큰 생성(64자 한도 내).
- **Rationale**: tech.md 설정 단일화 준수. 기본값 있는 additive라 기존 계약 의미 불변. 새 마이그레이션 없음.
- **Trade-offs**: s01 Settings 단일 소스를 건드리므로 s01 소유자와 조정 지점으로 명시.
- **Follow-up**: Settings 확장이 기존 부팅·필드 계약을 바꾸지 않음을 부팅/로드 테스트로 확인.

## Risks & Mitigations
- **무효화 창 미세 경합** — 무효화 후 접근이 전혀 없고 스윕 이전에 복구되는 경우, 이전 토큰이 잠시 재활성처럼 보일 수
  있으나 실시간 게이트가 무효 상태 접근을 이미 차단하며 다음 스윕/접근에서 retire로 영구화. while-invalid 보안 무영향.
- **공개 GET에서의 쓰기(lazy retire)** — 공개 읽기 경로가 무효 관측 시 write를 수행한다. 멱등(비활성 링크 제외)이며
  트랜잭션 격리로 안전. 부담이 크면 lazy retire를 생략하고 스윕에만 의존 가능(설정 주기 단축).
- **토큰 추측·열거** — `secrets.token_urlsafe`(고엔트로피) + 공개 경로 404 통일로 존재 추정 차단. 무효화는 토큰 교체로
  이전 URL 영구 소멸.
- **다중 워커 중복 스윕** — 멱등 스코프(`is_enabled=true`만 대상, retire는 토큰 교체 후 제외)로 무해화. 다중 워커 배포 시
  인프로세스 스케줄러 off + 외부 cron 단일 실행 권장(s10/s12와 동일).
- **하위 계층 계약 변경** — s07 `active_descendants`/렌더, s12 첨부 서빙·보관 404, s05 게이트 의미 변경은 해당 spec이
  상위 트리거이며 s14도 `s15` 재검증 대상(§Revalidation Triggers).

## References
- 계약 단일 소스(share_link 스키마·카탈로그 행 34~37·에러·Base Schemas·resolver·세션 인증·INV-8): `.kiro/specs/s01-contract-foundation/design.md`.
- 게이트(`is_shareable`) 소유·`require_ws_role` 실동작: `.kiro/specs/s05-workspace/design.md`.
- 문서 status·`active_descendants`·안전 렌더 규약·문서→WS 어댑터: `.kiro/specs/s07-document-core/design.md`.
- 첨부 서빙·보관 404·저장 격리·참조 URL 규약·스윕 패턴: `.kiro/specs/s12-attachment/design.md`·`research.md`.
- 상위 계약 근거: `docs/projects.md` §3 REQ-7·REQ-8.4·8.5, §4.5 재발급 통일, §5 INV-6·8.
- APScheduler: https://apscheduler.readthedocs.io/ — BackgroundScheduler 주기 실행(s10/s12가 도입).
- Python `secrets`: https://docs.python.org/3/library/secrets.html — `token_urlsafe` 고엔트로피 토큰 생성.
