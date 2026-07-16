# Implementation Plan — s05-workspace

> 워크스페이스·멤버십·권한 feature spec. 모든 명령은 `backend/`에서 `uv run` 기준. 산출물 언어 한국어,
> 코드 식별자는 영어. `s01-contract-foundation`의 계약(workspace·workspace_member·user 모델, 권한
> resolver `require_ws_role`, 세션 인증, 에러 모델, Base Schemas, Settings, 라우터 조립 지점)을 재사용하며
> 재정의하지 않는다. resolver의 위계 비교·admin bypass 로직은 s01 소유이며 s05는 `workspace_member`
> 데이터를 채워 이를 실동작시킨다. workspace·workspace_member는 물리 삭제(INV-4 비대상), user는 조회만.

- [ ] 1. Foundation: feature 모듈·스키마·의존성
- [x] 1.1 workspace 모듈 스캐폴드 및 스키마 정의
  - `app/workspace/` 패키지(`__init__.py`, `router.py`, `admin_router.py`, `service.py`, `repository.py`,
    `schemas.py`, `dependencies.py`) 골격 생성
  - `schemas.py`에 `s01` Base Schemas를 상속한 `WorkspaceCreate`(name), `WorkspaceUpdate`(name/is_shareable/
    trash_retention_days 부분 갱신), `WorkspaceRead`(`TimestampedRead` 상속, name/is_shareable/
    trash_retention_days), `MemberCreate`(user_id/role), `MemberUpdate`(role), `MemberRead`(id/workspace_id/
    user_id/role), `OwnerChangeRequest`(new_owner_user_id), role 문자열 Enum(owner/editor/viewer) 정의
  - 관찰 가능 완료: ORM workspace 객체로부터 `WorkspaceRead`가 직렬화되고, `MemberCreate`의 잘못된 role
    값과 `WorkspaceUpdate`의 필수/형식 위반이 검증 오류를 내며, `Role` 값이 `s01` `workspace_member.role`
    ENUM 문자열과 일치함을 단위 테스트로 확인
  - _Requirements: 1.2, 2.1, 3.1, 3.4, 5.1, 6.1_
  - _Boundary: WsMemberSchemas_
- [x] 1.2 workspace_id 어댑터 구현 (require_admin은 s01 공통 소비)
  - `dependencies.py`에 워크스페이스 경로 `{id}`를 workspace_id로 추출해 `s01` `require_ws_role(minimum)`에
    주입하는 얇은 어댑터 제공(resolver 로직 재구현 없음). **`require_admin`은 s05가 정의하지 않는다**: admin
    게이트는 `s01` `common/permissions`의 공통 `require_admin`으로 중앙화되었으므로 s05는 이를 import해
    소비만 한다(feature-local 정의 폐기)
  - 관찰 가능 완료: 어댑터가 경로 `{id}`로 `require_ws_role`를 구성해 소유 라우트에 부착 가능하고, `s01`
    공통 `require_admin`을 import해 admin_router에 부착 가능함을 단위 테스트로 확인
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.4_
  - _Boundary: WsIdAdapter (require_admin은 s01 소비, 재정의 없음)_
  - _Depends: 1.1_

- [ ] 2. Core: 리포지토리·서비스
- [x] 2.1 WorkspaceRepository 구현 (workspace CRUD·물리 삭제)
  - `repository.py`에 `s01` workspace 모델·`get_db` 세션 기반 `get_by_id`, `list_for_user`(멤버 조인,
    limit/offset, total), `list_all`(admin 전체), `create`(is_shareable=False, trash_retention_days 인자),
    `apply_updates`(name/is_shareable/trash_retention_days 부분 전환), `delete`(물리 삭제) 구현
  - 관찰 가능 완료: `create`가 `is_shareable=false` 워크스페이스 행을 만들고, `list_for_user`가 멤버 스코프
    items·total을, `list_all`이 전체를 반환하며, `delete`가 워크스페이스 행을 물리적으로 제거함을 단위 테스트로 확인
  - _Requirements: 1.3, 1.4, 2.1, 2.5_
  - _Boundary: WorkspaceRepository_
  - _Depends: 1.1_
- [x] 2.2 MembershipRepository 구현 (workspace_member CRUD·role 조회·user 존재 확인)
  - 참고: 2.1과 동일한 `repository.py`를 편집하므로 병렬 실행하지 않는다(파일 경합 회피).
  - `repository.py`에 `s01` workspace_member·user 모델 기반 `get`(workspace_id,user_id), `get_role`(resolver
    데이터 소스), `add`(role 지정), `set_role`, `remove`(물리 삭제), `remove_all_for_workspace`,
    `user_exists`(is_deleted 사용자도 존재로 간주) 구현. (workspace_id,user_id) 유일성은 사전 조회 + `s01`
    UNIQUE 제약으로 보장
  - 관찰 가능 완료: `add`가 멤버 행을 만들고 중복 조합 삽입이 유일성 위반으로 감지되며, `get_role`이 등록된
    role 문자열을 반환하고 비멤버는 None, `remove`가 멤버 행을 물리 제거함을 단위 테스트로 확인
  - _Requirements: 3.1, 3.2, 3.6, 3.8, 4.2, 4.7, 5.2, 5.3_
  - _Boundary: MembershipRepository_
  - _Depends: 1.1_
- [x] 2.3 WorkspaceService 구현 (생성 owner화·목록·상세·설정·삭제)
  - `service.py`에 `create_workspace`(워크스페이스 insert + 요청자 owner 멤버 등록, 단일 트랜잭션,
    trash_retention_days는 `s01` `Settings` 기본값), `list_workspaces`(admin 전체/멤버 스코프,
    `Page[WorkspaceRead]`), `get_workspace`(미존재→404), `update_workspace`(부분 갱신,
    trash_retention_days ≤ 0→422, 미존재→404), `delete_workspace`(빈 워크스페이스에 한해 멤버십 전체 제거
    후 워크스페이스 물리 삭제, 미존재→404; 문서가 남은 비-empty 워크스페이스는 `s01` FK `ON DELETE
    RESTRICT` 위반(IntegrityError)을 `DomainError(CONFLICT, 409)`로 변환해 거부 — INV-4·FK 정합) 구현.
    도메인 오류는 `s01` `DomainError`로 raise
  - 관찰 가능 완료: 생성 워크스페이스가 `is_shareable=false`·기본 보관일이고 요청자가 owner로 등록되며,
    `update_workspace`가 is_shareable/retention을 갱신하고 잘못된 retention→422, `delete_workspace`가 빈
    워크스페이스의 멤버십·워크스페이스를 함께 제거하고, FK RESTRICT 위반(비-empty)을 모사(mock
    IntegrityError)하면 409로 변환·아무것도 제거되지 않음을 단위 테스트로 확인
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 6.6_
  - _Boundary: WorkspaceService_
  - _Depends: 2.1, 2.2_
- [x] 2.4 MembershipService 구현 (멤버 추가·role 변경·제거·소유권 변경)
  - `service.py`에 `add_member`(대상 user 미존재→404, 기존 멤버→409, 지정 role 등록), `change_role`(멤버십
    미존재→404, role 갱신), `remove_member`(멤버십 미존재→404, 물리 삭제, 마지막 owner 제거도 허용),
    `change_owner`(admin용: 워크스페이스 미존재→404, 대상 user 미존재→404, 멤버면 role=owner 갱신·아니면
    owner 신규 등록 upsert, 기존 owner 유지) 구현
  - 관찰 가능 완료: 신규 멤버 등록·중복→409·미존재 사용자→404, role 변경과 마지막 owner 강등/제거 허용,
    `change_owner`가 비멤버를 owner로 신규 등록하고 owner 부재 워크스페이스에도 새 owner를 지정함을 단위
    테스트로 확인
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 5.1, 5.2, 5.3, 5.5, 5.6_
  - _Boundary: MembershipService_
  - _Depends: 2.2_

- [ ] 3. Integration: 라우터·부트스트랩 연결
- [x] 3.1 WorkspaceRouter 8개 엔드포인트 구현
  - `router.py`에 `POST /workspaces`(인증만, WorkspaceCreate→WorkspaceRead), `GET /workspaces`(limit/offset→
    Page[WorkspaceRead]), `GET /workspaces/{id}`(require_ws_role VIEWER), `PATCH /workspaces/{id}`
    (require_ws_role OWNER, WorkspaceUpdate), `DELETE /workspaces/{id}`(OWNER), `POST /workspaces/{id}/members`
    (OWNER, MemberCreate→MemberRead), `PATCH /workspaces/{id}/members/{uid}`(OWNER, MemberUpdate),
    `DELETE /workspaces/{id}/members/{uid}`(OWNER) 구현. 게이트는 1.2 어댑터 + `s01` `require_ws_role`,
    서비스에 위임
  - 관찰 가능 완료: 각 라우트가 요구 role 충족 시 정상 응답, viewer/editor/비멤버의 변경 요청→403,
    admin→bypass 통과, 비인증→401을 반환하고 스키마 검증 실패는 422 `ErrorResponse`로 직렬화됨을
    라우터 테스트로 확인
  - _Requirements: 1.1, 1.3, 1.5, 2.1, 2.5, 2.6, 3.1, 3.4, 3.5, 4.3, 4.4, 4.5, 6.2, 6.3, 6.4_
  - _Boundary: WorkspaceRouter_
  - _Depends: 1.2, 2.3, 2.4_
- [ ] 3.2 (P) AdminOwnerRouter 소유권 변경 엔드포인트 구현
  - `admin_router.py`에 `POST /admin/workspaces/{id}/owner`(게이트는 `s01` 공통 `require_admin`을 import해
    소비, OwnerChangeRequest→WorkspaceRead) 구현, `MembershipService.change_owner`에 위임. `s01` 카탈로그
    행 9와 정합(소유 spec s05 확정)
  - 관찰 가능 완료: admin 세션→소유권 변경 후 지정 사용자가 owner로 설정되고 `WorkspaceRead` 반환, 비-admin
    →403, 미존재 워크스페이스/사용자→404를 반환함을 라우터 테스트로 확인
  - _Requirements: 5.1, 5.4, 6.2, 6.4_
  - _Boundary: AdminOwnerRouter_
  - _Depends: 1.2, 2.4_
- [ ] 3.3 s01 라우터 조립 지점에 워크스페이스·admin 라우터 연결
  - `s01` `create_app()`의 feature 라우터 조립 지점(`app/main.py` 또는 `app/routers/__init__.py`)에
    `include_router(workspace.router)`·`include_router(workspace.admin_router)` 추가
  - 관찰 가능 완료: `uv run uvicorn app.main:app` 부팅 후 `/workspaces`·`/workspaces/{id}/members`·
    `/admin/workspaces/{id}/owner` 경로가 앱 라우트 목록에 노출됨을 확인
  - _Requirements: 6.4, 6.5_
  - _Depends: 3.1, 3.2_

- [ ] 4. Validation: resolver 실동작·권한·소유권 통합 검증
- [ ] 4.1 권한 resolver 실동작 및 워크스페이스·멤버십 왕복 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: (1) `POST /workspaces`로 생성 시 요청자가 owner로 자동 등록,
    (2) owner가 사용자를 viewer/editor/owner로 멤버 추가 후 각 세션으로 `require_ws_role` 보호 라우트 접근 →
    owner·admin만 변경 라우트 통과·viewer/editor/비멤버는 403(INV-1·2·3 실동작), (3) editor 세션으로
    `GET /workspaces/{id}` 상세 접근 가능, (4) 중복 멤버 추가→409·미존재 사용자→404, (5) owner의
    `DELETE /workspaces/{id}` 후 워크스페이스·멤버십 모두 제거를 검증하는 통합 테스트 작성.
    참고: L2에는 문서 테이블이 없어 삭제 대상은 항상 빈 워크스페이스다. **비어 있지 않은 워크스페이스
    삭제→409 거부(2.7)는 s07 문서 도입 이후 통합 체크포인트 s08(L3)에서 검증**하며, L2에서는 2.3의 단위
    테스트(FK RESTRICT IntegrityError→409 변환)로 커버한다.
  - 관찰 가능 완료: 위 시나리오 통합 테스트가 실제 앱 컨텍스트에서 모두 통과하고, 멤버십 생성 전에는 admin만,
    생성 후에는 실제 role로 게이팅됨이 확인된다
  - _Requirements: 1.1, 1.5, 2.5, 3.1, 3.2, 3.3, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_
  - _Depends: 3.3_
- [ ] 4.2 (P) admin 소유권 변경 및 계약 정합 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: (1) 워크스페이스의 owner를 모두 제거해 owner 부재 상태로 만든 뒤
    `POST /admin/workspaces/{id}/owner`(admin 세션)로 새 owner 지정→해당 사용자가 owner 게이트 통과(3.9·5.6),
    (2) 비-admin의 소유권 변경 요청→403, (3) 응답이 `{Resource}Read`·`Page[WorkspaceRead]` 규약과 `s01`
    `ErrorResponse` 형태를 따르고, (4) s05가 새 마이그레이션을 추가하지 않고 `s01` workspace·workspace_member
    스키마만 사용함을 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 위 4개 검증이 실제 앱 컨텍스트에서 모두 통과한다
  - _Requirements: 5.1, 5.4, 5.5, 5.6, 3.9, 6.1, 6.2, 6.5_
  - _Boundary: Integration Tests (owner-change 테스트 모듈, 4.1과 별도 파일)_
  - _Depends: 3.3_
