# Brief: s05-workspace

## Problem
문서 협업의 권한 단위인 워크스페이스가 필요하다. 권한은 워크스페이스 레벨로만 존재하며(INV-1),
owner/editor/viewer 3종과 멤버십, 공유 게이트(is_shareable), 휴지통 보관일 설정, admin 소유권 변경이
이 경계에 모인다.

## Current State
s01의 workspace·workspace_member 스키마와 권한 resolver 인터페이스 존재. s02/s03로 사용자·인증 확보.
워크스페이스 CRUD·멤버십·권한 판정 동작 미구현.

## Desired Outcome
- owner/admin이 워크스페이스 생성·삭제(REQ-3.1, 3.2).
- owner가 전체 사용자 목록에서 멤버 추가(지정 role), 제거, role 변경(3.3~3.5).
- 복수 owner 허용(3.6). owner ⊇ editor 권한.
- 권한 판정: viewer(읽기)/editor(문서 CRUD·하위생성·휴지통)/owner(멤버·공유·WS 생성삭제) — INV-1·2.
- admin은 멤버 여부와 무관하게 접근(INV-3), admin이 소유권 변경(2.7).
- 유일 owner 비활동/삭제되어도 editor·viewer 활동 무영향(3.7).
- owner/admin이 `is_shareable`(7.2)·`trash_retention_days` 설정.

## Approach
s01 권한 resolver를 실제 role 조회로 채우고, 워크스페이스/멤버십 라우터·서비스 구현. 권한 검사는
공통 레이어에 두고 각 라우터가 재사용(structure.md 정렬). admin bypass는 resolver에서 일괄 처리.

## Scope
- **In**: 워크스페이스 CRUD, 멤버십 CRUD, role 관리, 권한 판정 로직, is_shareable·retention 설정,
  admin 소유권 변경.
- **Out**: 문서/버전/휴지통/공유/첨부(s07 이상). 공유 링크 발급 자체(s14) — 여기선 게이트 플래그만.

## Boundary Candidates
- 워크스페이스 CRUD
- 멤버십·role 관리
- 워크스페이스 단위 권한 판정(공통 레이어)
- WS 설정(is_shareable, retention_days)

## Out of Boundary
- 문서 도메인 일체(s07+)
- 공유 링크 발급/무효화(s14)
- admin의 계정 생명주기(s03)

## Upstream / Downstream
- **Upstream**: s01(스키마·resolver), s04(게이트 통과)
- **Downstream**: s07-document-core 이하 모든 문서 도메인이 이 권한 경계에 의존, s06 체크포인트

## Existing Spec Touchpoints
- **Extends**: 없음(신규)
- **Adjacent**: s03-admin-account(소유권 변경 주체 admin)

## Constraints
INV-1(WS 단위 권한)·INV-2(viewer 읽기전용)·INV-3(admin 무제약)·INV-6(WS 경계). 산출물 한국어.
