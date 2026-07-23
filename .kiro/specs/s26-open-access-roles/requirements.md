# Requirements Document

## Project Description (Input)
역할 모델을 owner/editor/viewer 3단계 위계에서 owner/member 2단계로 재편하고, 문서 읽기 권한 경계를 전역으로 완화한다.

배경: 현재 시스템은 s01-contract-foundation이 정의한 워크스페이스 단위 3단계 위계(Role IntEnum: OWNER≥EDITOR≥VIEWER)로 모든 권한을 판정한다(INV-1: 워크스페이스 멤버십으로만 판정, 문서별 권한 없음). viewer 권한을 삭제하고 편집 가능한 member 개념으로 단순화하며, 읽기 접근을 전면 개방하려 한다.

(전체 입력은 spec 초기화 시 기록됨 — 아래 Introduction·Requirements가 확정본이다.)

## Introduction

이 기능은 markspace의 권한 모델을 두 축에서 재편한다.

1. **역할 2단계화**: owner/editor/viewer 3단계 위계를 owner/member 2단계로 축소한다. viewer를 삭제하고, 편집 가능한 모든 비-owner 멤버를 member로 통합한다. 기존 editor·viewer 멤버는 member로 이관되어 편집 권한을 유지한다.
2. **읽기 전역 개방**: 인증된 활성 사용자면 워크스페이스 멤버십과 무관하게 모든 워크스페이스의 문서·첨부·버전·워크스페이스 상세를 읽을 수 있다. 읽기에 한해 기존 INV-1(워크스페이스 단위 게이팅)을 해제한다. 편집·관리 권한은 여전히 멤버십 단위로만 판정한다.

이 재편은 s01-contract-foundation이 정의한 권한 근간(Role 위계·MemberRole 직렬화·workspace_member.role ENUM)과 이를 미러하는 프론트엔드 role 모델, 그리고 L1~L6 통합 체크포인트의 권한 경계 테스트에 걸친다.

## Boundary Context

- **In scope**:
  - 워크스페이스 role을 owner/member 2단계로 재정의(위계·직렬화·저장 값 집합).
  - 기존 editor·viewer 멤버십의 member 이관(데이터 마이그레이션).
  - 5개 읽기 엔드포인트(문서 트리·문서 상세·버전 이력·첨부 조회/다운로드·워크스페이스 상세)의 전역 개방.
  - 편집 계열 동작(문서 생성/이름변경/이동/휴지통이동, 잠금/저장/취소, 첨부 업로드, 공유 발급/토글, 휴지통 조회/복원/완전삭제)의 게이트를 "멤버(owner 또는 member)"로 통일.
  - 관리 계열 동작(워크스페이스 설정 변경/삭제, 멤버·assignable 조회, 멤버 추가/변경/제거, force-unlock)의 owner 전용 유지.
  - admin bypass(INV-3) 유지.
  - 프론트엔드 role 모델·역할 표시·선택 UI·게이팅 판정의 owner/member 정합.
  - L1~L6 및 단위 권한 테스트의 새 모델 반영.
- **Out of scope**:
  - 문서별 개별 권한 도입(여전히 없음 — 편집·관리는 워크스페이스 단위 판정 유지).
  - 읽기 전용 공유 링크(s14) 재설계 — 미인증 외부 접근의 토큰·is_shareable 게이트는 그대로 유지.
  - 새로운 관리 기능·역할 추가, 버전 rollback 등 신규 기능.
  - 계정 활성/삭제 판정 로직 자체 변경(auth 계층 재사용).
- **Adjacent expectations**:
  - 인증 계층은 "활성 사용자"(인증됨 + 활성 계정) 판정을 계속 제공한다 — 전역 읽기는 이 판정을 재사용한다.
  - s24 role 복원(재로그인·새로고침) 메커니즘은 유지되며, 복원되는 role 값 집합만 owner/member로 바뀐다.
  - steering 문서(`product.md`, `tech.md`)의 "owner/editor/viewer"·"viewer 권한" 문구는 본 변경에 맞춰 갱신되어야 한다(문서 정합).

## Requirements

### Requirement 1: 2단계 역할 모델(owner/member)
**Objective:** As a 시스템 운영자, I want 워크스페이스 역할을 owner/member 2단계로 단순화, so that viewer/editor 구분 없이 편집 가능한 멤버와 관리 owner만 남긴다.

#### Acceptance Criteria
1. The 권한 시스템 shall 워크스페이스 role을 owner와 member 두 값으로만 정의한다.
2. The 권한 시스템 shall role 위계를 owner > member로 판정한다 (owner는 member의 모든 권한을 포함).
3. Where 멤버 role이 API 요청/응답에 표현될 때, the 워크스페이스 서비스 shall 값을 "owner" 또는 "member" 문자열로 직렬화한다.
4. If 멤버 추가·role 변경 요청에 owner/member 이외의 role 문자열(예: "editor"·"viewer")이 오면, then the 워크스페이스 서비스 shall 해당 요청을 거부한다.
5. The 권한 시스템 shall admin 사용자를 role·멤버십과 무관하게 항상 통과시킨다 (INV-3 유지).

### Requirement 2: 기존 역할 데이터 이관
**Objective:** As a 시스템 운영자, I want 기존 editor·viewer 멤버가 데이터 손실 없이 member로 이관되기, so that 재편 후에도 기존 멤버십의 편집 권한이 유지된다.

#### Acceptance Criteria
1. When 역할 재편이 배포되면, the 시스템 shall 기존 editor 및 viewer 멤버십을 member로 이관하여 편집 권한을 유지시킨다.
2. When 역할 재편이 배포되면, the 시스템 shall 기존 owner 멤버십을 owner로 유지한다.
3. While 이관 완료 후, the 시스템 shall 워크스페이스마다 정확히 하나의 owner를 유지한다 (기존 단일 owner 불변식 유지).
4. The 시스템 shall 이관 후 저장되는 멤버 role 값으로 owner·member만 허용한다.
5. If 역할 재편을 롤백(downgrade)하면, then the 시스템 shall member를 editor로 되돌린다 (viewer는 복구되지 않으며, 이는 의도된 비대칭이다).

### Requirement 3: 문서 읽기 전역 개방
**Objective:** As a 활성 사용자, I want 소속 여부와 무관하게 모든 문서를 읽기, so that 워크스페이스 경계 없이 조직 내 문서를 열람한다.

#### Acceptance Criteria
1. When 활성 사용자가 문서 상세를 조회하면, the 문서 서비스 shall 워크스페이스 멤버십과 무관하게 문서를 반환한다.
2. When 활성 사용자가 워크스페이스의 문서 트리를 조회하면, the 문서 서비스 shall 멤버십과 무관하게 트리를 반환한다.
3. When 활성 사용자가 문서의 버전 이력을 조회하면, the 버전 서비스 shall 멤버십과 무관하게 이력을 반환한다.
4. When 활성 사용자가 첨부를 조회·다운로드하면, the 첨부 서비스 shall 멤버십과 무관하게 파일을 반환한다.
5. When 활성 사용자가 워크스페이스 상세를 조회하면, the 워크스페이스 서비스 shall 멤버십과 무관하게 이름·설정(is_shareable·보관일)을 반환하고, role 필드는 호출자 관점(비멤버면 null)으로 채운다.
6. If 요청자가 인증되지 않았거나 활성 계정이 아니면, then the 시스템 shall 읽기 요청을 거부한다 (기존 인증·활성 게이트 유지).
7. If 조회 대상 리소스(문서·워크스페이스·첨부)가 존재하지 않으면, then the 시스템 shall not-found로 응답한다.
8. When 비멤버 활성 사용자가 존재하는 문서·첨부·워크스페이스 상세를 읽으면, the 시스템 shall 권한 부족(403) 대신 성공(200)으로 응답한다 (읽기 경로의 열거-방지 403 제거).

### Requirement 4: 멤버 편집 권한
**Objective:** As a 워크스페이스 멤버, I want 멤버이면 편집 가능하기, so that owner가 아니어도 문서를 만들고 고칠 수 있다.

#### Acceptance Criteria
1. While 요청자가 대상 워크스페이스의 멤버(owner 또는 member)일 때, the 문서 서비스 shall 문서 생성·이름변경·이동·휴지통이동을 허용한다.
2. While 요청자가 멤버일 때, the 편집잠금·버전 서비스 shall 잠금 획득·저장·취소를 허용한다.
3. While 요청자가 멤버일 때, the 첨부 서비스 shall 첨부 업로드를 허용한다.
4. While 요청자가 멤버일 때, the 공유 서비스 shall 공유 링크 발급·토글을 허용한다.
5. While 요청자가 멤버일 때, the 휴지통 서비스 shall 휴지통 목록 조회·복원·완전삭제를 허용한다.
6. If 요청자가 대상 워크스페이스의 멤버가 아니면(admin 제외), then the 시스템 shall 편집·휴지통 동작을 거부한다.

### Requirement 5: owner 전용 관리 권한 유지
**Objective:** As a 워크스페이스 owner, I want 관리 작업을 owner로 한정하기, so that 설정·멤버 구성이 통제된다.

#### Acceptance Criteria
1. While 요청자가 owner(또는 admin)일 때, the 워크스페이스 서비스 shall 워크스페이스 설정 변경·삭제를 허용한다.
2. While 요청자가 owner(또는 admin)일 때, the 워크스페이스 서비스 shall 멤버 목록·assignable 사용자 조회 및 멤버 추가·role 변경·제거를 허용한다.
3. While 요청자가 owner(또는 admin)일 때, the 편집잠금 서비스 shall 강제 잠금 해제(force-unlock)를 허용한다.
4. If 요청자가 owner가 아니면(admin 제외), then the 시스템 shall 관리 작업을 거부한다.
5. The 멤버 목록·워크스페이스 응답 shall 각 멤버 role을 owner/member로 표현한다.

### Requirement 6: 프론트엔드 역할 표시·게이팅 정합
**Objective:** As a 사용자, I want UI가 owner/member만 표시·선택하기, so that 삭제된 viewer 흔적 없이 일관되게 동작한다.

#### Acceptance Criteria
1. The 프론트엔드 role 모델 shall 워크스페이스 role을 owner/member로만 표현한다 (백엔드 미러).
2. Where 역할 선택 UI가 노출될 때, the 멤버 관리 화면 shall owner·member 선택지만 제공한다.
3. Where 멤버 목록·현재 워크스페이스 표시가 노출될 때, the UI shall role을 owner/member로 표기한다.
4. The 프론트엔드 권한 판정 shall 편집성 UI 노출을 멤버 여부로 결정하고, admin은 항상 통과시킨다 (서버 강제를 대체하지 않는 UI 편의).
5. When 사용자가 재로그인·새로고침하면, the 프론트엔드 shall 서버가 제공한 owner/member role을 복원한다 (s24 메커니즘 유지, 값 집합만 변경).

### Requirement 7: 불변식·경계 재정의 및 회귀 정합
**Objective:** As a 시스템 운영자, I want 변경된 권한 경계가 기존 불변식·테스트와 정합하기, so that 재편 후 시스템이 일관되게 동작한다.

#### Acceptance Criteria
1. The 시스템 shall 문서 편집·워크스페이스 관리 권한을 워크스페이스 멤버십 단위로만 판정한다 (INV-1을 편집·관리에 한해 유지, 문서별 개별 권한 없음).
2. The 시스템 shall 문서·첨부·버전·워크스페이스 상세 읽기에 워크스페이스 멤버십 요구를 적용하지 않는다 (읽기에 한해 INV-1 완화).
3. The 공유 링크 경로 shall 미인증 외부 접근에 대해 기존 토큰·is_shareable 게이트를 그대로 유지한다 (전역 읽기 완화는 인증된 활성 사용자에만 적용).
4. The 휴지통 목록 조회 shall 전역 읽기 개방에서 제외되어 멤버(owner 또는 member) 이상만 접근한다.
5. When 역할·읽기 경계가 변경되면, the 회귀 테스트군(L1~L6 및 단위 권한 테스트) shall 새 2단계 모델·전역 읽기 경계를 반영하도록 갱신된다.
