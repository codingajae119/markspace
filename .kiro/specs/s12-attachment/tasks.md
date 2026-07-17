# Implementation Plan — s12-attachment

> 첨부·이미지 저장·격리·파일 생명주기 feature spec. 모든 명령은 `backend/`에서 `uv run` 기준. 산출물 언어
> 한국어, 코드 식별자는 영어. `s01-contract-foundation`의 계약(카탈로그 행 32~33, `attachment`·`document`·
> `document_version` 모델, 권한 resolver `require_ws_role`, 세션 인증, 에러 모델, Base Schemas, Settings
> `file_storage_root`, 라우터 조립 지점·lifespan)과 `s05`가 실동작시킨 `require_ws_role`, `s07`의 문서→WS 어댑터
> (`ws_role_for_document`)·`DocumentRepository`(`get_workspace_id`·`load_current_content`)를 재사용하며 재정의하지
> 않는다. **두 생명주기 반응(8.6 완전삭제 보관 이동·8.7 저장 참조 소멸 아카이브)은 관측 기반 조정으로 구현하며,
> s12는 문서 status·현재 버전 참조를 읽어서 판정할 뿐 상태 전이·버전 생성을 수행하지 않는다.** 첨부 물리 삭제
> 없음(INV-4, 보관 이동만). 보관=영구삭제 간주·복원 없음·admin 포함 비노출(INV-7). s12는 `s14`를 import하지
> 않고 `s09`/`s10`을 import하지 않는다(그들의 결과 상태만 관측). 새 DB 마이그레이션을 추가하지 않는다.

- [x] 1. Foundation: 모듈·스키마·설정·저장·데이터 접근·참조 판정·권한 어댑터
- [x] 1.1 attachment 모듈 스캐폴드·첨부 스키마 정의·설정 additive 확장
  - `app/attachment/` 패키지 골격 생성. `s01` Base Schemas(`ORMReadModel`)를 상속한 첨부 응답 스키마(id·
    workspace_id·document_id·kind(image/file)·original_name·is_archived·created_at·참조 url) 정의. url은 저장하지
    않고 응답 시 산정되는 `/attachments/{id}` 파생 규약임을 명시. 업로드는 multipart(file + 선택 kind) 규약으로 둠
  - `config.yml`과 `s01` 공용 Settings에 `attachment_archive_root`(str)·`attachment_sweep_interval_seconds`
    (기본 3600, 0 이하이면 인프로세스 스케줄러 비활성)·`attachment_max_bytes`(기본값) 필드를 additive로 추가.
    저장 루트는 기존 `file_storage_root` 재사용. 모듈별 설정 파일·개별 로더 신설 금지
  - 관찰 가능 완료: 앱 부팅 시 새 설정 필드가 기본값으로 로드되고 기존 Settings 필드 계약이 유지되며, 첨부 응답
    스키마가 `ORMReadModel` 규약으로 직렬화되고 url이 `/attachments/{id}` 형태로 산정되며, 새 DB 마이그레이션이
    추가되지 않음을 확인
  - _Requirements: 1.4, 7.1, 7.5, 7.6_
  - _Boundary: AttachmentSchemas, Settings (s01 additive)_
- [x] 1.2 (P) AttachmentStorage 구현 (WS 격리 저장·스트리밍·보관 이동)
  - 워크스페이스 격리 저장/보관 디렉터리 규약(`{file_storage_root}/{workspace_id}/...`·`{attachment_archive_root}/
    {workspace_id}/...`)과 파일 저장(서버 생성 파일명, 원본명은 DB에만 보존)·서빙 스트림 열기·보관 위치로의 파일
    이동을 구현. 보관 이동은 물리 삭제 없이 파일을 옮기고 새 보관 경로를 반환하며 이미 보관 경로면 멱등(no-op).
    보관 폴더 자동 정리 없음(단조 증가 수용)
  - 관찰 가능 완료: 저장·보관 경로가 워크스페이스별로 분리되고, 저장 후 파일이 저장 위치에 존재하며, 보관 이동이
    파일을 저장 위치에서 보관 위치로 옮기되(물리 삭제 없음) 원본을 남기지 않고, 재이동이 오류 없이 멱등함을 단위
    테스트로 확인
  - _Requirements: 1.2, 3.1, 4.2, 6.1, 6.5_
  - _Boundary: AttachmentStorage_
- [x] 1.3 (P) AttachmentRepository 구현 (첨부 r/w·조정 스코프 질의)
  - `s01` attachment·document·document_version 모델·세션 기반으로 첨부 삽입(is_archived=false)·단건 조회·보관
    표시(mark_archived: file_path를 보관 경로로 갱신·is_archived=true)와 조정 스코프 질의를 구현: (a) 미보관이며
    소속 문서가 deleted인 첨부 열거(8.6 스코프), (b) 미보관 image이며 소속 문서가 active/trashed이고 current_version이
    존재하는 첨부와 그 현재 버전 메타(id·created_at) 열거(8.7 스코프). 상태 전이·버전 생성은 하지 않음(관측만).
    현재 버전 본문 로드는 `s07` `DocumentRepository.load_current_content` 재사용
  - 관찰 가능 완료: 삽입·조회·보관 표시가 동작하고, 두 스코프 질의가 각각 deleted 문서 연결 미보관 첨부와 참조
    소멸 후보 image(+현재 버전 메타)만 반환하며 이미 보관된 첨부는 제외됨을 단위 테스트로 확인
  - _Requirements: 1.3, 3.2, 4.1, 4.4, 4.5, 5.1, 5.5_
  - _Boundary: AttachmentRepository_
- [x] 1.4 (P) ReferenceScanner 구현 (현재 버전 참조 판정)
  - 문서 현재 버전 본문에 첨부 참조 URL 규약(`/attachments/{id}`)이 등장하는지 판정하는 순수 함수 구현. 첨부 id
    경계를 정확히 구분해 `/attachments/12`가 `/attachments/123`을 오탐하지 않도록 처리
  - 관찰 가능 완료: 참조를 포함한 본문은 True, 미포함 본문은 False를 반환하고, id 경계 오탐(부분 일치)이 없음을
    단위 테스트로 확인
  - _Requirements: 5.1, 5.2_
  - _Boundary: ReferenceScanner_
- [x] 1.5 (P) 첨부 id → workspace_id 권한 어댑터 구현
  - 첨부 id로부터 `attachment.workspace_id`를 조회(미존재→404)해 `s01` `require_ws_role(VIEWER)`에 주입하는 얇은
    어댑터(`ws_role_for_attachment`) 구현. `/documents/{id}/attachments` 업로드 경로는 `s07` `ws_role_for_document
    (EDITOR)`를 재사용. resolver 위계 비교·admin bypass 로직은 재구현하지 않음
  - 관찰 가능 완료: 존재하는 첨부 id로 어댑터가 workspace_id를 추출해 권한 판정에 위임하고, 미존재 첨부 id→404,
    보호 라우트 스텁에서 viewer 미충족→403·admin→통과가 됨을 단위 테스트로 확인
  - _Requirements: 3.4, 3.6, 7.3_
  - _Boundary: AttWsAdapter_

- [x] 2. Core: 첨부 업로드·서빙 및 보관 조정(관측 기반)
- [x] 2.1 첨부 업로드 유스케이스 구현 (이미지 붙여넣기·파일 첨부)
  - 업로드 유스케이스 구현: 대상 문서 존재 확인(부재→404), 소속 workspace_id를 클라이언트 입력이 아닌 대상
    문서에서 확정, 업로드 크기 한도 초과 시 거부(422), `AttachmentStorage.save`로 WS 격리 위치에 파일 저장(붙여넣기
    이미지도 base64 인라인이 아닌 파일), `AttachmentRepository.insert`로 kind(image/file)·원본명 보존 레코드 생성,
    참조 url(`/attachments/{id}`) 포함 응답 반환. workspace_id 확정은 `s07` `get_workspace_id` 재사용
  - 관찰 가능 완료: 이미지·파일 업로드가 파일로 저장되고 kind·원본명·소속 문서/WS가 기록되며 응답 url이
    `/attachments/{id}`이고, 존재하지 않는 문서→404·크기 한도 초과→422가 됨을 단위 테스트로 확인
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 2.1, 2.2, 2.5, 3.2_
  - _Boundary: AttachmentService_
  - _Depends: 1.2, 1.3_
- [x] 2.2 (P) 첨부 서빙 유스케이스 구현 (보관 비노출)
  - 서빙 유스케이스 구현: 첨부 로드(부재→404), `is_archived`이면 요청자 role과 무관하게(권한 판정 이전) 404로
    차단해 보관 파일을 노출하지 않음, 미보관이면 `AttachmentStorage.open_stream`으로 바이너리 스트리밍(적절한
    content-type). 권한 게이트(첨부 workspace_id VIEWER)는 라우터에서 주입
  - 관찰 가능 완료: 미보관 첨부는 바이너리를 반환하고, 보관된 첨부는 admin 포함 role 무관 404, 존재하지 않는
    첨부→404가 됨을 단위 테스트로 확인
  - _Requirements: 3.3, 6.2, 6.3_
  - _Boundary: AttachmentService_
  - _Depends: 1.2, 1.3_
- [x] 2.3 (P) 완전삭제 반응 보관 이동 조정 구현 (8.6)
  - deleted 문서 반응 조정 구현: 미보관이며 소속 문서가 deleted인 첨부를 스코프 질의로 열거하고, 각 첨부를
    `AttachmentStorage.move_to_archive`로 보관 폴더로 이동(물리 삭제 없음)한 뒤 `mark_archived`로 is_archived=true·
    file_path 갱신. deleted 전이는 수행하지 않고 status='deleted' 관측으로만 판정, 이미 보관된 첨부는 스코프에서
    제외되어 멱등, 대상 문서의 첨부에만 적용, 첨부 단위 예외는 격리
  - 관찰 가능 완료: deleted 문서 연결 미보관 첨부가 보관 이동·is_archived=true가 되고 파일이 물리 삭제되지 않으며,
    반복 실행이 중복 이동/오류를 내지 않고, 다른(비-deleted) 문서의 첨부는 불변이며, s12 코드에 status 갱신·전이가
    없음을 단위 테스트로 확인
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 7.7_
  - _Boundary: ArchivalSweepService_
  - _Depends: 1.2, 1.3_
- [x] 2.4 (P) 저장 참조 소멸 이미지 아카이브 조정 + 통합 스윕 구현 (8.7)
  - 참조 소멸 조정 구현: 미보관 image이며 current_version이 있는 첨부를 스코프 질의로 열거하고, 붙여넣기 보호로
    `attachment.created_at > current_version.created_at`(미저장 새 붙여넣기)인 이미지는 skip, 현재 버전 본문을 `s07`
    `load_current_content`로 로드해 `ReferenceScanner.is_referenced`가 False면 보관 이동·is_archived=true, 현재
    버전이 참조하면 유지. 이미지 종류에 한정(일반 파일은 8.6으로만). 저장·버전 생성은 수행하지 않고 현재 버전 참조
    관측으로만 판정. 두 조정(8.6·8.7)을 순서대로 수행하고 `now`를 주입받는 통합 `sweep(db, now)` 진입점 제공
  - 관찰 가능 완료: 현재 버전이 참조하지 않는 image가 보관되고, 참조하는 image·미저장 붙여넣기 image·일반 파일은
    보관되지 않으며, 통합 스윕이 두 조정을 수행하고 반복 실행이 멱등함을 단위 테스트로 확인
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.7_
  - _Boundary: ArchivalSweepService_
  - _Depends: 1.3, 1.4, 2.3_

- [x] 3. Integration: 라우터·스케줄러·부트스트랩 연결
- [x] 3.1 첨부 2개 엔드포인트 구현 (행 32~33)
  - 첨부 업로드(editor, 문서 경로, multipart) · 첨부 조회 서빙(viewer, 첨부 경로, 바이너리) 엔드포인트를 구현.
    업로드는 `s07` 문서→WS 어댑터(`ws_role_for_document(EDITOR)`)로 게이트(문서 미존재→404, viewer/비멤버→403,
    비인증→401, admin bypass), 조회는 `ws_role_for_attachment(VIEWER)`로 게이트(첨부 미존재→404). 조회는 보관 첨부
    role 무관 404를 서비스가 처리하고 성공 시 `StreamingResponse` 반환. 모든 오류는 `s01` `ErrorResponse` 형태.
    서비스에 위임하고 상태 전이·버전 생성을 라우터에 두지 않음
  - 관찰 가능 완료: 두 엔드포인트가 editor/viewer·admin 통과·부적격 role 403·비인증 401·미존재 404로 게이팅되고,
    업로드가 `AttachmentRead`를 반환하며 조회가 미보관 첨부의 바이너리를 스트리밍하고 크기 초과→422가 됨을 라우터
    테스트로 확인
  - _Requirements: 1.1, 1.5, 2.1, 2.3, 2.4, 3.3, 3.4, 3.5, 3.6, 6.2, 6.3, 7.2, 7.3_
  - _Boundary: AttachmentRouter_
  - _Depends: 1.5, 2.1, 2.2_
- [x] 3.2 (P) 아카이브 스윕 스케줄러 어댑터·엔트리포인트 구현
  - 조정 로직과 분리된 스케줄러 어댑터 구현: 자기 세션으로 스윕을 1회 실행하는 엔트리포인트(`run_archival_sweep`,
    테스트·수동/외부 cron 실행 가능)와, `attachment_sweep_interval_seconds`가 0보다 크면 인프로세스 백그라운드
    스케줄러를 기동·주기 등록하고 0 이하이면 기동하지 않는 시작/종료 훅을 제공. 설정 접근은 단일 Settings 경유.
    APScheduler는 `s10`이 이미 도입한 의존성을 재사용(신규 추가 없음)
  - 관찰 가능 완료: 엔트리포인트 직접 호출 시 스윕이 자기 세션으로 1회 수행되고, 실행 주기 > 0 설정에서 스케줄러가
    기동되며 0 이하 설정에서는 기동되지 않음을 확인
  - _Requirements: 4.1, 5.1, 7.6_
  - _Boundary: ArchivalScheduler_
  - _Depends: 2.4_
- [x] 3.3 s01 라우터 조립·lifespan에 첨부 라우터·스케줄러 연결
  - `s01` 앱 조립 지점에 첨부 라우터를 등록하고 앱 lifespan 시작/종료에 아카이브 스케줄러 시작/종료 훅을 연결.
    조립·lifespan 방식은 `s01`·`s05`·`s07`·`s10`을 따르며 새 DB 마이그레이션을 추가하지 않음
  - 관찰 가능 완료: `uv run uvicorn app.main:app` 부팅 후 카탈로그 행 32~33 경로가 앱 라우트 목록에 노출되고,
    스케줄러가 lifespan에서 기동·정지되며 새 마이그레이션이 없음을 확인
  - _Requirements: 7.4, 7.5_
  - _Depends: 3.1, 3.2_

- [ ] 4. Validation: 통합·seam·불변식 검증
- [ ] 4.1 첨부 업로드·서빙·권한 게이팅 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: (1) editor가 이미지·파일을 업로드→응답 url로 조회 시 바이너리 반환→저장
    파일이 워크스페이스 격리 위치에 존재, (2) `s05` 멤버십 기반으로 업로드는 viewer 403·editor 통과, 조회는 viewer
    통과·비멤버 403·비인증 401·admin bypass(INV-1·2·3), (3) 응답이 `AttachmentRead`·`s01` `ErrorResponse` 규약을
    따르고 첨부 workspace_id가 대상 문서에서 확정됨(위조 불가)을 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 위 시나리오가 실제 앱 컨텍스트에서 모두 통과하고, 첨부 권한이 WS 단위 resolver로만 게이팅됨
    (문서·첨부별 개별 권한 없음)과 파일 WS 격리 저장이 확인된다
  - _Requirements: 1.1, 1.3, 2.1, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 7.1, 7.2_
  - _Depends: 3.3_
- [ ] 4.2 (P) 완전삭제 반응 보관 이동 seam 통합 테스트 (8.6)
  - 마이그레이션된 DB + 부팅 앱에서: 문서에 첨부를 올린 뒤 `s07`/`s10` 경로로 문서를 완전삭제(deleted)→아카이브
    스윕(`run_archival_sweep` 또는 서비스 직접 호출) 실행 후 그 첨부가 보관 폴더로 이동·is_archived=true가 되고
    `GET /attachments/{id}`가 admin 포함 404가 되며, 파일이 물리 삭제되지 않고 보관 위치에 존재함(INV-4), 보관된
    첨부를 active로 되돌리는 애플리케이션 경로가 없음(INV-7), 반복 스윕이 멱등함을 검증하는 통합 테스트 작성
  - 관찰 가능 완료: deleted↔보관 이동 seam이 실제 앱에서 통과하고, 보관=영구삭제(admin 포함 비노출·복원 없음)와
    물리 삭제 없음(보관 위치 파일 존재)이 확인되며, s12가 deleted 상태 관측으로만 판정함(전이 미수행)이 확인된다
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 6.2, 6.3, 6.4, 7.7_
  - _Depends: 3.3_
- [ ] 4.3 (P) 저장 참조 소멸 아카이브 seam 통합 테스트 (8.7)
  - 마이그레이션된 DB + 부팅 앱에서: 문서에 이미지를 붙여넣어(응답 url 참조를 본문에 포함) `s09` 경로로 저장→그
    이미지 참조를 제거한 본문으로 다시 저장(새 현재 버전)→아카이브 스윕 실행 후 그 이미지가 보관되고, 여전히
    참조되는 이미지는 보관되지 않으며, 붙여넣었으나 아직 저장하지 않은(현재 버전보다 나중 생성) 이미지는 보관되지
    않고(붙여넣기 보호), 일반 파일 첨부는 참조 소멸로 보관되지 않음을 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 저장↔참조 소멸 seam이 실제 앱에서 통과하고, 참조 유지/소멸·붙여넣기 보호·이미지 한정 경계가
    모두 확인되며, s12가 현재 버전 참조 관측으로만 판정함(저장·버전 생성 미수행)이 확인된다
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.5, 7.7_
  - _Depends: 3.3_

## Implementation Notes
- 테스트 하네스는 **공유 `notion_lite_test` MySQL DB**를 사용한다. 두 개 이상의 DB 기반 pytest
  프로세스를 동시에 같은 인스턴스에 돌리면 스퓨리어스 실패/에러가 발생한다(격리 재실행 시 사라짐).
  전체 스위트 회귀 검증은 항상 단일 프로세스로 직렬 실행할 것(구현→리뷰 순차 처리로 이미 보장).
- `AttachmentRead`는 `attachment` 모델에 `updated_at`이 없어 `TimestampedRead`가 아니라
  `ORMReadModel`을 상속하고 `id`/`created_at`을 명시 선언한다. `url`은 DB 컬럼이 아닌 파생값이라
  raw `model_validate(att)`는 실패하며, `AttachmentRead.from_attachment(att)`가 유일한 생성 경로
  (url=`/attachments/{id}` 산정). 다운스트림(2.1/2.2)은 이 생성자를 사용.
- `AttachmentStorage`가 반환하는 `file_path`는 **루트 상대 경로**(`{workspace_id}/{uuid}.ext`)라
  DB는 루트 독립 참조만 보유한다. 디스크 파일명은 서버 생성 uuid(경로 트래버설 방지), 원본명은
  DB `original_name`에만 보존. 물리 삭제 없음(INV-4) — `move_to_archive`는 `shutil.move`만.
- `AttachmentRepository` 쓰기 메서드(`insert`·`mark_archived`)는 `DocumentRepository` 관례대로
  `db.commit()`한다(스윕의 첨부 단위 커밋+예외격리와 업로드 요청 경로 모두에 정합).
  document/document_version은 **읽기 전용 조인**으로만 사용(status/current_version_id/버전 무변경, 관측만).
- (4.3 통합 테스트용 보강 메모) 8.7 스코프 단위 테스트는 문서당 버전 1개만 시드해 잘못된 조인
  (예: `DocumentVersion.document_id` 기준)을 판별하지 못한다. 소스 조인은
  `document.current_version_id == DocumentVersion.id`로 정확하나, 4.3 통합에서 현재 버전 문서에
  더 오래된 버전을 하나 더 두어 wrong-version-join 회귀를 잡도록 한다.
- (3.1) multipart 업로드(`File`/`Form`/`UploadFile`)는 FastAPI가 `python-multipart`를 하드 요구한다
  (없으면 임포트 시 RuntimeError). 3.1에서 `uv add python-multipart`(>=0.0.32)로 추가 — design
  §Tech Stack의 multipart 규약을 실동작시키는 최소 필수 의존성(design의 "신규 외부 의존성 없음"은
  이 지점에서 부정확). pyproject.toml·uv.lock 변경이 커밋에 포함됨. kind는 라우터에서 content-type
  추론(image/*→IMAGE, 그 외→FILE, 명시 Form 우선). 보관 첨부 404는 서비스가 처리(라우터 무처리).
- (3.3/통합 테스트용) 이 FastAPI 버전은 `include_router` 결과를 `_IncludedRouter`로 lazy 보관해
  `app.routes` 순회가 하위 경로를 top-level Route로 평탄화하지 않는다(→ `[]`). 라우트 노출 검증의
  권위 표면은 `app.openapi()["paths"]`다. 통합/조립 테스트는 openapi paths로 경로 존재를 확인할 것.
