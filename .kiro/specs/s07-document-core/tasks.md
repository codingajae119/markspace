# Implementation Plan — s07-document-core

> 문서 코어·상태 전이 엔진 feature spec. 모든 명령은 `backend/`에서 `uv run` 기준. 산출물 언어 한국어,
> 코드 식별자는 영어. `s01-contract-foundation`의 계약(document·document_version·workspace 모델, 권한
> resolver `require_ws_role`, 세션 인증, 에러 모델, Base Schemas, Settings, 라우터 조립 지점)과 `s05`가
> 실동작시킨 `require_ws_role`을 재사용하며 재정의하지 않는다. 문서는 물리 삭제하지 않는다(INV-4, 상태
> 전환만). **상태 전이(삭제·복구·완전삭제·묶음 식별)는 `DocumentStateEngine` 단일 구현에만 존재**하고,
> CRUD/이동/렌더 서비스는 이를 호출한다. s10·s14는 이 엔진 primitive를 소비하며, 이 spec은 s10·s14를
> import하지 않는다.

- [x] 1. Foundation: 모듈·스키마·데이터 접근·의존성
- [x] 1.1 document 모듈 스캐폴드·스키마 정의·렌더 의존성 추가
  - `app/document/` 패키지(`__init__.py`, `router.py`, `service.py`, `engine.py`, `renderer.py`,
    `repository.py`, `schemas.py`, `dependencies.py`) 골격 생성
  - `schemas.py`에 `s01` Base Schemas를 상속한 `DocumentCreate`(title/parent_id), `DocumentUpdate`(title 부분
    갱신), `DocumentMoveRequest`(new_parent_id/형제 기준 필드), `DocumentRead`(`TimestampedRead` 상속:
    workspace_id/parent_id/title/status/sort_order/current_version_id/created_by/content/content_html) 정의
  - markdown 렌더 + HTML 새니타이즈 외부 의존성을 `uv add`로 추가(`pyproject.toml`·`uv.lock` 갱신)
  - 관찰 가능 완료: ORM document 객체로부터 `DocumentRead`가 직렬화되고 `status` 값이 `s01`
    `document.status` ENUM 문자열과 일치하며, `DocumentCreate`의 필수/형식 위반이 검증 오류를 내고, 추가한
    렌더 의존성이 `uv run python -c` 임포트로 로드됨을 확인
  - _Requirements: 1.1, 1.2, 3.1, 4.1, 10.1_
  - _Boundary: DocumentSchemas_
- [x] 1.2 DocumentRepository 구현 (계층·상태 질의·현재 버전 본문)
  - `repository.py`에 `s01` document·document_version 모델·`get_db` 기반 `get`, `get_workspace_id`,
    `list_active_by_workspace`(limit/offset/total), `list_children`/`list_siblings`(정렬 순),
    `collect_active_descendants`(재귀, root 포함, 이미 trashed 제외), `list_trashed_by_workspace`(묶음
    재구성용), `load_current_content`(없으면 빈 문자열), `insert`(status=active), `apply_updates`,
    `set_status_bulk`(묶음 전이 원자 적용점), `set_parent_and_order` 구현. 문서 물리 삭제 없음
  - 관찰 가능 완료: `insert`가 active 문서 행을 만들고, `collect_active_descendants`가 트리에서 active
    하위(root 포함)만 반환하며 trashed 하위는 제외하고, `list_trashed_by_workspace`가 trashed 문서를 반환하고,
    `load_current_content`가 현재 버전 부재 시 빈 문자열을 반환함을 단위 테스트로 확인
  - _Requirements: 1.1, 1.2, 2.1, 2.4, 3.1, 4.1, 5.2, 5.3, 6.1, 6.5, 7.1, 8.1, 9.3_
  - _Boundary: DocumentRepository_
  - _Depends: 1.1_
- [x] 1.3 문서 id → workspace_id 어댑터 구현
  - `dependencies.py`에 문서 id로 소속 workspace_id를 조회(미존재→404)해 `s01` `require_ws_role(minimum)`에
    주입하는 얇은 어댑터 구현. `/workspaces/{id}/*`는 경로 id를 직접 workspace_id로 사용하고, `/documents/{id}`
    는 이 어댑터로 workspace_id를 추출. resolver 위계 비교·admin bypass 로직은 재구현하지 않음
  - 관찰 가능 완료: 존재하는 문서 id로 어댑터가 workspace_id를 추출해 `require_ws_role` 판정에 위임하고,
    미존재 문서 id는 404를 내며, 보호 라우트 스텁에 부착 시 role 미충족→403·admin→통과가 됨을 단위 테스트로 확인
  - _Requirements: 10.3, 10.4_
  - _Boundary: DocumentWsAdapter_
  - _Depends: 1.2_
- [x] 1.4 (P) MarkdownRenderer 안전 렌더 규약 구현
  - `renderer.py`에 markdown → 새니타이즈된 HTML 렌더(`render`) 구현. 스크립트·이벤트 핸들러·위험 URL 제거
    (XSS 방지). 열람(4.4)과 편집 preview(4.5)가 공용하는 단일 규약
  - 관찰 가능 완료: 일반 markdown이 HTML로 렌더되고, `<script>`·`onerror` 등 위험 요소가 포함된 입력은
    새니타이즈되어 실행 불가 HTML로 출력되며, 빈 입력은 빈/안전 HTML을 반환함을 단위 테스트로 확인
  - _Requirements: 2.2, 2.3, 2.5_
  - _Boundary: MarkdownRenderer_
  - _Depends: 1.1_

- [ ] 2. Core: 문서 구조 서비스 (CRUD·이동·렌더 오케스트레이션)
- [x] 2.1 문서 생성·조회·목록 구현 (렌더 포함)
  - `service.py`에 `create_document`(부모 지정 시 존재·active·동일 WS 검증, 아니면 거부; 형제 마지막 순서
    `sort_order` 부여; status=active·created_by 기록; 초기 버전 생성 안 함), `get_document`(미존재→404, 현재
    버전 `content`와 `MarkdownRenderer` 렌더 `content_html` 포함), `list_documents`(`Page[DocumentRead]`) 구현
  - 관찰 가능 완료: 루트·하위 문서가 active로 생성되고 잘못된/타 WS 부모는 거부되며, `get_document` 응답이
    `content`·`content_html`을 포함하고 현재 버전 부재 문서는 빈 본문 렌더를 반환, 목록이 WS active 문서를
    반환함을 단위 테스트로 확인
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.3, 2.4, 2.7_
  - _Boundary: DocumentService_
  - _Depends: 1.2, 1.4_
- [x] 2.2 문서 제목 수정 구현
  - `service.py`에 `update_document`(부분 갱신: title; 미존재→404) 구현. 본문 내용·버전 생성은 이 경계에서
    수행하지 않고 s09에 위임함을 코드·주석으로 명확히 함
  - 관찰 가능 완료: `update_document`가 제목을 갱신하고 미존재 문서→404를 내며, 본문/버전 필드를 건드리지
    않음을 단위 테스트로 확인
  - _Requirements: 3.1, 3.3, 3.4_
  - _Boundary: DocumentService_
  - _Depends: 2.1_
- [ ] 2.3 문서 이동·재정렬 구현 (순환 방지·동일 WS·중간 삽입)
  - `service.py`에 `move_document` 구현: 대상=자기/후손 이동 거부(순환 방지, 새 부모에서 루트까지 조상
    체인 검사, INV-5); 새 부모 WS 상이 시 거부(INV-6); 새 부모 존재·active 검증(아니면 거부); 두 형제 사이
    삽입은 인접 `sort_order` 중간값 부여(다른 형제 재배치 없음). active 문서에만 적용
  - 관찰 가능 완료: 자기/후손 밑 이동과 타 WS 부모 이동이 거부되고, 정상 이동이 parent/sort_order를
    갱신하며, 두 형제 사이 재정렬이 인접 중간값으로 삽입되어 다른 형제 순서를 바꾸지 않음을 단위 테스트로 확인
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7_
  - _Boundary: DocumentService_
  - _Depends: 2.1_

- [ ] 3. Core: 상태 전이 엔진 (묶음 비흡수 단일 구현)
- [ ] 3.1 (P) 묶음 식별·열거·active 하위 질의 구현
  - `engine.py`에 `Bundle` DTO와 `active_descendants`(삭제 캐스케이드·s14 공유 공용), `identify_bundles`(WS
    전체 묶음 열거), `get_bundle`(루트 문서 id로 묶음 구성원 확정·검증, 유효하지 않은 루트→404) 구현. 묶음
    = 루트 문서 id, 루트 = trashed 문서 중 부모가 없거나·부모가 trashed 아님·부모 trashed_at 상이인 문서;
    구성원 = 루트에서 parent_id로 내려가며 status=trashed이고 루트와 동일 trashed_at인 연결 서브트리
  - 관찰 가능 완료: 여러 시점에 trashed된 문서들이 있는 WS에서 `identify_bundles`가 별개 루트로 분리 열거되고,
    `get_bundle(root)`가 동일 trashed_at 연결 구성원만 반환하며, 비루트/비trashed id는 404를 냄을 단위 테스트로 확인
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.1, 9.2, 9.3_
  - _Boundary: DocumentStateEngine_
  - _Depends: 1.2_
- [ ] 3.2 삭제 캐스케이드(active → trashed) primitive 구현
  - `engine.py`에 `trash_document` 구현: 대상 active 검사(아니면 409); 현재 시각 `trashed_at` 산정;
    `active_descendants`로 그 시점 active 하위(root 포함) 포착·이미 trashed 하위 제외(비흡수, 6.2.1);
    포착 구성원을 단일 트랜잭션에서 status=trashed·공통 trashed_at으로 전환(원자적, INV-10); 잠금 여부 무시
    (상태·잠금 독립, §4.3); 반환은 루트=대상 묶음
  - 관찰 가능 완료: active 문서 삭제 시 그 시점 active 하위만 공통 trashed_at으로 trashed되고 이미 trashed된
    하위는 제외되며(자식 개별 삭제 시 독립 묶음), 자식 먼저(t1)·부모 나중(t2) 삭제에서 자식이 흡수되지 않고
    `child.trashed_at ≤ parent.trashed_at`(INV-11)이 성립함을 단위 테스트로 확인
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 6.1, 6.2, 6.3, 6.4, 9.4_
  - _Boundary: DocumentStateEngine_
  - _Depends: 3.1_
- [ ] 3.3 복구(trashed → active) primitive 구현
  - `engine.py`에 `restore_bundle` 구현: `get_bundle`로 구성원 확정; 루트의 부모 상태 1회 검사(6.5)로 부모
    active면 부모 밑(parent_id 유지, sort_order 원위치 복원 — 충돌 시 중간값·근사·맨 뒤 폴백, 6.7.1),
    non-active/부재면 root 맨 뒤 append(parent_id=NULL, 6.7.2); 구성원 전체 status=active·trashed_at=NULL,
    묶음 내부 계층 유지; 자동 재중첩 없음(6.5.3); 독립 묶음 단독 복구 가능(6.6)
  - 관찰 가능 완료: 부모 active 묶음은 부모 밑 원위치로, 부모 non-active/부재 묶음은 root 맨 뒤로 복귀하고,
    root 복구 후 부모를 복구해도 자동 재중첩되지 않으며, 독립 자식 묶음이 부모와 무관하게 단독 복구됨을 단위 테스트로 확인
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 9.2_
  - _Boundary: DocumentStateEngine_
  - _Depends: 3.1_
- [ ] 3.4 완전삭제(trashed → deleted) primitive 구현
  - `engine.py`에 `purge_bundle` 구현: `get_bundle` 구성원 전체를 status=deleted로 원자적 전환(INV-10);
    물리 삭제 없음(INV-4, 레코드 보존); deleted 종착(INV-7); 상태 전이만 수행하고 첨부 아카이브(s12)·버전
    처리는 소유하지 않음; 다른 독립 묶음 불변
  - 관찰 가능 완료: 완전삭제가 묶음 전체를 deleted로 전환하되 레코드를 제거하지 않고, 다른 독립 묶음의
    상태·trashed_at을 변경하지 않으며, deleted 문서에 대한 재복구 경로가 없음을 단위 테스트로 확인
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - _Boundary: DocumentStateEngine_
  - _Depends: 3.1_

- [ ] 4. Integration: 라우터·부트스트랩 연결
- [ ] 4.1 DocumentRouter 6개 엔드포인트 구현
  - `router.py`에 `POST /workspaces/{id}/documents`(EDITOR, DocumentCreate→DocumentRead),
    `GET /workspaces/{id}/documents`(VIEWER, limit/offset→Page[DocumentRead]), `GET /documents/{id}`(VIEWER→
    DocumentRead), `PATCH /documents/{id}`(EDITOR, DocumentUpdate), `POST /documents/{id}/move`(EDITOR,
    DocumentMoveRequest), `DELETE /documents/{id}`(EDITOR, 엔진 `trash_document` 호출) 구현. 게이트는
    `/workspaces/{id}/*`는 경로 id=workspace_id, `/documents/{id}`는 1.3 어댑터 + `s01` `require_ws_role`;
    서비스·엔진에 위임
  - 관찰 가능 완료: 각 라우트가 요구 role 충족 시 정상 응답, viewer/비멤버의 변경(생성·수정·이동·삭제)→403·
    admin→bypass·비인증→401, DELETE가 대상을 trashed로 만들고 비active 대상→409, 스키마 검증 실패→422
    `ErrorResponse`로 직렬화됨을 라우터 테스트로 확인
  - _Requirements: 1.1, 1.6, 1.7, 2.1, 2.4, 2.6, 3.1, 3.2, 4.1, 4.6, 5.1, 5.2, 5.6, 10.2, 10.3, 10.5_
  - _Boundary: DocumentRouter_
  - _Depends: 1.3, 2.1, 2.2, 2.3, 3.2_
- [ ] 4.2 s01 라우터 조립 지점에 문서 라우터 연결
  - `s01` `create_app()`의 feature 라우터 조립 지점(`app/main.py` 또는 `app/routers/__init__.py`)에
    `include_router(document.router)` 추가. 조립 방식은 `s01`·`s05`를 따름
  - 관찰 가능 완료: `uv run uvicorn app.main:app` 부팅 후 카탈로그 행 18~23 경로
    (`/workspaces/{id}/documents`·`/documents/{id}`·`/documents/{id}/move`)가 앱 라우트 목록에 노출됨을 확인
  - _Requirements: 10.5, 10.6_
  - _Depends: 4.1_

- [ ] 5. Validation: 통합·불변식 검증
- [ ] 5.1 CRUD·계층·권한 게이팅 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: (1) 루트·하위 문서 생성→조회 시 `content`·`content_html` 포함→제목
    수정→이동/재정렬 왕복, (2) `s05` 멤버십 기반으로 viewer는 변경(생성·수정·이동·삭제) 403·editor 통과·
    admin bypass·조회는 viewer 통과(INV-1·2·3), (3) `/documents/{id}`가 문서→WS 어댑터로 게이팅되고 미존재
    문서→404, (4) 응답이 `DocumentRead`·`Page[DocumentRead]`·`s01` `ErrorResponse` 규약을 따르고 새
    마이그레이션 미추가를 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 위 시나리오가 실제 앱 컨텍스트에서 모두 통과하고, 문서 권한이 WS 단위 resolver로만
    게이팅됨(문서별 개별 권한 없음)이 확인된다
  - _Requirements: 1.1, 1.3, 1.4, 1.6, 1.7, 2.1, 2.4, 2.6, 3.1, 3.2, 4.1, 4.6, 10.1, 10.2, 10.3, 10.5, 10.6, 10.7_
  - _Depends: 4.2_
- [ ] 5.2 (P) 상태 엔진 불변식 property·edge-case 테스트
  - 엔진 primitive를 라우터 밖에서 직접 호출하는 재사용 경계로 검증: (1) 비흡수 property — 임의 트리에서
    자식·부모를 임의 순서로 삭제해도 서로 다른 시점 묶음이 병합되지 않고 별개 루트로 식별(INV-10·11),
    (2) 독립 타이머 기준 — 각 묶음 보관 기준 시각이 자기 trashed_at이고 다른 묶음 삭제·복구가 그 값을 바꾸지
    않음(INV-12 기준값 불변), (3) 복구 위치 결정성 — 부모 상태 조합(active/trashed/deleted/부재)에 대해 복구
    목적지가 6.5 규칙과 일치·자동 재중첩 없음, (4) 완전삭제 원자성·종착·물리삭제 없음, (5) 이동 사이클 부재
    property(INV-5)를 검증하는 테스트 작성
  - 관찰 가능 완료: 비흡수·독립 기준·복구 위치·완전삭제·이동 사이클 불변식 테스트가 모두 통과하고, 엔진
    primitive가 s10/s14 소비 계약으로서 라우터 없이도 호출 가능함이 확인된다
  - _Requirements: 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 8.1, 8.2, 8.3, 8.4, 9.1, 9.2_
  - _Boundary: DocumentStateEngine (property test 모듈)_
  - _Depends: 3.2, 3.3, 3.4_
- [ ] 5.3 (P) 상태·잠금 독립 및 엔진 primitive 재사용 통합 검증
  - 마이그레이션된 DB에서: (1) `lock_user_id`가 설정된 문서(테스트에서 직접 세팅)도 `trash_document`가 정상
    전이하고, 이 spec이 lock 값을 스스로 설정하지 않음(§4.3·9.4·9.5), (2) 동일 엔진의
    `trash_document`→`restore_bundle`→(재삭제)→`purge_bundle` 왕복이 상태를 일관되게 전이시켜 s10이 소비할
    복구·완전삭제·묶음 열거 primitive 계약이 성립함을 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 잠긴 문서의 상태 전이가 잠금과 독립적으로 동작하고, 삭제→복구→완전삭제 primitive 왕복이
    실제 DB에서 일관되게 통과함이 확인된다
  - _Requirements: 8.5, 9.1, 9.2, 9.4, 9.5_
  - _Depends: 3.2, 3.3, 3.4_
