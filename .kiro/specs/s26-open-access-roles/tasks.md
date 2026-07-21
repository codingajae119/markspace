# Implementation Plan

- [ ] 1. 백엔드 2단계 role 근간 재정의 및 편집·관리 게이트 통일
- [x] 1.1 role 직렬화 enum을 owner/member 2값으로 축소
  - `MemberRole` 직렬화 enum을 owner·member 2값으로 재정의하고 editor·viewer 값 제거
  - 멤버 추가·role 변경 요청에 "editor"/"viewer" 문자열이 오면 계층에서 자동 422로 거부됨을 확인
  - 멤버 목록·워크스페이스 응답의 role 필드가 owner/member로만 직렬화됨을 확인
  - 관측 완료: editor/viewer role 요청이 422를 반환하고 owner/member 직렬화 단위 테스트가 통과
  - _Requirements: 1.3, 1.4, 5.5_
  - _Boundary: workspace/schemas_

- [x] 1.2 role 위계 2단계 재번호 및 전체 게이트 심볼 통일(원자적 리네임)
  - 워크스페이스 role 위계를 owner > member 2단계로 재번호(viewer/editor 심볼 삭제, editor를 member로 리네임, 하위 호환 alias 없음, 최종 수치 member=1·owner=2)하고 role 문자열→위계 매핑을 owner/member로 재정의
  - admin은 role·멤버십과 무관하게 항상 통과하는 판정(INV-3)을 그대로 유지
  - 편집·휴지통 게이트(문서 생성·이름변경·이동·휴지통이동, 잠금 획득·저장·취소, 첨부 업로드, 공유 발급·토글, 휴지통 목록·복원·완전삭제)의 최소 요구 role을 editor에서 member로 통일
  - 5개 읽기 게이트(문서 트리·상세, 버전 이력, 첨부 서빙, 워크스페이스 상세)의 최소 요구 role을 viewer에서 member로 치환(삭제된 viewer 심볼 잔존 참조 제거 — 읽기는 이 단계에서 임시로 멤버 게이트 유지, 전역 개방은 task 3에서 수행)
  - 강제 잠금 해제(force-unlock)와 워크스페이스 설정 변경·삭제·멤버 관리 게이트는 owner 전용으로 유지(변경 없음 확인)
  - 관측 완료: 백엔드가 임포트 에러 없이 기동하고 owner > member 위계·editor/viewer 심볼 부재·편집 게이트 member 통일이 단위 권한 테스트로 통과하며, 비멤버 읽기는 아직 거부(전역 개방 전)됨
  - _Requirements: 1.1, 1.2, 1.5, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 7.1, 7.4_
  - _Boundary: common/permissions, document/router, lock_version/router, attachment/router, sharing/router, trash/router, workspace/router (전체 게이트 심볼 스왑 — 무-alias 리네임이 강제하는 명시적 통합 작업)_

- [ ] 2. 워크스페이스 멤버 role 데이터 마이그레이션
- [x] 2.1 (P) editor·viewer→member 이관 마이그레이션 0004 작성
  - 3-스텝 ENUM 재편으로 upgrade 구현: 4값 임시 확장 → editor·viewer를 member로 UPDATE → owner·member 2값 축소
  - owner 행을 어느 스텝에서도 건드리지 않아 워크스페이스당 단일 owner 불변식 보존
  - downgrade는 역순·비대칭으로 구현: member→editor 복원, viewer는 복구하지 않음(의도된 비대칭)
  - 이관 후 저장 가능한 role 값 집합을 owner·member로만 제한
  - 관측 완료: `alembic upgrade head` 후 `SELECT DISTINCT role`이 {owner, member}이고 워크스페이스당 owner 수=1, `downgrade -1` 후 기존 member가 editor로 복원되고 구조 roundtrip이 통과
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - _Boundary: migrations_
  - _Depends: 없음 (role 코드 변경과 독립된 DB 계층 — task 1과 병렬 가능)_

- [ ] 3. 문서·첨부·워크스페이스 읽기 전역 개방
- [x] 3.1 활성 사용자 워크스페이스 읽기 게이트 신규(공통)
  - 활성 사용자 판정(미인증·비활성 401 거부)을 재사용하고 워크스페이스 존재만 확인(부재 404)하는 읽기 게이트를 공통 레이어에 신설(role 판정 없음)
  - 문서 트리 라우트가 workspace 도메인을 교차 import하지 않도록 게이트를 공통 레이어에 배치
  - 관측 완료: 게이트 단위 테스트에서 미인증→401, 워크스페이스 부재→404, 비멤버 활성 사용자→통과(403 발생 없음)
  - _Requirements: 3.2, 3.6, 3.7, 3.8, 7.2_
  - _Boundary: common/permissions_
  - _Depends: 1.2_

- [x] 3.2 문서 트리·상세 읽기 전역 개방 전환
  - 문서 id→워크스페이스 매핑(부재 404) 후 role 위임 없이 활성 사용자만 요구하는 문서 읽기 게이트를 신설
  - 문서 트리 조회는 공통 읽기 게이트로, 문서 상세 조회는 신규 문서 읽기 게이트로 라우트 게이트를 멤버 게이트에서 교체(전역 개방)
  - 관측 완료: 비멤버 활성 사용자가 존재하는 문서 상세·트리를 조회하면 403이 아닌 200을 받고, 부재 문서·워크스페이스는 404, 미인증은 401
  - _Requirements: 3.1, 3.2, 3.6, 3.7, 3.8, 7.2_
  - _Boundary: document/dependencies, document/router_
  - _Depends: 3.1_

- [x] 3.3 (P) 첨부 조회·다운로드 읽기 전역 개방 전환
  - 첨부 id→워크스페이스 매핑(부재 404) 후 role 위임 없이 활성 사용자만 요구하는 첨부 읽기 게이트를 신설하고 첨부 서빙 라우트를 멤버 게이트에서 교체
  - 보관(archived) 첨부의 서빙 차단이 권한 이전 서비스 단계에서 그대로 처리됨을 확인(읽기 게이트 전환이 이 동작을 바꾸지 않음)
  - 관측 완료: 비멤버 활성 사용자가 존재하는 첨부를 조회·다운로드하면 200, 부재 첨부는 404, 미인증은 401
  - _Requirements: 3.4, 3.6, 3.7, 3.8, 7.2_
  - _Boundary: attachment/dependencies, attachment/router_
  - _Depends: 1.2_

- [x] 3.4 (P) 워크스페이스 상세 role 주입 및 읽기 전역 개방 전환
  - 워크스페이스 상세 서비스에 호출자 컨텍스트를 전달해 호출자 관점 role(owner/member/비멤버 null)을 주입(admin 상승 없음)하고, 상세 라우트를 멤버 게이트에서 활성 사용자 게이트로 교체
  - 관측 완료: 비멤버 활성 사용자가 워크스페이스 상세를 조회하면 이름·설정(is_shareable·보관일)을 200으로 받고 role 필드는 null, 부재 워크스페이스는 404
  - _Requirements: 3.5, 3.7, 3.8, 7.2_
  - _Boundary: workspace/service, workspace/router_
  - _Depends: 1.2_

- [x] 3.5 버전 이력 읽기 전역 개방 전환
  - 버전 이력 조회 라우트가 신규 문서 읽기 게이트를 재사용하도록 멤버 게이트에서 교체(신규 교차 import 없이 기존 문서 dependencies 재사용)
  - 관측 완료: 비멤버 활성 사용자가 존재하는 문서의 버전 이력을 조회하면 200, 부재 문서는 404
  - _Requirements: 3.3, 3.6, 3.7, 3.8, 7.2_
  - _Boundary: lock_version/router_
  - _Depends: 3.2_

- [ ] 4. 프론트엔드 role 모델·표시·게이팅 정합
- [x] 4.1 (P) 공용 role 모델·권한 판정 미러 정합
  - 공용 role enum을 백엔드와 동일 수치(member=1, owner=2)로 재번호하고 role union·문자열→enum 번역을 owner/member 2값으로 정합
  - 편집성 UI 게이팅 소비처의 최소 요구 role을 editor에서 member로 전환하고 admin 항상 통과·null 거부 판정은 유지
  - 관측 완료: role 모델·권한 판정 단위 테스트에서 owner≥member·member≥member·admin 통과·null 거부가 통과하고 BE/FE 수치가 일치
  - _Requirements: 6.1, 6.4_
  - _Boundary: shared/auth_
  - _Depends: 1.2_

- [x] 4.2 멤버 role 타입·선택 UI·복원 값 집합 정합
  - feature role 타입을 owner/member로 축소하고 역할 선택 UI 옵션을 owner·member 2값으로 제한
  - 멤버 목록·현재 워크스페이스 표시의 role 라벨을 owner/member로 표기하고, 재로그인·새로고침 role 복원(s24) 메커니즘은 유지한 채 복원 값 집합만 owner/member로 정합
  - 관측 완료: 역할 선택 UI가 owner·member만 노출하고, 재로그인 후 서버 제공 owner/member role이 복원되는 것이 E2E로 통과
  - _Requirements: 6.2, 6.3, 6.5_
  - _Boundary: features/workspace_
  - _Depends: 4.1_

- [ ] 5. 회귀 스위트·불변식·문서 정합
- [x] 5.1 (P) 백엔드 단위 권한 테스트 갱신
  - 권한·멤버십·admin 우회 단위 테스트를 새 2단계 모델로 갱신(owner>member 위계, editor/viewer 심볼 부재, editor/viewer role 요청 422, admin bypass 유지)
  - 관측 완료: 갱신된 백엔드 단위 권한 테스트 스위트가 전부 통과
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 5.5, 7.1, 7.5_
  - _Boundary: tests(unit permissions)_
  - _Depends: 1.2_

- [x] 5.2 (P) 마이그레이션 roundtrip·head-guard 정합
  - 마이그레이션 구조 roundtrip 테스트를 ENUM 구조 복귀 반영으로 갱신하고, L2·L4·L5·L6 및 workspace·attachment 스위트의 head/리비전-체인 가드를 head=0004·4-리비전 선형 체인으로 갱신
  - 관측 완료: head-guard·roundtrip 스위트가 전부 통과하고 마이그레이션 개수/head 단언이 0004 기준으로 정합
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 7.5_
  - _Boundary: tests(migration/head-guard)_
  - _Depends: 2.1_

- [x] 5.3 (P) L2~L6 권한 경계 스위트 갱신
  - 읽기 경로 경계 테스트 기대값을 403에서 200으로 전환(비멤버 활성 사용자 문서·트리·버전·첨부·워크스페이스 상세 200)하고 편집 경계를 member 통일로 갱신
  - 휴지통 목록은 전역 개방에서 제외되어 멤버(owner 또는 member) 이상만 접근함을 확인하고, 공유 링크 게스트 경로의 토큰·is_shareable 게이트가 불변임을 확인
  - owner 전용 관리 작업(설정 변경·삭제·멤버 관리·force-unlock)이 비-owner에서 거부됨을 확인
  - 관측 완료: 갱신된 L2~L6 권한 경계 스위트가 전부 통과하고 읽기 200·편집 member·관리 owner·휴지통 제외·공유 게스트 불변이 각각 검증됨
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.8, 4.6, 5.1, 5.2, 5.3, 5.4, 7.2, 7.3, 7.4, 7.5_
  - _Boundary: tests(integration L2-L6)_
  - _Depends: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 5.4 (P) 프론트엔드 role 테스트 갱신
  - role 모델·권한 판정·역할 선택·role 복원 관련 프론트엔드 테스트를 owner/member 2단계 모델로 갱신
  - 관측 완료: 갱신된 프론트엔드 role 관련 테스트 스위트가 전부 통과
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.5_
  - _Boundary: tests(frontend role)_
  - _Depends: 4.1, 4.2_

- [x] 5.5 (P) steering 문서 role 문구 정합
  - product·tech steering 문서의 "owner/editor/viewer"·"viewer 권한" 문구를 owner/member 2단계 모델로 갱신(에디터 읽기 렌더 모드 명칭 "viewer mode"는 role 이름이 아니므로 유지)
  - 관측 완료: steering 문서에 삭제된 viewer role 흔적이 남지 않고 owner/member 모델과 정합
  - _Requirements: 1.1_
  - _Boundary: steering docs_
  - _Depends: 1.2_

- [ ] 6. 최종 통합 검증
- [x] 6.1 전체 회귀 스위트 실행 및 경계 불변식 확인
  - 백엔드 전체·프론트엔드 전체 테스트 스위트와 마이그레이션 upgrade/downgrade를 실행하고, 읽기 전역 개방(비멤버 200)·편집 member 통일·관리 owner 전용·휴지통 개방 제외·공유 게스트 불변·admin bypass가 종단에서 정합함을 확인
  - 관측 완료: 백엔드·프론트엔드 전체 스위트가 전부 통과하고 읽기 완화·편집·관리·휴지통·공유·admin 경계 불변식이 종단 검증으로 확인됨
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  - _Depends: 1.1, 1.2, 2.1, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 5.1, 5.2, 5.3, 5.4, 5.5_

## Implementation Notes
- 4.2 boundary 확장(설계 근거): design.md "Modified Files — Frontend"가 편집성 UI 게이팅 소비처의 `minimum: Role.EDITOR → Role.MEMBER` 스왑을 명시하나, 이 소비처는 features/document·features/sharing·features/editor 및 s24 복원 경로(app/workspace-context)에 걸쳐 있어 어느 task의 `_Boundary:_`에도 명시되지 않았다(4.1=shared/auth, 4.2=features/workspace). no-alias 리네임으로 Role.EDITOR/VIEWER 심볼이 삭제되어 이 소비처들이 컴파일·게이팅 불능이 되므로, 4.2가 승인된 설계의 FE 미러 파일 목록 전체(features 전 도메인 소스 소비처 + s24 복원 경로)를 소유하도록 확장한다. 교차-feature 게이팅 TEST 갱신은 5.4로 이연(중간 phased-red).
- 소스 갭 발견·보정(5.1 중): design "Modified Files — Backend"와 task 1.2/2.1 boundary가 `app/models/workspace.py`의 SQLAlchemy `Enum("owner","editor","viewer")` 선언을 누락했다. 마이그레이션 0004가 DB 컬럼을 `ENUM('owner','member')`로 바꾼 뒤 ORM이 `member` 행을 읽으면 SQLAlchemy Enum result processor가 `LookupError: 'member' is not among the defined enum values`를 던져 resolver.resolve·멤버십 조회·WS 상세 role 주입이 프로덕션에서 깨진다(create_all 기반 단위 테스트도 동일 실패). 이는 role 근간 재정의(task 1.2)의 일부이므로 `Enum("owner","member",...)`로 보정했다(무-alias 2단계 모델 완성). 단위 테스트 786건 통과 검증. 잔존 45 errors는 `tests/integration_L2/helpers.py`의 editor/viewer 시드에서 파생(5.3 소관), 3 deselected는 head-guard(5.2).
