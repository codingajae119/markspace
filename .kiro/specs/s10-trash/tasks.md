# Implementation Plan — s10-trash

> 휴지통 API·UX·보관 배치 feature spec. 모든 명령은 `backend/`에서 `uv run` 기준. 산출물 언어 한국어,
> 코드 식별자는 영어. `s01-contract-foundation`의 계약(카탈로그 행 29~31, `document`·`workspace` 모델, 권한
> resolver `require_ws_role`, 세션 인증, 에러 모델, Base Schemas·`Page`, Settings, 라우터 조립 지점·lifespan)과
> `s05`가 실동작시킨 `require_ws_role`·워크스페이스 `trash_retention_days`, `s07`의 `DocumentStateEngine`
> primitive(`identify_bundles`·`restore_bundle`·`purge_bundle`)·`Bundle` DTO·`DocumentRepository.get_workspace_id`를
> 재사용하며 재정의하지 않는다. **상태 전이·묶음 규칙(INV-10·11·12)은 s07 엔진에 위임하고 s10 어디에도 status/
> trashed_at 직접 갱신을 두지 않는다.** 문서 물리 삭제 없음(INV-4). s10은 s12·s14를 import하지 않는다.

- [ ] 1. Foundation: 모듈·스키마·설정·데이터 접근·권한 어댑터
- [x] 1.1 trash 모듈 스캐폴드·표시 스키마 정의·스케줄러 의존성 추가
  - `app/trash/` 패키지 골격 생성. `s01` Base Schemas를 상속한 휴지통 묶음 표시 스키마 정의: 묶음
    식별자(= 루트 문서 id)·루트 제목·소속 워크스페이스·묶음 공통 trashed_at·보관 만료 예정 시각·구성원 수·구성원
    요약 목록. 보관 만료 예정 시각은 저장하지 않고 응답 시 산정되는 파생값임을 스키마 규약으로 명시
  - 주기 실행 스케줄러 외부 의존성을 `uv add`로 추가(`pyproject.toml`·`uv.lock` 갱신)
  - 관찰 가능 완료: s07 엔진의 묶음 DTO로부터 휴지통 묶음 표시 스키마가 직렬화되고 목록 응답이 `Page` 규약을
    따르며, 추가한 스케줄러 의존성이 `uv run python -c` 임포트로 로드됨을 확인
  - _Requirements: 1.3, 6.2_
  - _Boundary: TrashSchemas_
- [x] 1.2 (P) TrashRepository 구현 (보관일 조회·스윕 스코프)
  - `s01` workspace 모델·세션 기반으로 워크스페이스 보관일(trash_retention_days) 조회와 trashed 문서를 보유한
    워크스페이스 열거(스윕 스코프 축소)를 제공. 문서 상태 전이·묶음 식별은 하지 않음(엔진 위임)
  - 관찰 가능 완료: 보관일 조회가 워크스페이스 설정값을 반환하고, trashed 문서가 있는 워크스페이스만 스윕
    스코프로 열거되며 없으면 빈 목록을 반환함을 단위 테스트로 확인
  - _Requirements: 1.4, 4.3_
  - _Boundary: TrashRepository_
- [x] 1.3 (P) 묶음 id → workspace_id 권한 어댑터 구현
  - 묶음 id(= 루트 문서 id)로부터 소속 workspace_id를 `s07` 문서→WS 조회로 확정(미존재→404)해 `s01`
    `require_ws_role(EDITOR)`에 주입하는 얇은 어댑터 구현. `/workspaces/{id}/trash`는 경로 id를 직접
    workspace_id로 사용. resolver 위계 비교·admin bypass 로직은 재구현하지 않음. 묶음 루트 유효성은 서비스
    단계 엔진이 판정
  - 관찰 가능 완료: 존재하는 묶음 문서 id로 어댑터가 workspace_id를 추출해 권한 판정에 위임하고, 미존재 문서
    id→404, 보호 라우트 스텁에서 editor 미충족→403·admin→통과가 됨을 단위 테스트로 확인
  - _Requirements: 5.1, 5.4_
  - _Boundary: BundleWsAdapter_
- [x] 1.4 (P) 배치 실행 주기 설정을 단일 Settings에 additive 확장
  - `config.yml`과 `s01` 공용 Settings에 배치 실행 주기(기본 3600초, 0 이하이면 인프로세스 스케줄러 비활성)
    필드를 additive로 추가. 보관일 기본값은 기존 `default_trash_retention_days`(30) 재사용. 모듈별 설정 파일·
    개별 로더를 신설하지 않음
  - 관찰 가능 완료: 앱 부팅 시 새 설정 필드가 기본값으로 로드되고 기존 Settings 필드 계약이 그대로 유지되며,
    새 DB 마이그레이션이 추가되지 않음을 확인
  - _Requirements: 6.7_
  - _Boundary: Settings (s01 additive)_

- [ ] 2. Core: 휴지통 서비스 및 보관 스윕 (상태 전이는 엔진 위임)
- [x] 2.1 휴지통 묶음 목록 투영 구현
  - 엔진 묶음 열거 결과를 표시 스키마로 투영하는 목록 유스케이스 구현: 워크스페이스의 trashed 묶음 전체를
    엔진 식별 결과로 구성(무엇이 묶음인지 재판정하지 않음)하고, 각 묶음의 보관 만료 예정 시각 = 묶음 trashed_at +
    워크스페이스 보관일로 산정. trashed 묶음만 포함하고 deleted는 노출하지 않음. 본인 삭제분 외 전체 노출(권한은
    라우터 게이트)
  - 관찰 가능 완료: 여러 시점에 삭제된 묶음이 별개로 열거되고 각 묶음의 만료 예정 시각이 trashed_at + 보관일과
    일치하며 목록이 `Page` 규약을 따르고 deleted 문서가 포함되지 않음을 단위 테스트로 확인
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_
  - _Boundary: TrashService_
  - _Depends: 1.1, 1.2_
- [x] 2.2 묶음 복구·완전삭제 위임 구현
  - 복구·완전삭제 유스케이스를 엔진 primitive 호출로 구현: 복구는 엔진 복구 primitive를 해당 묶음 루트에 호출해
    묶음 전체를 active로 되돌리되 복구 위치·순서·자동 재중첩 규칙은 엔진 결정에 위임; 완전삭제는 엔진 완전삭제
    primitive를 호출해 해당 묶음만 즉시 deleted(물리 삭제 없는 종착 전환)로 전환. 유효하지 않은 묶음 루트→404
    전파, 요청 묶음에만 적용(다른 독립 묶음 무영향), 첨부 보관 이동·공유 무효화는 소유하지 않음. status/trashed_at을
    직접 갱신하지 않음
  - 관찰 가능 완료: 복구가 엔진 복구 primitive를, 완전삭제가 엔진 완전삭제 primitive를 정확한 루트로 호출하고,
    유효하지 않은 루트→404가 되며, 완전삭제 후 대상 묶음은 deleted·다른 묶음은 불변이고 s10 코드에 status/
    trashed_at 직접 갱신이 없음을 단위 테스트로 확인
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.5, 3.7, 6.1_
  - _Boundary: TrashService_
  - _Depends: 1.1_
- [ ] 2.3 (P) 보관 만료 자동 영구삭제 스윕 로직 구현
  - 주입된 현재 시각에 대해 만료 묶음을 산정·전환하는 멱등 스윕 로직 구현: trashed 문서 보유 워크스페이스별로
    엔진 묶음 식별을 호출하고, 각 묶음의 trashed_at + 워크스페이스 보관일 ≤ 현재 시각이면 엔진 완전삭제 primitive로
    전환. 만료 여부는 각 묶음 trashed_at 기준 독립 산정(다른 묶음이 기준에 영향 없음), 미만료 묶음은 유지, 서로 다른
    trashed_at 자식/부모 묶음은 각자 만료(자식 먼저 허용), 이미 deleted/복구된 묶음은 오류 없이 건너뜀. 묶음 단위
    예외를 격리해 전체 스윕이 중단되지 않게 함. 상태 전이는 엔진 위임
  - 관찰 가능 완료: 현재 시각 주입 시 만료 묶음만 deleted로 전환되고 미만료 묶음은 유지되며, 한 묶음 만료가 다른
    묶음 기준을 바꾸지 않고, 반복 실행이 중복 전이나 오류를 일으키지 않음을 단위 테스트로 확인
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 6.1_
  - _Boundary: RetentionSweepService_
  - _Depends: 1.2_

- [ ] 3. Integration: 라우터·스케줄러·부트스트랩 연결
- [ ] 3.1 휴지통 3개 엔드포인트 구현
  - 휴지통 목록(editor, 워크스페이스 경로) · 묶음 복구(editor, 묶음 경로) · 묶음 완전삭제(editor, 묶음 경로)
    엔드포인트를 구현. 목록은 경로 id를 workspace_id로 사용하고, 복구·완전삭제는 묶음→WS 어댑터로 workspace_id를
    주입해 editor 이상만 통과(viewer/비멤버→403, admin bypass, 비인증→401, WS 단위 판정). 완전삭제 엔드포인트는
    되돌릴 수 없는 파괴적 조작임을 API 설명에 표기하고 확인 절차는 프론트엔드 UX 계약임을 명시. 서비스에 위임
  - 관찰 가능 완료: 세 엔드포인트가 editor·admin 통과·viewer/비멤버 403·비인증 401로 게이팅되고, 목록이
    `Page[TrashBundleRead]`를 반환하며 복구·완전삭제가 204를 반환하고 유효하지 않은 묶음 루트→404가 됨을 라우터
    테스트로 확인
  - _Requirements: 1.7, 1.8, 2.5, 2.6, 3.4, 3.6, 5.1, 5.2, 5.3, 5.5, 5.6, 6.3, 6.4, 6.5_
  - _Boundary: TrashRouter_
  - _Depends: 1.3, 2.1, 2.2_
- [ ] 3.2 보관 스윕 스케줄러 어댑터·엔트리포인트 구현
  - 스윕 로직과 분리된 스케줄러 어댑터 구현: 자기 세션으로 스윕을 1회 실행하는 엔트리포인트(테스트·수동/외부
    cron 실행 가능)와, 설정된 실행 주기가 0보다 크면 인프로세스 백그라운드 스케줄러를 기동·주기 등록하고 0 이하이면
    기동하지 않는 시작/종료 훅을 제공. 설정 접근은 단일 Settings 경유
  - 관찰 가능 완료: 엔트리포인트를 직접 호출하면 스윕이 자기 세션으로 1회 수행되고, 실행 주기 > 0 설정에서
    스케줄러가 기동되며 0 이하 설정에서는 기동되지 않음을 확인
  - _Requirements: 4.1, 6.7_
  - _Boundary: RetentionScheduler_
  - _Depends: 2.3, 1.4_
- [ ] 3.3 s01 라우터 조립·lifespan에 휴지통 라우터·스케줄러 연결
  - `s01` 앱 조립 지점에 휴지통 라우터를 등록하고 앱 lifespan 시작/종료에 스케줄러 시작/종료 훅을 연결. 조립·
    lifespan 방식은 `s01`·`s05`·`s07`을 따르며 새 DB 마이그레이션을 추가하지 않음
  - 관찰 가능 완료: `uv run uvicorn app.main:app` 부팅 후 카탈로그 행 29~31 경로가 앱 라우트 목록에 노출되고,
    스케줄러가 lifespan에서 기동·정지되며 새 마이그레이션이 없음을 확인
  - _Requirements: 6.5, 6.6_
  - _Depends: 3.1, 3.2_

- [ ] 4. Validation: 통합·불변식 검증
- [ ] 4.1 휴지통 API·권한 게이팅 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: (1) s07로 문서를 삭제(trashed)한 뒤 휴지통 목록이 묶음·만료 예정 시각을
    반환→복구로 목록에서 사라지고 문서가 active로 돌아옴→재삭제 후 완전삭제로 deleted 종착이 됨(엔진 primitive가
    라우터를 통해 소비됨), (2) `s05` 멤버십 기반으로 viewer는 목록·복구·완전삭제 403·editor 통과(본인 삭제분 외
    묶음 포함)·admin bypass·비인증 401(INV-1·2·3), (3) 응답이 `TrashBundleRead`·`Page`·`s01` `ErrorResponse` 규약을
    따르고 새 마이그레이션 미추가를 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 위 시나리오가 실제 앱 컨텍스트에서 모두 통과하고, 휴지통 권한이 WS 단위 resolver로만 게이팅됨
    (묶음·문서별 개별 권한 없음)과 deleted 종착(복원 경로 없음)이 확인된다
  - _Requirements: 1.1, 1.7, 1.8, 2.1, 2.5, 3.1, 3.4, 5.1, 5.2, 5.3, 5.5, 6.2, 6.3, 6.5, 6.6_
  - _Depends: 3.3_
- [ ] 4.2 (P) 보관 만료 자동 영구삭제 스윕 통합·독립 타이머 검증
  - 마이그레이션된 DB에서 여러 워크스페이스·여러 묶음을 서로 다른 trashed_at으로 만든 뒤, 현재 시각을 주입한
    스윕이 (1) 만료 묶음만 deleted로 전환하고 미만료·타 워크스페이스 묶음은 불변, (2) 각 묶음 만료가 자기 trashed_at
    기준으로 독립 산정되어 한 묶음 처리가 다른 묶음 기준에 영향 없음(자식/부모 서로 다른 trashed_at이면 자식 먼저
    만료), (3) 이미 deleted/복구된 묶음을 만나도 오류 없이 건너뛰고 반복 실행이 멱등함을 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 만료 경계·묶음 독립 타이머·멱등성 시나리오가 실제 DB에서 모두 통과하고, 스윕이 엔진 묶음
    식별·완전삭제 primitive만으로 동작함(INV-12·10)이 확인된다
  - _Requirements: 4.1, 4.2, 4.4, 4.5, 4.6, 4.7, 6.1_
  - _Depends: 3.2_
