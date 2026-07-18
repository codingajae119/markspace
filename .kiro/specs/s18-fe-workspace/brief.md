# Brief: s18-fe-workspace

## Problem
사용자가 소속 워크스페이스를 전환하고, 멤버·권한을 관리하며(owner), WS 설정(is_shareable·retention)을
편집하고, admin은 사용자 계정과 WS 소유권을 관리할 수 있어야 한다. 역할별 UI 노출은 공통 권한 게이팅
유틸(s16)로 결정한다.

## Current State
s16 공통 레이어 확보 가정(세션·권한 게이팅·API 클라이언트). 소비 API:
`GET/POST /workspaces`, `GET/PATCH/DELETE /workspaces/{id}`, `POST/PATCH/DELETE /workspaces/{id}/members[/{uid}]`,
`POST /admin/workspaces/{id}/owner`, admin 계정: `POST/GET /admin/users`, `PATCH /admin/users/{id}`,
`POST /admin/users/{id}/password`. 백엔드 s05-workspace·s03-admin-account 완료.

## Desired Outcome
- WS 스위처: 소속 WS 목록·현재 WS 선택(전역 컨텍스트, 후속 문서/편집 화면이 소비할 현재 WS 경계).
- 멤버/권한 관리(owner): 멤버 추가/역할 변경(owner/editor/viewer)/제거, INV-1·2 권한 경계 UI 반영.
- WS 설정(owner): `is_shareable` 토글, retention(보관 기간) 설정 편집.
- admin 콘솔: 사용자 CRUD·비활동·삭제·재활성화·비밀번호 재설정, WS 소유권 변경(admin override INV-3).
- 역할별 노출: owner 전용 설정·멤버관리, admin 전용 콘솔은 공통 권한 게이팅 유틸로 결정(컴포넌트 역할 비교 금지).

## Approach
현재 WS를 전역 컨텍스트로 노출해 후속 문서/편집/공유 화면이 WS 경계를 일관되게 소비하도록 한다.
권한 게이팅은 s16 유틸 경유. admin 콘솔은 별도 화면군으로 admin 세션에서만 라우팅.

## Scope
- **In**: WS 스위처·현재 WS 컨텍스트, 멤버/권한 관리 화면(owner), WS 설정(is_shareable·retention),
  admin 사용자 콘솔(CRUD·flag·재설정), WS 소유권 변경(admin).
- **Out**: 문서 트리·CRUD(s19), 공유 링크 발급 UI(s22 — 여기선 is_shareable 게이트 플래그만 소유),
  세션/로그인(s17), 권한 게이팅 유틸 자체(s16).

## Boundary Candidates
- WS 스위처·현재 WS 전역 컨텍스트
- 멤버/권한 관리(owner)
- WS 설정(is_shareable·retention)
- admin 콘솔(계정 생명주기·소유권 변경)

## Out of Boundary
- 권한 게이팅 유틸·세션(s16)
- 문서 계층·뷰어(s19)
- 공유 링크 발급/관리(s22)

## Upstream / Downstream
- **Upstream**: s16-fe-foundation(권한 게이팅·세션·API 클라이언트), s01(workspace·member·권한 계약)
- **Downstream**: s19-fe-document·s20~s22(현재 WS 컨텍스트·is_shareable 게이트를 소비)

## Existing Spec Touchpoints
- **Extends**: 없음(신규)
- **Adjacent**: s17-fe-auth(같은 user 도메인의 로그인 측), s22-fe-sharing(is_shareable 게이트 소비자)

## Constraints
INV-1·2·3(WS 단위 권한·admin override) UI 반영은 s16 게이팅 유틸 경유. is_shareable 플래그는 이 spec 소유.
검증 기준 s01 계약. 산출물 한국어.
