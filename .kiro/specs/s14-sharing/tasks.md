# Implementation Plan — s14-sharing

> 문서 단위 읽기 전용 공유 링크 feature spec(최상위 L6). 모든 명령은 `backend/`에서 `uv run` 기준. 산출물 언어
> 한국어, 코드 식별자는 영어. `s01-contract-foundation`의 계약(카탈로그 행 34~37, `share_link`·`document`·
> `workspace`·`attachment` 모델, 권한 resolver `require_ws_role`, 세션 인증, 에러 모델, Base Schemas, 라우터
> 조립 지점·lifespan)과 `s05` 게이트(`workspace.is_shareable`)·실동작 `require_ws_role`, `s07` 문서→WS 어댑터
> (`ws_role_for_document`)·`DocumentRepository`·`DocumentStateEngine.active_descendants`·`MarkdownRenderer`,
> `s12` `AttachmentService.serve_attachment`·`AttachmentRepository.get`을 재사용하며 재정의하지 않는다.
> **재발급 통일 원칙(INV-8): 토글(PATCH)만 토큰을 유지하는 상태 기반 예외이고, 무효화(문서 trashed/deleted·게이트
> off)는 retire(비활성 + 토큰 교체)로 이전 토큰을 영구 무효화하며, 재공유는 발급(POST)이 새 토큰을 생성한다.**
> 무효화는 **공개 접근 시점 실시간 게이트 + 관측 기반 조정 스윕**의 이중 구조로 구현하며, s14는 문서 status·
> 워크스페이스 게이트를 읽어서 판정할 뿐 상태 전이·게이트 설정을 수행하지 않는다. share_link 물리 삭제 없음
> (INV-4, retire만). 공개 경로(행 36~37)는 인증 우회하되 토큰·게이트·status·WS 격리로 범위를 제한한다. s14는
> 최상위이며 어떤 feature도 s14를 import하지 않는다. 새 DB 마이그레이션을 추가하지 않는다.

- [ ] 1. Foundation: 모듈·스키마·설정·데이터 접근
- [x] 1.1 sharing 모듈 스캐폴드·공유 스키마 정의·설정 additive 확장
  - `app/sharing/` 패키지 골격 생성. `s01` Base Schemas를 상속한 링크 응답 스키마(id·document_id·token·is_enabled·
    created_at·파생 share_url=`/public/{token}`), 토글 요청 스키마(is_enabled), 공개 렌더 응답 스키마(공유 문서를
    루트로 하는 읽기 전용 중첩 트리: 노드는 id·title·content_html·children)를 정의. 공개 스키마는 workspace_id·
    created_by 등 내부 필드를 노출하지 않음(최소 노출)
  - `config.yml`과 `s01` 공용 Settings에 `share_token_bytes`(기본 32)·`share_invalidation_sweep_interval_seconds`
    (기본 3600, 0 이하이면 인프로세스 스케줄러 비활성) 필드를 additive로 추가. 모듈별 설정 파일·개별 로더 신설 금지
  - 관찰 가능 완료: 앱 부팅 시 새 설정 필드가 기본값으로 로드되고 기존 Settings 필드 계약이 유지되며, 링크 응답
    스키마가 `TimestampedRead` 규약으로 직렬화되고 share_url이 `/public/{token}` 형태로 산정되며, 공개 렌더 스키마가
    중첩 트리로 직렬화되고 새 DB 마이그레이션이 추가되지 않음을 확인
  - _Requirements: 2.1, 3.1, 4.1, 7.1, 7.5, 7.6_
  - _Boundary: SharingSchemas, Settings (s01 additive)_
- [x] 1.2 (P) ShareLinkRepository 구현 (r/w·토큰 생성·retire·무효화 스코프)
  - `s01` share_link·document·workspace 모델·세션 기반으로 문서 단위 링크 데이터 접근을 구현: 문서 id·토큰으로
    링크 조회, 발급/재발급 upsert(행이 없으면 생성·있으면 갱신하되 **항상 새 토큰 생성 + is_enabled=true**), 토글용
    상태 전환(is_enabled만 바꾸고 **토큰 유지**), retire(is_enabled=false + **토큰 교체**로 이전 토큰 영구 무효화),
    무효화 스코프 질의(is_enabled=true이면서 소속 문서 status가 trashed/deleted이거나 소속 워크스페이스 is_shareable이
    false인 링크 열거, 이미 비활성 링크는 제외). 토큰은 추측 불가하게 생성하고 token 컬럼 한도 내에 적재. share_link
    물리 삭제 없음(retire만), 상태 전이·게이트 설정은 하지 않음(관측만)
  - 관찰 가능 완료: 발급/재발급이 매번 이전과 다른 새 토큰·활성 링크를 만들고, 토글 상태 전환이 토큰을 유지하며,
    retire가 토큰을 교체하고 비활성화하고, 무효화 스코프 질의가 활성이면서 문서 trashed/deleted 또는 게이트 off인
    링크만 반환하며 이미 비활성 링크는 제외됨을 단위 테스트로 확인
  - _Requirements: 1.1, 2.1, 2.4, 2.5, 4.1, 5.1, 5.3, 5.6, 7.5_
  - _Boundary: ShareLinkRepository_

- [ ] 2. Core: 발급·토글·공개 렌더·링크 파일 서빙·무효화 조정
- [x] 2.1 (P) 공유 링크 발급·재발급·토글 유스케이스 구현
  - 발급/재발급 유스케이스: 대상 문서 존재 확인(부재→404), 문서 status가 active인지(비active→409)·소속 워크스페이스
    is_shareable가 true인지(게이트 off→409) 검사 후 새 토큰·활성 링크 발급(무효화 이후에도 새 토큰 재발급). 토글
    유스케이스: 문서 링크 로드(부재→404), 비활성화는 항상 허용(토큰 유지), 활성화는 게이트 on·문서 active일 때만
    허용(아니면 409, 토큰 유지). workspace_id·문서 로드는 `s07` `DocumentRepository` 재사용, 게이트 값은 워크스페이스
    관측. 토글은 새 토큰을 만들지 않는 유일한 상태 기반 예외
  - 관찰 가능 완료: 게이트 on·active 문서에서 발급이 새 토큰 활성 링크를 반환하고, 게이트 off·비active 문서 발급이
    409, 무효화된 문서 재발급이 이전과 다른 새 토큰을 만들며, 토글 off/on이 토큰을 유지한 채 상태만 전환하고 게이트
    off에서 활성화가 409가 됨을 단위 테스트로 확인
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.4, 2.5, 4.1, 4.2, 4.3_
  - _Boundary: ShareLinkService_
  - _Depends: 1.2_
- [x] 2.2 (P) 공개 읽기 전용 렌더 유스케이스 구현 (동적 하위·안전 렌더·참조 재작성·실시간 게이트)
  - 공개 렌더 유스케이스: 토큰으로 링크 로드(부재→404), 유효성=is_enabled·문서 status=active·게이트 on을 접근마다
    라이브로 관측(무효→404, 무효 조건 관측 시 그 자리에서 retire로 영구화=lazy retire). 유효 시 `s07`
    `active_descendants`로 접근 시점의 현재 active 하위 계층을 동적 수집(하위 추가는 자동 포함·trashed는 제외),
    각 문서 본문을 `s07` `load_current_content`+`MarkdownRenderer`로 안전 HTML 렌더, 렌더 HTML의 `/attachments/{id}`
    참조를 `/public/{token}/attachments/{id}`로 재작성(id 경계 정확히 구분), 읽기 전용 중첩 트리 반환(변경 동작 없음)
  - 관찰 가능 완료: 활성 링크가 문서+현재 active 하위 트리를 안전 렌더로 반환하고, 하위 추가 후 재요청 시 동적 포함·
    trashed 하위 제외, 문서 trashed·게이트 off 접근은 404이며 그 관측이 링크를 retire(토큰 교체)하고, content_html의
    첨부 참조가 링크 스코프 경로로 재작성되며 미존재 토큰은 404가 됨을 단위 테스트로 확인
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.1, 5.2, 7.7_
  - _Boundary: PublicShareService_
  - _Depends: 1.2_
- [x] 2.3 링크 경유 첨부 서빙 유스케이스 구현 (유효성·서브트리·격리·s12 위임)
  - 링크 경유 파일 서빙 유스케이스: 링크 유효성 검사(공개 렌더와 동일한 실시간 게이트, 무효→404로 게이트 off·문서
    trashed 시 파일 접근 함께 차단), 첨부 로드(`s12` `AttachmentRepository.get`, 부재→404), 첨부가 공유 문서 또는 그
    현재 active 하위에 속하고 동일 워크스페이스인지 검사(아니면 404, 범위·격리), 실제 바이너리·보관 차단은 `s12`
    `AttachmentService.serve_attachment`에 위임(보관 첨부는 role·경로 무관 404). 첨부 저장·격리·보관 판정은 재구현하지
    않음
  - 관찰 가능 완료: 공유 문서·active 하위에 속한 미보관 첨부는 링크 경유로 바이너리를 반환하고, 게이트 off·문서
    trashed 시 파일 접근 404, 보관 첨부 404, 범위 밖·다른 WS 첨부 404가 됨을 단위 테스트로 확인
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.7_
  - _Boundary: PublicShareService_
  - _Depends: 2.2_
- [x] 2.4 (P) 무효화 조정 스윕 구현 (status·게이트 관측 retire)
  - 관측 기반 무효화 조정 구현: 무효화 스코프 질의로 활성이면서 문서 status가 trashed/deleted이거나 게이트 off인
    링크를 열거하고, 각 링크를 retire(is_enabled=false + 토큰 교체)로 영구 무효화. 상태 전이·게이트 설정은 수행하지
    않고 문서 status·게이트 관측으로만 판정, 이미 비활성 링크는 스코프에서 제외되어 멱등, 개별 링크 예외는 격리.
    retire가 토큰을 교체하므로 이후 문서 복구·게이트 재활성에도 이전 토큰은 소멸해 재발급으로만 재공유 가능
  - 관찰 가능 완료: 문서 trashed/deleted·게이트 off인 활성 링크가 retire(비활성+토큰 교체)되고, 복구·게이트 재 on
    후에도 이전 토큰이 되살아나지 않으며, 반복 실행이 중복 retire/오류를 내지 않고, s14 코드에 상태 전이·게이트
    설정이 없음을 단위 테스트로 확인
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.7_
  - _Boundary: ShareInvalidationSweep_
  - _Depends: 1.2_

- [ ] 3. Integration: 라우터·스케줄러·부트스트랩 연결
- [x] 3.1 공유 4개 엔드포인트 구현 (행 34~37)
  - 공유 링크 발급(editor)·토글(editor)·공개 렌더(공개)·링크 경유 첨부 서빙(공개) 엔드포인트를 구현. 발급·토글은
    `s07` 문서→WS 어댑터(`ws_role_for_document(EDITOR)`)로 게이트(문서 미존재→404, viewer/비멤버→403, 비인증→401,
    admin bypass)하고 게이트 off·비active는 409. 공개 렌더·첨부 서빙은 인증·권한 게이트 없이(공개) 서비스가 토큰·
    게이트·문서 status·WS 격리로 범위를 제한하며 모든 거부를 404로 통일(존재 추정 차단). 발급/토글은 링크 응답,
    공개 렌더는 트리 응답, 파일은 바이너리 스트리밍. 모든 오류는 `s01` `ErrorResponse` 형태. 서비스에 위임하고 상태
    전이·게이트 설정·첨부 저장을 라우터에 두지 않음
  - 관찰 가능 완료: 발급·토글이 editor/admin 통과·viewer 403·비인증 401·문서 미존재 404·게이트 off 409로 게이팅되고
    링크 응답을 반환하며, 공개 렌더가 활성 링크의 문서 트리를 반환하고 무효·미존재 토큰을 404로 통일하며, 링크 경유
    첨부가 바이너리를 스트리밍함을 라우터 테스트로 확인
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.6, 4.1, 6.1, 6.2, 6.3, 6.4, 7.2, 7.3_
  - _Boundary: SharingRouter_
  - _Depends: 2.1, 2.2, 2.3_
- [x] 3.2 (P) 무효화 스윕 스케줄러 어댑터·엔트리포인트 구현
  - 조정 로직과 분리된 스케줄러 어댑터 구현: 자기 세션으로 무효화 스윕을 1회 실행하는 엔트리포인트
    (`run_invalidation_sweep`, 테스트·수동/외부 cron 실행 가능)와, `share_invalidation_sweep_interval_seconds`가
    0보다 크면 인프로세스 백그라운드 스케줄러를 기동·주기 등록하고 0 이하이면 기동하지 않는 시작/종료 훅을 제공.
    설정 접근은 단일 Settings 경유. APScheduler는 `s10`/`s12`가 이미 도입한 의존성을 재사용(신규 추가 없음)
  - 관찰 가능 완료: 엔트리포인트 직접 호출 시 스윕이 자기 세션으로 1회 수행되고, 실행 주기 > 0 설정에서 스케줄러가
    기동되며 0 이하 설정에서는 기동되지 않음을 확인
  - _Requirements: 5.1, 7.6_
  - _Boundary: ShareInvalidationScheduler_
  - _Depends: 2.4_
- [ ] 3.3 s01 라우터 조립·lifespan에 공유 라우터·스케줄러 연결
  - `s01` 앱 조립 지점에 공유 라우터를 등록하고 앱 lifespan 시작/종료에 무효화 스케줄러 시작/종료 훅을 연결. 조립·
    lifespan 방식은 `s01`·`s05`·`s07`·`s10`·`s12`를 따르며 새 DB 마이그레이션을 추가하지 않음
  - 관찰 가능 완료: `uv run uvicorn app.main:app` 부팅 후 카탈로그 행 34~37 경로가 앱 라우트 목록에 노출되고,
    무효화 스케줄러가 lifespan에서 기동·정지되며 새 마이그레이션이 없음을 확인
  - _Requirements: 7.4, 7.5_
  - _Depends: 3.1, 3.2_

- [ ] 4. Validation: 통합·seam·불변식 검증
- [ ] 4.1 발급·토글·게이트·재발급 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: (1) 게이트 on 워크스페이스의 active 문서에 editor가 발급→`GET /public/{token}`
    200→토글 off→동일 토큰 404→토글 on→동일 토큰 200(토큰 유지), (2) 게이트 off 워크스페이스에서 발급 409·활성화
    409, (3) `s05` 멤버십 기반으로 발급·토글이 viewer 403·editor 통과·비인증 401·admin bypass(INV-1·2·3), 문서·
    워크스페이스 미존재 404, (4) 응답이 링크 응답·`s01` `ErrorResponse` 규약을 따르고 공개 응답이 내부 필드를 노출하지
    않음을 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 위 시나리오가 실제 앱 컨텍스트에서 모두 통과하고, 공유 권한이 WS 단위 resolver로만 게이팅됨
    (문서별 개별 권한 없음)과 토글이 토큰을 유지함이 확인된다
  - _Requirements: 1.1, 1.4, 2.1, 2.2, 2.3, 2.6, 4.1, 4.2, 4.3, 7.1, 7.2_
  - _Depends: 3.3_
- [ ] 4.2 (P) 무효화·재발급(INV-8) seam 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: 발급 후 `s07`/`s10` 경로로 문서를 trashed→즉시 `GET /public/{token}` 404(실시간
    게이트)→무효화 스윕(`run_invalidation_sweep`) 실행→문서 복구→이전 토큰 여전히 404(재발급 필요)→발급(POST)으로
    새 토큰 200이고 이전 토큰과 다름; `s05` 게이트 off→즉시 404→게이트 재 on 후에도 이전 토큰 404·재발급 필요를
    검증하는 통합 테스트 작성. 반복 스윕이 멱등하고 s14가 상태 전이·게이트 설정을 수행하지 않음(관측만)을 확인
  - 관찰 가능 완료: 무효화↔재발급 seam이 실제 앱에서 통과하고, 무효화된 이전 토큰이 재발급 없이 되살아나지 않으며
    (INV-8), 재발급 토큰이 이전과 다르고, while-invalid 접근이 스윕 주기와 무관하게 즉시 차단됨이 확인된다
  - _Requirements: 4.4, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - _Depends: 3.3_
- [ ] 4.3 (P) 공개 렌더 동적 하위 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: 발급 후 `GET /public/{token}`이 문서+현재 active 하위 트리를 안전 렌더(스크립트
    제거)로 반환→공유 문서에 하위 문서 추가 후 재요청 시 새 하위가 트리에 동적 포함→그 하위를 trashed하면 트리에서
    제외됨을 검증하고, 공개 응답이 읽기 전용이며 변경 엔드포인트를 제공하지 않음, content_html 첨부 참조가 링크 스코프
    경로로 재작성됨을 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 동적 active 하위 포함/제외·안전 렌더·읽기 전용·참조 재작성이 실제 앱에서 모두 확인되고, s14가
    `s07` `active_descendants`·`MarkdownRenderer`를 재사용함(재구현 없음)이 확인된다
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 7.7_
  - _Depends: 3.3_
- [ ] 4.4 (P) 링크 경유 첨부 서빙·연동 차단 seam 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: 공유 문서(또는 active 하위)에 `s12`로 올린 첨부를 `GET /public/{token}/
    attachments/{aid}`로 다운로드→바이너리 반환(8.4); 게이트 off·문서 trashed 시 파일 접근도 404(8.5); 보관된 첨부는
    404(s12 규약 재사용); 다른 문서·다른 워크스페이스 첨부는 범위 밖 404(INV-6)를 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 링크 경유 파일 서빙 seam이 실제 앱에서 통과하고, 파일 접근이 게이트·문서 status와 함께 차단되며
    보관·범위 밖·격리 경계가 모두 확인되고, s14가 `s12` 첨부 서빙을 재사용함(저장·격리·보관 재구현 없음)이 확인된다
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.7_
  - _Depends: 3.3_
