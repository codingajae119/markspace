# Implementation Plan — s09-lock-version

> 편집 잠금·저장 버전 feature spec. 모든 명령은 `backend/`에서 `uv run` 기준. 산출물 언어 한국어,
> 코드 식별자는 영어. `s01-contract-foundation`의 계약(`document`의 lock 필드·`current_version_id`,
> `document_version` 스키마, 카탈로그 행 24~28, 권한 resolver `require_ws_role`, 세션 인증, 에러 모델,
> Base Schemas, 라우터 조립 지점)과 `s07-document-core`의 문서→workspace_id 어댑터(`ws_role_for_document`)를
> 재사용하며 재정의하지 않는다. 새 마이그레이션·새 외부 의존성을 추가하지 않는다(기존 `s01` 스키마 위에서
> 동작). 문서·버전은 물리 삭제하지 않는다(INV-4). **잠금·버전 동작은 문서 `status`를 검사·변경하지 않는다**
> (§4.3). 잠금 판정 근거는 `lock_user_id` 단일 컬럼(INV-9). `s10`/`s12`/`s14`를 import하지 않는다.

- [x] 1. Foundation: 모듈·스키마·데이터 접근
- [x] 1.1 lock_version 모듈 스캐폴드·스키마 정의
  - `app/lock_version/` 패키지(`__init__.py`, `router.py`, `service.py`, `repository.py`, `schemas.py`)
    골격 생성
  - `schemas.py`에 `s01` Base Schemas를 상속한 `DocumentSaveRequest`(content: markdown 본문, 빈 문자열 허용),
    `DocumentLockRead`(`ORMReadModel`: document_id/lock_user_id/lock_acquired_at),
    `DocumentVersionRead`(`ORMReadModel`: id/document_id/created_by/created_at — **본문 미포함**) 정의
  - 관찰 가능 완료: ORM `document`·`document_version` 객체로부터 `DocumentLockRead`·`DocumentVersionRead`가
    직렬화되고, `DocumentVersionRead`에 content 필드가 없으며, `DocumentSaveRequest`의 형식 위반이 검증
    오류를 냄을 단위 테스트로 확인. 새 마이그레이션·새 의존성이 추가되지 않았음을 확인
  - _Requirements: 1.1, 2.1, 2.6, 5.1, 5.4, 7.2, 7.5_
  - _Boundary: LockVersionSchemas_
- [x] 1.2 LockVersionRepository 구현 (lock 필드·버전·행 잠금)
  - `repository.py`에 `s01` `document`·`document_version` 모델·`get_db` 기반 `get`,
    `get_for_update`(`SELECT ... FOR UPDATE` 행 잠금), `acquire_lock`(lock_user_id=요청자·lock_acquired_at=at),
    `clear_lock`(lock_user_id·lock_acquired_at=NULL), `insert_version`(content·created_by·created_at, flush로
    id 확보), `set_current_version`(document.current_version_id 갱신),
    `list_versions`(document_id로 최신 저장 순, limit/offset/total) 구현. 문서·버전 물리 삭제 없음, status
    무검사·무변경
  - 관찰 가능 완료: `acquire_lock`이 미잠금 문서에 보유자·시각을 기록하고, `clear_lock`이 잠금 필드를 NULL로
    되돌리며, `insert_version`이 새 버전 행을 만들고 `set_current_version`이 `current_version_id`를 갱신하고,
    `list_versions`가 저장 순(최신 우선) 목록·total을 반환하며, `get_for_update`가 행 잠금으로 문서를 로드함을
    단위 테스트로 확인
  - _Requirements: 1.1, 1.3, 1.4, 2.1, 2.2, 2.3, 3.1, 4.1, 5.1, 6.4_
  - _Boundary: LockVersionRepository_
  - _Depends: 1.1_

- [x] 2. Core: 잠금·버전 서비스
- [x] 2.1 편집 시작(start_edit) 구현 (INV-9·멱등·충돌)
  - `service.py` `LockVersionService.start_edit` 구현: `get_for_update`로 문서 로드(미존재→404); `lock_user_id`
    분기 — NULL→`acquire_lock`(요청자·현재 시각), 요청자 본인→기존 잠금 유지 멱등 성공, 타인→409(다른
    사용자가 편집 중); `DocumentLockRead` 반환. 문서 `status` 검사하지 않음(§4.3)
  - 관찰 가능 완료: 미잠금 문서 시작이 요청자·시각을 기록하고, 동일 보유자 재시작이 잠금을 바꾸지 않고 멱등
    성공하며, 타인 잠금 문서 시작이 409를 내고, 미존재 문서가 404를 냄을 단위 테스트로 확인
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 6.1_
  - _Boundary: LockVersionService_
  - _Depends: 1.2_
- [x] 2.2 저장(save) 원자 트랜잭션 구현 (버전 생성·current 갱신·잠금 해제)
  - `service.py` `LockVersionService.save` 구현: 단일 트랜잭션에서 `get_for_update` 로드(미존재→404)→보유자
    검사(`lock_user_id != 요청자`면 409·버전 미생성·롤백)→`insert_version`(content·created_by=요청자, flush)→
    `set_current_version`(새 버전 id)→`clear_lock`→commit; `DocumentVersionRead` 반환. 원자성 보장(부분 적용
    없음). status 무검사(§4.3)
  - 관찰 가능 완료: 보유자 저장이 새 `document_version`을 만들고 `current_version_id`를 새 버전으로 갱신하며
    잠금을 해제하고 생성 버전을 반환하고, 보유자가 아닌(미잠금·타인 잠금) 저장이 409를 내며 어떤 버전도
    만들지 않고 잠금 상태를 유지함을 단위 테스트로 확인
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 6.1_
  - _Boundary: LockVersionService_
  - _Depends: 1.2_
- [x] 2.3 취소·강제해제(cancel_edit·force_unlock) 구현
  - `service.py`에 `cancel_edit`(보유자→`clear_lock`·버전 미생성; 미잠금→멱등 no-op 성공; 타인 잠금→409)과
    `force_unlock`(보유자 무관 `clear_lock`·버전 미생성; 미잠금→멱등 성공; 권한 게이트는 라우터의
    `require_ws_role(OWNER)`가 담당) 구현. 두 동작 모두 `document_version`을 생성하지 않고 status를 바꾸지 않음
  - 관찰 가능 완료: 보유자 취소가 잠금을 풀고 버전을 만들지 않으며, 미잠금 취소가 멱등 성공하고, 타인 잠금
    취소가 409를 내며, 강제해제가 보유자와 무관하게 잠금을 풀고(미저장 변경분 폐기) 미잠금 시 멱등 성공함을
    단위 테스트로 확인
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.3, 4.4, 4.5, 6.1, 6.3_
  - _Boundary: LockVersionService_
  - _Depends: 1.2_
- [x] 2.4 버전 목록(list_versions) 구현
  - `service.py` `LockVersionService.list_versions` 구현: 문서 미존재→404; `repository.list_versions`로 최신
    저장 순 `Page[DocumentVersionRead]`(메타데이터 전용) 반환. 기존 버전 삭제·본문 노출 없음(무한 보관·rollback
    없음)
  - 관찰 가능 완료: 여러 번 저장된 문서의 버전 목록이 최신 저장 순으로 식별자·저장자·저장 시각을 페이지
    단위로 반환하고, 응답에 본문이 없으며, 기존 버전이 삭제되지 않음을 단위 테스트로 확인
  - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - _Boundary: LockVersionService_
  - _Depends: 1.2_

- [ ] 3. Integration: 라우터·부트스트랩 연결
- [ ] 3.1 LockVersionRouter 5개 엔드포인트 구현
  - `router.py`에 `POST /documents/{id}/lock`(EDITOR→DocumentLockRead), `POST /documents/{id}/save`(EDITOR,
    DocumentSaveRequest→DocumentVersionRead), `POST /documents/{id}/cancel`(EDITOR→204),
    `POST /documents/{id}/force-unlock`(OWNER→204), `GET /documents/{id}/versions`(VIEWER, limit/offset→
    Page[DocumentVersionRead]) 구현. 게이트는 `s07` 문서→WS 어댑터(`ws_role_for_document(minimum)`)로
    workspace_id 추출→`require_ws_role` 주입(미존재→404); 서비스에 위임. resolver 위계·admin bypass 재구현 안 함
  - 관찰 가능 완료: 각 라우트가 요구 role 충족 시 정상 응답하고, viewer/비멤버의 잠금·저장·취소→403·
    force-unlock은 editor→403·owner/admin→통과·비인증→401, 타인 잠금 시 lock/save/cancel→409, 저장 스키마
    검증 실패→422가 `ErrorResponse`로 직렬화됨을 라우터 테스트로 확인
  - _Requirements: 1.1, 1.5, 1.6, 2.1, 2.5, 3.1, 3.5, 4.1, 4.2, 5.1, 5.5, 7.1, 7.3, 7.4_
  - _Boundary: LockVersionRouter_
  - _Depends: 2.1, 2.2, 2.3, 2.4_
- [ ] 3.2 s01 라우터 조립 지점에 잠금·버전 라우터 연결
  - `s01` `create_app()`의 feature 라우터 조립 지점(`app/main.py` 또는 `app/routers/__init__.py`)에
    `include_router(lock_version.router)` 추가. 조립 방식은 `s01`·`s05`·`s07`을 따름
  - 관찰 가능 완료: `uv run uvicorn app.main:app` 부팅 후 카탈로그 행 24~28 경로
    (`/documents/{id}/lock`·`/save`·`/cancel`·`/force-unlock`·`/versions`)가 앱 라우트 목록에 노출됨을 확인
  - _Requirements: 7.6_
  - _Depends: 3.1_

- [ ] 4. Validation: 통합·불변식 검증
- [ ] 4.1 잠금→저장 왕복·권한 게이팅 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: (1) editor A `POST /lock`→editor B `POST /lock` 시 409("편집 중")→A
    `POST /save`(content)로 새 버전 생성·`current_version_id` 갱신·잠금 해제→B `POST /lock` 성공(INV-9),
    (2) `s05` 멤버십 기반으로 viewer는 lock/save/cancel 403·editor 통과·admin bypass, force-unlock은
    owner/admin만 통과·editor 403, versions는 viewer 통과(INV-1·2·3), (3) `/documents/{id}/*`가 `s07`
    문서→WS 어댑터로 게이팅되고 미존재 문서→404, (4) 취소·강제해제가 잠금을 풀고 버전을 만들지 않음을 검증하는
    통합 테스트 작성
  - 관찰 가능 완료: 위 시나리오가 실제 앱 컨텍스트에서 모두 통과하고, 잠금이 `lock_user_id` 단일 컬럼으로
    최대 1인만 보유되며(INV-9), 잠금·버전 권한이 WS 단위 resolver로만 게이팅됨이 확인된다
  - _Requirements: 1.1, 1.2, 1.5, 1.6, 2.1, 2.2, 2.3, 2.5, 3.1, 3.3, 3.5, 4.1, 4.2, 5.1, 5.5, 7.1, 7.3, 7.6_
  - _Depends: 3.2_
- [ ] 4.2 (P) 잠금·삭제 독립·멱등/충돌·버전 보관·카탈로그 정합 검증
  - (1) 잠금·삭제 독립(§4.3): 잠긴 문서를 `s07` `DocumentStateEngine.trash_document`로 trashed 전이시켜도 잠금
    필드가 유지되고 잠금·저장·해제 동작이 status와 무관하게 계속 동작하며 `s09`가 상태 전이를 수행하지 않음,
    (2) 멱등/충돌: 동일 보유자 재시작 멱등·미잠금 취소/강제해제 멱등·타인 잠금 시작·저장·취소 409,
    (3) 버전 무한 보관: 다회 저장 후 목록이 최신순 메타데이터를 반환하고 기존 버전 미삭제·본문 미노출·rollback
    엔드포인트 부재, (4) 카탈로그·마이그레이션 정합: 행 24~28 경로 노출·새 마이그레이션 미추가·`s01`
    document/document_version 스키마만 사용을 검증하는 테스트 작성
  - 관찰 가능 완료: 잠금·삭제 독립·멱등/충돌·버전 보관·카탈로그 정합 테스트가 모두 통과하고, `s09`가 문서
    상태 전이를 수행하지 않으며 새 마이그레이션을 추가하지 않았음이 확인된다
  - _Requirements: 3.2, 4.3, 4.4, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 7.2, 7.4, 7.5_
  - _Boundary: LockVersionService·LockVersionRepository (독립·불변식 테스트 모듈)_
  - _Depends: 3.2_
