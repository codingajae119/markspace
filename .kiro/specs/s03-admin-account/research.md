# Research Log — s03-admin-account

## Discovery Scope

- **Feature type**: Extension(기존 시스템 위 통합). `s01-contract-foundation`이 확정한 계약·인프라 위에 admin
  계정 생명주기 동작을 얹는 작업으로, integration-focused light discovery를 적용한다.
- **핵심 질문**: (1) admin 전용 게이팅을 `s01`의 어느 계약으로 실현할 것인가, (2) 삭제/비활동/재활성화를 어떤
  엔드포인트·필드로 표현할 것인가, (3) `s01` API 카탈로그의 소유권 표기와 roadmap/brief 경계 사이의 불일치를
  어떻게 정합시킬 것인가.

## 기존 계약 조사 (s01-contract-foundation)

| 조사 항목 | 발견 | 함의 |
|-----------|------|------|
| user 스키마 | `user(id, login_id UNIQUE, password_hash, name, email NULL, is_admin, is_active, is_deleted, created_at, updated_at)`, INDEX `(is_deleted, is_active)` | s03은 이 테이블만 대상으로 하며 새 컬럼·테이블을 추가하지 않는다. 목록·soft-delete 필터가 인덱스로 지원됨. |
| 세션 인증 | `AuthContext(user_id, is_admin)`, `get_current_user(request, db)` | admin 게이팅 근거를 `AuthContext.is_admin`으로 확보. 세션 write/clear는 s02 소유. |
| 권한 resolver | `require_ws_role(min_role)` (워크스페이스 스코프 + admin bypass) | s03 엔드포인트는 **워크스페이스 스코프가 아님**(전역 admin 전용). `require_ws_role`은 부적합. |
| 에러 모델 | `ErrorResponse`, `ErrorCode`(401/403/404/409/422/500), `DomainError` | 재사용. 중복 login_id→409, 미존재→404, 검증 실패→422, 비-admin→403. |
| 보안 헬퍼 | `hash_password`/`verify_password`(Argon2id, pwdlib) | 생성·재설정 시 `hash_password` 재사용(평문 저장 금지). |
| 스키마 규약 | `ORMReadModel`, `TimestampedRead`, `Page[T]`, `{Resource}Create/Read/Update` | User 스키마를 이 베이스에서 상속. 목록은 `Page[UserRead]`. |
| 부트스트랩 | `create_app()`에 "feature 라우터 조립 지점(초기 비어있음)" | s03 라우터를 이 지점에 include_router로 연결. |

## 핵심 설계 결정

### D1. admin 전용 게이트: `require_admin` 의존성 신설 (feature-local)

- **문제**: `s01`은 워크스페이스 스코프 `require_ws_role`만 제공하고, 전역 admin 전용 게이트는 제공하지 않는다.
  s03 엔드포인트(`/admin/users*`)는 특정 워크스페이스에 속하지 않는다.
- **결정**: `s01`의 `get_current_user`/`AuthContext.is_admin`을 재사용하는 얇은 `require_admin` 의존성을 s03가
  소유한다. `ctx.is_admin`이 false면 `DomainError(FORBIDDEN, 403)`.
- **경계 판단**: 이는 계약 변경이 아니라 feature 레벨 가드다. `AuthContext` 시그니처·판정 규칙을 바꾸지 않으며
  기존 계약 요소만 조합한다. 따라서 재검증 트리거가 아니다.
- **대안 기각**: `require_ws_role`에 workspace_id 없이 admin 판정만 우회 사용 — 계약 오용이며 스코프 혼동. 기각.

### D2. 삭제·비활동·재활성화 = 단일 PATCH(UserUpdate) 상태 전이

- **근거**: `s01` API 카탈로그 행 7 `PATCH /admin/users/{id}`가 REQ-2.3·2.4·2.5를 함께 소유한다.
- **결정**: 부분 갱신 `UserUpdate`(name?, email?, is_active?, is_deleted?)로 삭제(`is_deleted=true`)·
  비활동(`is_active=false`)·재활성화(`is_deleted=false`)·재활동(`is_active=true`)을 모두 표현한다.
  두 flag는 독립 상태로, 한쪽 변경이 다른쪽을 자동 변경하지 않는다(REQ-2.4/2.5, docs §2.1).
- **불변식**: repository는 어떤 경우에도 물리 DELETE를 발행하지 않는다(INV-4). flag 전환만 수행.

### D3. 애플리케이션 admin 승격 금지

- **근거**: docs REQ-2.1 "애플리케이션 상 admin 생성 기능 없음", `s01` 보안 고려사항 "admin은 수동 DB 설정".
- **결정**: `UserCreate`는 `is_admin`을 입력받지 않으며 항상 `is_admin=false`로 생성한다. `UserUpdate`도
  `is_admin`을 갱신 대상에 포함하지 않는다. admin 표시는 애플리케이션 경로로 변경 불가.

### D4. 단일 admin 잠금 방지 가드

- **문제**: 단일 admin 모델(docs §1, 부록 "다중 admin 미도입")에서 admin 자신을 삭제/비활동하면 서비스
  관리 주체가 사라진다.
- **결정**: 삭제·비활동 대상이 `is_admin=true`이면 거부한다(REQ-4.4, 5.5). 관리자 계정은 애플리케이션 경로로
  비활동·삭제되지 않는다(수동 DB 관리 영역).
- **에러**: 도메인 규칙 위반이므로 `409 conflict` 또는 `422 unprocessable`. bundle/상태 충돌 계열과 일관되게
  `409 conflict`로 표준화한다(에러 카탈로그의 "상태/불변식 충돌").

## 소유권 정합 노트 (계약 카탈로그 vs roadmap/brief)

- `s01` API 카탈로그 행 9 `POST /admin/workspaces/{id}/owner`(REQ-2.7)는 초기 기준선에서 소유 spec을 s03로
  표기했다. 그러나 **roadmap**(s05: "admin 소유권 변경")과 **brief**(§Out of Boundary: "소유권 변경(2.7)은 s05가
  소유, workspace 멤버십 자원 필요")는 이를 **s05-workspace**로 배정한다.
- **정합 결정**: workspace·workspace_member 자원이 s05에서 도입되므로 owner 변경은 **s05가 소유**한다. s03는
  계정(user 테이블) 생명주기만 소유하고 owner 변경 엔드포인트를 구현하지 않는다.
- 이는 카탈로그의 경로·메서드·요구 role·스키마를 변경하는 것이 아니라 **소유 spec 표기의 조정**이며, s05 spec
  생성 시점에 카탈로그 소유권 라인이 s05로 반영되어야 한다. design의 Out of Boundary와 Revalidation Triggers에
  명시한다.

## 위험 및 완화

| 위험 | 완화 |
|------|------|
| `s01` 계약(스키마·에러·인증) 변경 시 s03 회귀 | s03는 계약을 재구현하지 않고 재사용만 하므로 계약 변경은 재검증 트리거(design 명시)로 관리. |
| admin 자기 잠금 | D4 가드(관리자 삭제·비활동 거부). |
| 평문 비밀번호 유출 | 생성·재설정 모두 `s01` `hash_password` 경유, 응답 스키마에 `password_hash` 미노출. |
| owner 변경 소유권 혼동 | 위 소유권 정합 노트로 s05 배정 확정. |

## Synthesis 결과

- **Generalization**: admin 게이팅은 `require_admin` 단일 의존성으로 일반화(모든 s03 라우트 공통 적용). 향후
  다른 admin 전용 spec도 재사용 가능하나, 현재는 s03 소유로 최소 범위 유지.
- **Build vs adopt**: 인증·에러·해싱·스키마 베이스·모델은 전부 `s01` **adopt**. 신규 build는 admin 계정 도메인
  서비스·리포지토리·라우터·스키마·게이트 5개 파일뿐.
- **Simplification**: 별도 단일 사용자 상세 조회 엔드포인트는 카탈로그에 없으므로 추가하지 않는다(카탈로그
  변경=재검증 트리거 회피). 상태 전이는 단일 PATCH로 통합해 엔드포인트 수를 최소화.
