# Brief: s20-fe-editor

## Problem
editor+ 사용자가 문서 뷰(s19)에서 편집 모드로 진입해 Toast UI Editor로 편집하고, 편집 잠금을 획득/해제하며,
문서 이탈 시 1회 자동저장(버전 스냅샷 생성)하고, 과거 버전을 열람할 수 있어야 한다. lock은 자동
타임아웃이 없으므로 강제 해제 UI를 제한된 대상에게만 제공한다.

## Current State
s16 공통 레이어(Toast UI 래퍼·권한 게이팅)·s19 문서 뷰 확보 가정. 소비 API:
`POST /documents/{id}/lock`(DocumentLockRead), `POST /documents/{id}/save`(DocumentVersionRead),
`POST /documents/{id}/cancel`(204), `POST /documents/{id}/force-unlock`(204),
`GET /documents/{id}/versions`(Page[DocumentVersionRead]). 백엔드 s09-lock-version 완료.
저장=버전 스냅샷 생성 계약, rollback 없음, lock 자동 타임아웃 없음.

## Desired Outcome
- 편집 진입: 편집 모드 진입 시 lock 획득(`/lock`), Toast UI 편집(WYSIWYG 기본 + markdown 토글, s16 래퍼).
- lock UX: 다른 사용자가 보유한 잠금·자신의 잠금 상태 표시. 잠금 실패(타인 보유) 시 안내.
- 자동저장: **문서 이탈 시 1회**(라우트 전환·언마운트)에 `/save` 호출(주기 타이머·debounce 금지 —
  버전 폭증 회피). 편집 취소는 `/cancel`(저장 없이 잠금 해제).
- 강제 해제: `/force-unlock` UI 제공하되 노출 대상 = lock 보유 editor 본인·WS owner·admin 한정
  (공통 권한 게이팅 유틸 경유, 컴포넌트 역할 비교 금지).
- 버전 뷰어: `/versions` 목록·과거 버전 스냅샷 열람(읽기 전용, rollback 없음 — 복원 액션 미제공).

## Approach
s19 문서 뷰 위에 편집 레이어를 얹는다. 편집 진입=lock 획득, 이탈=자동저장+해제의 생명주기를 라우트
전환/언마운트에 바인딩. Toast UI 편집/읽기 렌더는 s16 단일 래퍼 재사용. 강제 해제 노출은 s16 게이팅 유틸.

## Scope
- **In**: 편집 모드 진입/이탈 생명주기, lock 획득/해제/취소 UX, 이탈 시 1회 자동저장, 강제 해제 UI(제한 노출),
  버전 목록·열람 뷰어.
- **Out**: 문서 뷰어·트리·CRUD(s19), 첨부 붙여넣기/업로드(s21 — 에디터 표면에 얹힘), 공유(s22),
  Toast UI 래퍼·권한 유틸 자체(s16).

## Boundary Candidates
- 편집 진입/이탈 생명주기(lock 바인딩)
- lock UX(상태 표시·획득/취소)
- 이탈 시 1회 자동저장
- 강제 해제 UI(제한 노출)
- 버전 뷰어

## Out of Boundary
- 문서 뷰/트리/CRUD(s19)
- 첨부 업로드(s21)
- 권한 게이팅·Toast UI 래퍼(s16)

## Upstream / Downstream
- **Upstream**: s16-fe-foundation(Toast UI 래퍼·권한 게이팅), s19-fe-document(문서 뷰·편집 진입점),
  s01(lock·version 계약)
- **Downstream**: s21-fe-attachment(에디터 편집 표면에 붙여넣기/드롭 업로드를 얹음)

## Existing Spec Touchpoints
- **Extends**: 없음(신규)
- **Adjacent**: s19-fe-document(같은 문서 화면의 읽기 측), s21-fe-attachment(같은 에디터 표면)

## Constraints
자동저장=이탈 시 1회(버전 폭증 회피). lock 자동 타임아웃 없음 → 강제 해제 제한 노출. rollback 미제공.
읽기/편집 렌더 이원화 금지. 검증 기준 s01 계약. 산출물 한국어.
