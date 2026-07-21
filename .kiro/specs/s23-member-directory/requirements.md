# Requirements Document

## Introduction

워크스페이스 owner(일반 사용자)가 멤버를 추가할 때, 현재는 대상 사용자의 raw `user_id` 를 직접
입력해야 한다. 시스템에는 일반 사용자를 열거할 수 있는 owner 접근 수단이 없고(사용자 목록 조회는
`GET /admin/users` 로 admin 전용, 워크스페이스 멤버 목록 조회 엔드포인트는 부재 — 계약 공백 S1),
이는 의도된 anti-enumeration 설계다.

이 기능은 그 설계를 **owner 범위로 좁게 완화**하여, owner 가 자신이 소유한 워크스페이스에 아직
멤버가 아닌 일반 사용자를 이름·이메일과 함께 열람·선택해 멤버로 추가할 수 있게 한다. 완화는
"owner(및 admin override)만", "이름·이메일·식별자만 노출", "admin·비활성·삭제 계정 제외",
"이미 멤버인 사용자 제외" 라는 최소 노출 원칙을 명시적 요구사항으로 못박아 통제한다.

## Boundary Context

- **In scope**:
  - owner(및 admin override)가 특정 워크스페이스에 **배정 가능한 사용자**(admin 아님·활성·비-멤버)를
    이름·이메일·식별자로 열거하는 능력.
  - 프론트 멤버 관리 화면에서 raw `user_id` 입력을 **선택 UI** 로 대체.
  - 배정 가능 목록에서 사용자·role 을 선택해 기존 멤버 추가 뮤테이션으로 추가.
- **Out of scope**:
  - 권위 있는 **전체 멤버 목록** 조회를 공개 능력으로 신설하는 것(S1 계약 공백 해소는 목표 아님).
    "비-멤버" 판정은 서버가 **내부적으로** 수행하며 멤버 열거 자체를 노출하지 않는다.
  - 계정 생성·상태 전이·비밀번호 재설정 등 계정 생명주기(= s03 admin 기능 소유).
  - self sign-up(제품 정책상 부재).
  - 사용자 검색어 필터·정렬 UI 의 상세 형태(있어도 되나 이 spec 의 수용 기준은 아님).
- **Adjacent expectations**:
  - 멤버 추가·role 변경·제거 뮤테이션과 owner 게이트(`require_ws_role(OWNER)`)·admin override 는
    기존 워크스페이스 spec(s05) 소유이며 **재사용**한다(재구현 없음).
  - 프론트 role 게이팅은 s16 `RequireRole` / s18 `MembershipRoleSource` 를 재사용한다.
  - 사용자 계정의 `is_admin`·`is_active`·`is_deleted` 플래그 의미는 기존 계정 spec(s01·s03) 정의를 따른다.

## Requirements

### Requirement 1: 배정 가능 사용자 열거 (anti-enumeration 완화)
**Objective:** 워크스페이스 owner 로서, 현재 워크스페이스에 배정 가능한 사용자 목록을 이름·이메일과 함께
열람하고 싶다. 그래야 raw `user_id` 를 몰라도 정확한 사용자를 멤버로 추가할 수 있다.

#### Acceptance Criteria
1. When owner 가 특정 워크스페이스의 배정 가능 사용자 목록을 요청하면, the Member Directory Service shall
   `is_admin=false` 이고 `is_active=true` 이며 `is_deleted=false` 이고 해당 워크스페이스의 기존 멤버가
   아닌 사용자만 반환한다.
2. The Member Directory Service shall 각 사용자에 대해 식별자(user id)·이름·이메일만 노출하고,
   그 외 계정 필드(`login_id`·상태 플래그·타임스탬프·비밀번호 관련 등)는 노출하지 않는다.
3. If 대상 사용자의 이메일이 없으면(null), the Member Directory Service shall 이메일을 빈 값으로
   표현하되 해당 사용자를 목록에서 제외하지 않는다.
4. When 배정 가능한 사용자가 한 명도 없으면, the Member Directory Service shall 빈 목록을 반환한다
   (오류가 아니다).
5. The Member Directory Service shall 목록을 결정적(deterministic) 순서로 제공하며, 다수 사용자
   환경을 위해 부분 조회(페이지 단위 조회)를 지원해야 한다.

### Requirement 2: owner 게이팅과 접근 통제 (보안 경계)
**Objective:** 시스템으로서, 사용자 열거 능력을 owner(및 admin override)로만 제한하고 싶다. 그래야
anti-enumeration 완화가 의도한 범위를 넘지 않는다.

#### Acceptance Criteria
1. If 요청자가 대상 워크스페이스의 owner 가 아니면(editor·viewer·비멤버), the Member Directory Service
   shall 배정 가능 사용자 목록 요청을 403 으로 거부한다.
2. Where 요청자가 admin 이면, the Member Directory Service shall owner 멤버가 아니어도 접근을
   허용한다(기존 admin override 정합).
3. If 요청자가 미인증(세션 없음·무효)이면, the Member Directory Service shall 401 로 거부한다.
4. The Member Directory Service shall owner(및 admin) 외 어떤 역할에게도 사용자 열거 결과를 제공하지
   않으며, 서버 측 owner 게이트를 유일한 접근 통제 경계로 삼는다.

### Requirement 3: 선택 기반 멤버 추가 UI
**Objective:** 워크스페이스 owner 로서, 사용자를 이름·이메일로 보고 목록에서 선택해 멤버로 추가하고
싶다. 그래야 `user_id` 를 몰라도 정확히 추가할 수 있다.

#### Acceptance Criteria
1. When owner 가 멤버 관리 화면을 열면, the Member Management UI shall 배정 가능 사용자 목록을 각
   사용자의 이름·이메일과 함께 표시한다.
2. The Member Management UI shall 기존 raw `user_id` 직접 입력 방식을 목록 선택 방식으로 대체한다.
3. When owner 가 목록에서 사용자와 role 을 선택해 추가를 확정하면, the Member Management UI shall
   선택된 사용자를 선택된 role 의 멤버로 추가 요청한다.
4. When 멤버 추가가 성공하면, the Member Management UI shall 해당 사용자를 배정 가능 목록에서
   제거(또는 목록을 갱신)하여 동일 사용자가 다시 선택되지 않게 한다.
5. If 배정 가능한 사용자가 없으면, the Member Management UI shall 선택 가능한 사용자가 없음을
   안내하고 추가 동작을 비활성화한다.
6. While 배정 가능 목록을 불러오는 중이면, the Member Management UI shall 로딩 상태를 표시하고
   추가 동작을 방지한다.

### Requirement 4: 오류·비정상 상태 표면화
**Objective:** 워크스페이스 owner 로서, 목록 조회나 멤버 추가가 실패하면 그 이유를 알고 싶다. 그래야
클라이언트 게이팅에 가려 오류가 조용히 사라지지 않는다.

#### Acceptance Criteria
1. If 배정 가능 사용자 목록 조회가 실패하면(403·401·기타), the Member Management UI shall 오류를
   인라인으로 표시하며, 클라이언트 게이팅으로 숨겼다는 이유로 오류를 억제하지 않는다.
2. If 멤버 추가 요청이 서버 오류(대상 미존재 404·이미 멤버 409·권한 403 등)로 실패하면, the Member
   Management UI shall 오류를 표시하고 로컬 상태를 시도 이전과 동일하게 유지한다(부분 반영 없음).
3. If 목록이 낡아(stale) 이미 멤버가 된 사용자를 추가 시도해 409 가 반환되면, the Member Management
   UI shall 409 를 표시하고 배정 가능 목록을 갱신한다.
