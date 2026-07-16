# Research & Design Decisions — s09-lock-version

## Summary
- **Feature**: `s09-lock-version`
- **Discovery Scope**: Extension (기존 `s01` 계약·`s07` 문서 도메인 위에 잠금·버전 동작을 얹는 통합 중심)
- **Key Findings**:
  - lock 필드(`lock_user_id`·`lock_acquired_at`)와 `document_version` 스키마는 `s01`이 이미 확정했고
    `s07`은 이를 **인정만** 하고 값 설정을 위임했다. 따라서 `s09`는 새 마이그레이션·새 컬럼 없이 기존 스키마
    위에서 쓰기 경로만 채운다.
  - API 카탈로그 행 24~28(lock/save/cancel/force-unlock/versions)이 경로·메서드·요구 role까지 고정되어
    있어 계약은 이미 결정적이다. `s09`는 동작만 구현하고 카탈로그를 바꾸지 않는다.
  - 잠금·삭제 독립(§4.3)은 단방향이 아니라 **양방향 무간섭**으로 해석하는 것이 가장 단순하고 회귀에 강하다:
    `s07` 엔진이 lock을 검사하지 않듯, `s09` 잠금·버전 동작도 문서 `status`를 게이팅하지 않는다.

## Research Log

### 잠금 상태 가시성(“다른 사용자가 편집 중” 표시)의 계약 경로
- **Context**: REQ-5.2는 타인 잠금 시 편집 시작 차단과 "다른 사용자가 편집 중" 표시를 요구한다. 그러나
  `s07` `DocumentRead`에는 lock 필드가 포함되어 있지 않고, 카탈로그(행 24~28)에 잠금 상태 조회용 GET
  엔드포인트가 없다.
- **Sources Consulted**: `s01/design.md` §API Catalog(행 24~28)·§에러 코드 카탈로그(409 = "잠금 보유자
  충돌"), `s07/design.md` `DocumentRead` 필드, `docs/projects.md` §4.3.
- **Findings**:
  - `s01` 에러 카탈로그가 **409 conflict의 예시로 "잠금 보유자 충돌"을 명시**한다 → 타인 잠금 시 편집
    시작(`POST /lock`)은 409로 표면화하는 것이 계약 정합적이다.
  - 별도 GET 잠금-상태 엔드포인트를 추가하면 카탈로그 변경(재검증 트리거)이므로 도입하지 않는다.
- **Implications**: "편집 중" 표시는 (1) `POST /lock`의 409 응답(성공 시 반환하는 `DocumentLockRead`가
  담는 보유자 정보를 에러 메시지로 전달)로 충족한다. 잠금-상태 상시 표시가 필요하면 향후 `s07`
  `DocumentRead` 확장(계약 변경)으로 다뤄야 하며 `s09` 범위 밖이다.

### 과거 버전 본문 열람 및 rollback 경계
- **Context**: `docs/projects.md` §2.5는 "버전 열람 UI 제공 여부는 design 단계 판단"이라 하고, §6은 rollback
  미도입을 확정한다.
- **Findings**: 카탈로그에는 `GET /documents/{id}/versions`(목록)만 있고 과거 버전 **본문** 조회 엔드포인트는
  없다. rollback도 없다. 현재 버전 본문은 `s07` `GET /documents/{id}`의 `content_html`로 이미 열람된다.
- **Implications**: `DocumentVersionRead`는 **메타데이터 전용**(식별자·저장자·저장 시각)으로 정의한다. 과거
  버전 본문 노출은 새 엔드포인트가 필요하므로 계약 변경이 되어 범위 밖이다. 목록에 본문을 싣지 않으면
  MEDIUMTEXT 대량 전송도 피할 수 있다.

### 문서→workspace_id 게이팅 재사용
- **Context**: `/documents/{id}/*` 경로는 문서 id로 workspace_id를 조회해 `require_ws_role`에 주입해야 한다.
- **Findings**: `s07`이 `dependencies.py`에 `ws_role_for_document(minimum: Role)` 어댑터를 이미 제공하고,
  steering `structure.md`는 권한 검사 재구현을 금지한다.
- **Implications**: `s09`는 `s07`의 문서→WS 어댑터를 재사용한다(자체 어댑터 신설 금지). role만 파라미터로
  바꿔 lock/save/cancel=EDITOR, force-unlock=OWNER, versions=VIEWER를 게이팅한다.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 단일 feature 모듈 `app/lock_version/`(선택) | 레이어드(schemas→repository→service→router), 단일 `LockVersionService`가 5개 동작 담당 | 잠금·저장이 강결합(save=버전+잠금해제)이라 한 서비스에 두는 편이 응집 높음. 작은 spec 크기 유지 | 서비스가 read(목록)+write(잠금)를 함께 가짐 → 메서드 분리로 완화 | steering 레이어드·단일 구현 원칙 정렬 |
| 잠금/버전 서비스 분리(2개) | `LockService` + `VersionService` | 관심사 분리 | save가 두 서비스를 오케스트레이션해야 해 트랜잭션 경계가 흐려짐 | 과분해, 기각 |
| `s07` 모듈에 잠금·버전 추가 | 문서 도메인에 흡수 | 어댑터 재사용 쉬움 | `s07` 경계(상태 전이 전용)를 침범, 재검증 트리거 확대 | 경계 위반, 기각 |

## Design Decisions

### Decision: 잠금·버전 동작은 문서 status와 독립(§4.3 양방향 무간섭)
- **Context**: §4.3는 "삭제 상태와 잠금 상태는 서로 독립이며 충돌하지 않는다(잠긴 문서도 trashed/deleted
  가능)"이라 명시한다. `s09` 동작이 `status`를 게이팅해야 하는지 결정 필요.
- **Alternatives Considered**:
  1. start-edit/save를 `status=active`로 제한(비active면 409).
  2. 잠금·버전 동작을 status와 완전 독립으로 두고 문서 존재(404)만 검사.
- **Selected Approach**: (2) — 잠금 획득·저장·취소·강제 해제·목록은 문서 `status`를 검사하지 않는다. 유일한
  존재 가드는 문서 행 존재 여부(soft-delete 행도 존재하므로 404는 물리 부재에만).
- **Rationale**: `s07` 상태 엔진은 lock을 검사하지 않는다(단방향). 대칭적으로 `s09`가 status를 검사하지
  않으면 두 관심사가 완전히 디커플링되어 교차-spec 상태 결합·회귀가 사라진다. REQ-5.x 어디에도 "active만
  편집"이라는 요구가 없으므로 status 게이트를 추가하는 것은 요구 발명이다.
- **Trade-offs**: trashed 문서에 대한 저장이 이론적으로 가능하나(버전은 rollback 없는 스냅샷이라 무해),
  프론트엔드가 trashed 문서에 편집 UI를 노출하지 않으므로 실사용 충돌은 없다. 독립성 회귀 검증이 단순해진다.
- **Follow-up**: 통합 테스트에서 "잠긴 문서를 `s07` 엔진으로 trashed 전이시켜도 잠금·저장 동작이 유지됨"을 확인.

### Decision: 잠금 획득/취소/강제해제의 멱등·충돌 규칙
- **Context**: 재클릭·이탈 beacon·중복 호출에 대한 결정적 응답이 필요하다.
- **Selected Approach**:
  - 획득: 미잠금→획득(200). 동일 보유자 재요청→기존 잠금 유지 멱등 성공(200). 타인 잠금→409.
  - 저장: 보유자만 성공. 미잠금/타인 잠금→409(버전 미생성).
  - 취소: 보유자→해제(204). 미잠금→멱등 204(no-op). 타인 잠금→409.
  - 강제 해제: owner/admin→보유자 무관 해제(204). 미잠금→멱등 204.
- **Rationale**: 획득/취소/강제해제의 멱등 성공은 이탈·재시도 클라이언트 트래픽에 견고하고, 저장·취소의
  "타인 잠금→409"는 INV-9와 보유자 단일성을 강제한다. 타인 잠금 해제는 오직 force-unlock(owner)만 가능.
- **Trade-offs**: 취소를 멱등(미잠금 시 204)으로 두어 이탈 처리에 관대하되, 타인 잠금은 엄격히 409로 막는다.

### Decision: 저장의 원자적 트랜잭션 순서(순환 FK 회피)
- **Context**: `document.current_version_id`는 `document_version(id)`를 참조하는 nullable FK(순환은 nullable로
  회피, `s01`).
- **Selected Approach**: 단일 트랜잭션에서 (1) `document_version` insert → flush로 새 id 확보 → (2)
  `document.current_version_id = new_id`·`lock_user_id/at = NULL` 갱신 → (3) commit.
- **Rationale**: 버전 생성·current 갱신·잠금 해제가 한 트랜잭션이라 부분 적용이 없다(REQ-2.4). flush로 순환
  FK를 안전하게 채운다.
- **Follow-up**: 저장 실패 시 롤백으로 버전 미생성·잠금 유지가 보장되는지 테스트.

### Decision: `DocumentVersionRead` 메타데이터 전용
- **Context**: 목록에 본문(MEDIUMTEXT)을 실을지 여부.
- **Selected Approach**: `DocumentVersionRead = {id, document_id, created_by, created_at}`(본문 제외). 저장
  응답·목록 항목 모두 동일 스키마.
- **Rationale**: 과거 버전 본문 조회 엔드포인트가 없고 rollback도 없으므로 본문이 불필요하다. 목록 경량화.

## Risks & Mitigations
- **위험: 잠금 획득 경합(두 요청이 동시에 미잠금 문서를 잠금)** — 두 요청이 동시에 `lock_user_id=NULL`을
  읽고 각각 자신으로 설정하면 INV-9가 깨질 수 있다. **완화**: 획득 시 조건부 갱신(`UPDATE ... SET
  lock_user_id=:me WHERE id=:id AND lock_user_id IS NULL`)의 영향 행 수로 획득 성공을 판정하거나, 행 잠금
  (`SELECT ... FOR UPDATE`) 후 갱신하여 원자성을 확보한다. 구현 태스크에서 확정.
- **위험: 저장 시 잠금 보유자 검사와 갱신 사이의 경합** — 보유자 확인 후 강제 해제가 끼어들 수 있다.
  **완화**: 저장 트랜잭션에서 문서 행을 `FOR UPDATE`로 로드해 보유자 재확인 후 원자적으로 처리.
- **위험: `s07`/`s10` 모듈과의 순환 import** — `s09`가 `s07` 어댑터를 재사용하되 `s10`은 import 금지.
  **완화**: 의존 방향을 `s01`·`s07`(upstream)만으로 제한하고 `s10`/`s12`/`s14`를 import하지 않는다.
- **위험: `DATETIME` 초 단위 정밀도의 `lock_acquired_at`** — 표시·정렬 정보일 뿐 잠금 판정 근거가 아니므로
  (판정은 `lock_user_id`) 기능 영향 없음. 기록만 유지.

## References
- `.kiro/specs/s01-contract-foundation/design.md` — document/document_version 스키마, 카탈로그 행 24~28,
  에러 모델(409=잠금 충돌), Base Schemas, `require_ws_role`, INV-9 매핑.
- `.kiro/specs/s07-document-core/design.md` — 문서 도메인, 문서→WS 어댑터(`ws_role_for_document`), 상태·잠금
  독립(§4.3·9.4·9.5), `DocumentRepository`/`DocumentStateEngine`.
- `docs/projects.md` — §2.4 document·§2.5 document_version, §3 REQ-5, §4.3 편집 잠금 상태, §5 INV-9, §6 범위 밖.
