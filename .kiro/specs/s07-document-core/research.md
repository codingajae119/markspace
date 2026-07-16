# Research & Design Decisions — s07-document-core

## Summary
- **Feature**: `s07-document-core`
- **Discovery Scope**: Complex Integration (신규 코어 도메인 + `s01` 계약·`s05` 권한 위에서 동작하는 상태
  전이 엔진. 하위 s10·s14가 재사용할 단일 구현 경계를 확정해야 한다.)
- **Key Findings**:
  - 상태/bundle 전이 엔진은 `s01` 스키마(`document.status`·`trashed_at`·`parent_id`·`sort_order`) 위에서
    **컬럼 추가 없이** 묶음 비흡수 모델을 구현할 수 있다. 묶음 식별을 위한 별도 `bundle_id` 컬럼은 `s01`
    계약 변경(전 체크포인트 재검증)을 유발하므로 도입하지 않고, **묶음 루트 문서 id**를 묶음 식별자로 삼는다.
  - 삭제·복구·완전삭제·묶음 식별을 **단일 엔진 서비스**로 캡슐화하고, 문서 CRUD/이동/렌더는 별도 서비스로
    분리하면 s10(휴지통 API·타이머)·s14(공유)가 규칙을 재구현하지 않고 엔진 primitive만 호출한다.
  - `docs/projects.md` §4.3에 따라 문서 상태와 편집 잠금은 서로 독립이므로, 엔진은 lock 필드를 읽거나 잠금을
    이유로 전이를 막지 않는다(잠긴 문서도 삭제/복구/완전삭제 가능). lock 필드 값 설정은 s09 소유.

## Research Log

### 묶음(bundle) 식별 — 별도 컬럼 없이 루트+trashed_at 재구성
- **Context**: §4.2 비흡수 모델은 "한 번의 삭제가 포착한 서브트리"를 묶음으로 정의한다. s10의
  `/trash/{bundleId}/restore`·`DELETE /trash/{bundleId}`가 묶음을 지칭하려면 묶음 식별자가 필요하다. `s01`
  스키마에는 `bundle_id` 컬럼이 없다.
- **Sources Consulted**: `s01/design.md` document 물리 모델(`status`·`trashed_at`·`parent_id`·`sort_order`,
  인덱스 `(workspace_id, status, trashed_at)`), `docs/projects.md` §4.2·§6.2~6.4·§5 INV-10·11.
- **Findings**:
  - 각 문서는 정확히 한 번만 trashed되므로, 묶음은 trashed 문서 집합을 분할(partition)한다.
  - 캐스케이드(6.2)는 포착한 모든 구성원에 **동일한 trashed_at**을 부여한다. 독립 자식(먼저 삭제)은
    부모보다 **먼저**(작거나 같은) trashed_at을 가진다(INV-11).
  - 따라서 묶음 루트 R = "trashed 문서 중 그 부모가 같은 묶음이 아닌 문서"이고, 묶음 구성원 = R에서 시작해
    `parent_id`를 따라 내려가며 `status=trashed`이고 `trashed_at`이 R과 같은 서브트리(연결 성분)다.
  - 묶음 식별자는 **루트 문서 id**로 노출한다(별도 컬럼 불필요). s10의 `bundleId`는 이 루트 문서 id다.
- **Implications**: 묶음 식별·열거·구성원 확정 로직을 엔진 primitive(`identify_bundles`/`get_bundle`)로 두고
  s10이 재사용한다. `(workspace_id, status, trashed_at)` 인덱스가 묶음 열거·타이머 산정을 지원한다.

### 묶음 구성원 재구성의 정밀도(precision) 경계
- **Context**: `s01` 물리 모델은 타임스탬프를 `DATETIME`으로 정의한다. 묶음 구성원을 trashed_at 동치로
  재구성할 때, 서로 다른 삭제 조작이 **동일 초(second)**에 발생하면 부모-자식 관계에서 독립 묶음이 잘못
  병합될 이론적 여지가 있다(부모를 나중에 삭제하는데 이미 trashed된 자식과 trashed_at 초가 같은 경우).
- **Findings**:
  - 정상 경로에서 INV-11은 독립 자식의 trashed_at이 부모보다 **엄격히 이르도록**(또는 같도록) 만든다. 초
    단위 동치 충돌은 매우 드문 경합이지만 0은 아니다.
  - `DATETIME(6)`(마이크로초) 등 고해상도 저장은 `s01` 스키마의 물리 정밀도 변경에 해당해 전 체크포인트
    재검증 트리거가 될 수 있어 이 spec에서 단독으로 바꾸지 않는다.
- **Selected Approach**: 엔진은 (1) 삭제 캐스케이드에서 **이미 trashed된 하위를 원자적으로 제외**하여 병합을
  구조적으로 차단하고, (2) 묶음 루트 판정을 "부모가 trashed가 아니거나 부모의 trashed_at이 자신과 다른
  경우 루트"로 정의하며, (3) 동일 트랜잭션 내 삭제 조작이 자신이 포착한 구성원 집합을 결정적으로 확정한다.
  즉 **묶음 구성원은 삭제 시점에 확정**되고, 재구성은 그 결과(연결 성분 + trashed_at)를 읽는다.
- **Follow-up / Risk**: 초 단위 정밀도로 인한 이론적 오병합 가능성을 `Risks`에 기록한다. 실제 회귀 위험이
  관측되면 `trashed_at` 고해상도화를 **s01 계약 개정**으로 승격(전 체크포인트 재검증 동반)한다. L3 시점의
  property/edge-case 테스트로 비흡수·독립 타이머 불변식을 검증한다.

### 삭제 진입점(DELETE /documents/{id})과 s10 경계
- **Context**: `s01` 카탈로그에서 `DELETE /documents/{id}`(행 23)는 s07 소유, `/trash/*` 복구·완전삭제(행
  30·31)와 `GET /workspaces/{id}/trash`(행 29)는 s10 소유다. 상태 규칙 중복을 피해야 한다.
- **Findings**: 행 23은 active→trashed(삭제=묶음 포착)이고, 행 30·31은 trashed→active/deleted다. 규칙은
  한 엔진에 있어야 하지만 HTTP 표면은 두 spec에 나뉜다.
- **Selected Approach**: s07은 **삭제(trash) primitive를 자기 라우터(행 23)에서 호출**하고, **복구·완전삭제·
  묶음 열거 primitive를 s10이 호출**하도록 엔진 인터페이스를 공개한다. 보관 타이머(6.8)는 s10 소유이며 s07
  완전삭제 primitive를 호출한다. s07은 s10 코드를 import하지 않는다(의존 방향 하향 유지).
- **Trade-offs**: 삭제 표면(행 23)과 복구/완전삭제 표면(행 30·31)이 분리되지만 규칙은 단일 엔진에 존재해
  드리프트가 없다. s10은 얇은 API·타이머 어댑터만 갖는다.

### 렌더/preview 경계 — 단일 markdown 렌더 규약
- **Context**: 4.4(열람 시 현재 버전 렌더)·4.5(편집 화면 preview 창)를 s07이 소유하나, 프론트엔드 화면과
  버전 저장(s09)은 범위 밖이고 `s01` 카탈로그에 preview 전용 엔드포인트는 없다(엔드포인트 신설은 계약 변경).
- **Findings**: 두 요구는 "동일한 markdown 문법·안전 처리로 렌더"라는 **단일 규약**으로 수렴한다. 신설
  엔드포인트 없이, 문서 조회 응답에 현재 버전 렌더 결과를 포함하고, 편집 화면 preview는 동일 렌더 규약을
  재사용한다(preview UI 자체는 프론트엔드=범위 밖).
- **Selected Approach**: 재사용 가능한 **markdown 렌더 서비스**(markdown → 안전 HTML)를 s07 서비스 레이어에
  두고, 문서 조회(행 20)가 이를 사용해 현재 버전 렌더 결과를 응답에 포함한다. preview는 같은 규약을 소비한다.
  카탈로그(경로·메서드·요구 role) 무변경.
- **Trade-offs**: 서버측 렌더로 규약을 단일화(안전 처리 일관)한다. 신규 문서(현재 버전 부재)는 빈 렌더로 처리.

### 문서 이동 — 순환 방지·동일 WS·중간 삽입 정렬
- **Context**: REQ-4.6~4.8, INV-5(사이클 금지)·INV-6(WS 경계). `sort_order`는 `DECIMAL(30,15)`로 중간 삽입 지원.
- **Findings**:
  - 순환 방지: 새 부모에서 루트까지 `parent_id`를 거슬러 올라 대상 문서를 만나면 거부(자기/후손 이동 금지).
  - 동일 WS: 문서의 `workspace_id`는 고정. 새 부모의 `workspace_id`가 다르면 거부(INV-6). 이동은 WS 내
    parent 재지정·형제 재정렬에 한정.
  - 중간 삽입: 두 형제 사이 위치는 인접 형제 `sort_order`의 중간값으로 부여해 다른 형제 재배치를 피한다.
- **Implications**: 이동/재정렬은 active 문서에만 적용한다(trashed/deleted는 휴지통 도메인). 새 부모도 active여야 한다.

### 권한 게이팅 — s05 실동작 resolver 재사용 + 문서→WS 어댑터
- **Context**: 문서는 워크스페이스에 속하고 권한은 WS 단위만이다(INV-1). `s01` `require_ws_role`은
  workspace_id를 주입받으며, `/documents/{id}` 경로는 문서 id만 준다.
- **Findings**: `s05`가 `workspace_member`를 채워 resolver가 실제 role로 동작한다. s07은 문서 id →
  workspace_id 매핑 어댑터만 제공하면 된다(resolver 로직 재구현 금지).
- **Selected Approach**: `/workspaces/{id}/documents`(행 18·19)는 경로 id가 곧 workspace_id다.
  `/documents/{id}`(행 20·21·22·23)는 문서를 로드해 `workspace_id`를 추출하는 어댑터로 `require_ws_role`을
  구성한다. CRUD·이동·삭제=EDITOR, 조회=VIEWER, admin은 bypass.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Feature 모듈 + 상태 엔진 분리 | `app/document/`에 schemas→repository→(DocumentService · DocumentStateEngine)→router. 엔진을 별도 서비스로 캡슐화 | 상태 규칙 단일 구현·재사용, 단일 책임, s10/s14 재사용 경계 명확 | 없음(스택 재사용) | **채택** — structure.md·브리프 정렬 |
| 상태 규칙을 라우터/서비스에 분산 | 삭제·복구·완전삭제 로직을 CRUD 서비스에 혼합 | 파일 수 감소 | s10/s14가 규칙 재구현·드리프트, 불변식 검증 산재 | 기각 |
| `bundle_id` 컬럼 추가 | 묶음을 명시 컬럼으로 식별 | 재구성 단순 | `s01` 스키마 계약 변경(전 체크포인트 재검증) | 기각 |
| 신규 preview 엔드포인트 추가 | preview 전용 API 신설 | 서버 preview 명시 | `s01` 카탈로그 변경(계약 변경)·프론트 범위 밖 | 기각 |

## Design Decisions

### Decision: 상태/bundle 전이 엔진을 단일 서비스로 캡슐화
- **Context**: 브리프·structure.md가 "bundle 전이 엔진은 단일 well-encapsulated 구현, 하위 spec 재사용,
  재구현 금지"를 명시.
- **Alternatives Considered**:
  1. CRUD 서비스에 상태 로직 혼합 — 하위 spec 재구현·드리프트.
  2. `DocumentStateEngine` 별도 서비스로 삭제(trash)·복구(restore)·완전삭제(purge)·묶음 식별을 단일화.
- **Selected Approach**: (2). 엔진은 `trash_document`·`restore_bundle`·`purge_bundle`·`identify_bundles`·
  `get_bundle`·active 하위 질의를 노출한다. s07 라우터는 `trash_document`만 호출(행 23), 나머지 primitive는
  s10/s14가 호출한다.
- **Rationale**: 불변식 INV-10·11·12를 코드 한 곳에 담아 property 테스트로 검증하고 하위 드리프트를 차단.
- **Trade-offs**: 엔진과 CRUD 서비스 간 얇은 협력이 필요하나, 재사용 경계가 명확해진다.
- **Follow-up**: 엔진 primitive 시그니처를 design.md Contracts로 고정. s10/s14 design이 이를 참조.

### Decision: 묶음 식별자 = 묶음 루트 문서 id
- **Context**: `bundleId` 지칭 수단 필요, 스키마 무변경 원칙.
- **Selected Approach**: 묶음 루트(직접 삭제 대상, 또는 캐스케이드 최상위) 문서 id를 묶음 식별자로 사용.
  구성원은 루트+동일 trashed_at 연결 서브트리로 결정적으로 재구성.
- **Rationale**: 컬럼 추가 없이 결정적 식별. INV-11이 부모/자식 묶음 분리를 보장.
- **Trade-offs**: 초 단위 trashed_at 정밀도 경계(위 Risk). 캐스케이드 제외로 구조적 차단.

## Risks & Mitigations
- **Risk**: `DATETIME` 초 단위 정밀도로 인해 동일 초 독립 삭제가 묶음 재구성에서 오병합될 이론적 가능성 —
  **Mitigation**: 삭제 캐스케이드에서 이미 trashed된 하위를 원자적 제외로 구조적 차단, 묶음 루트 판정을
  trashed_at 상이 기준으로 정의, property/edge-case 테스트로 비흡수 검증. 관측 시 `s01` 계약으로 정밀도 승격.
- **Risk**: 상태 엔진과 CRUD 서비스의 이중 소유로 상태 규칙이 새어나갈 우려 — **Mitigation**: 상태 전이는
  엔진만 소유, CRUD/이동/렌더는 상태를 읽기만 하고 전이는 엔진 호출로 위임.
- **Risk**: 문서 보유 워크스페이스 삭제(s05 물리 삭제)와의 FK 충돌 — **Mitigation**: `s01` FK RESTRICT가
  문서 보유 시 워크스페이스 삭제를 차단(s05 research에 기록됨). s07은 문서 물리 삭제를 하지 않는다(INV-4).
- **Risk**: 복구 sort_order 원위치 복원 시 원래 이웃 소멸로 위치 불확정 — **Mitigation**: 6.7 폴백 계단
  (원위치→중간값→근사→맨 뒤)을 엔진에 결정적으로 구현.

## References
- 계약 단일 소스(문서·문서버전 스키마·에러·인증·resolver·카탈로그·불변식): `.kiro/specs/s01-contract-foundation/design.md`.
- 권한 resolver 실동작·`require_ws_role` 사용 패턴·문서→WS 어댑터 근거: `.kiro/specs/s05-workspace/design.md`.
- 상위 근거: `docs/projects.md` §2.4·§2.5 데이터 모델, §3 REQ-4·REQ-6, §4.1~4.3 상태 전이, §5 INV-5·6·10·11·12.
