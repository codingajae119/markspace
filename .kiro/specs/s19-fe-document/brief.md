# Brief: s19-fe-document

## Problem
현재 워크스페이스 안에서 문서를 계층 트리로 탐색하고, breadcrumb으로 위치를 파악하며, 문서를
생성/이름변경/삭제하고, 드래그앤드롭으로 이동하며, 읽기 전용으로 볼 수 있어야 한다. 편집(잠금/저장)은
s20이 얹으므로, 이 spec은 네비게이션·CRUD·이동·뷰어까지만 소유한다.

## Current State
s16 공통 레이어·s18 현재 WS 컨텍스트 확보 가정. 소비 API:
`POST /documents`, `GET /documents`(트리·목록), `GET /documents/{id}`(DocumentRead),
`PATCH /documents/{id}`, `POST /documents/{id}/move`(이동/재정렬), `DELETE /documents/{id}`(휴지통 이동).
휴지통: `GET /workspaces/{id}/trash`(TrashBundleRead), 복구/완전삭제(trash router POST/DELETE).
백엔드 s07-document-core·s10-trash 완료. status·bundle 전이 엔진은 백엔드 소유(관찰만).

## Desired Outcome
- 트리 네비게이션: WS 문서 계층 표시·펼침/접힘·선택.
- breadcrumb: 현재 문서의 조상 경로 표시·이동.
- 문서 CRUD: 생성(부모 지정)·이름변경(PATCH)·삭제(DELETE → 휴지통, 묶음 단위 원자성 반영).
- 이동(DnD): 드래그앤드롭으로 부모 변경·재정렬(`/move`), 순환·동일 WS 제약을 백엔드 에러로 표면화.
- 뷰어: viewer 권한·읽기 시 Toast UI viewer mode로 문서 렌더(편집 경로와 이원화 금지, s16 래퍼 재사용).
- 휴지통: 목록(묶음별)·복구·완전삭제 화면, editor+ WS 전체 접근(권한 게이팅 s16 경유).

## Approach
현재 WS 컨텍스트(s18) 안에서 문서 계층을 소비. 렌더는 s16 Toast UI viewer 래퍼 재사용. 이동·삭제의
묶음/순환 규칙은 백엔드 엔진이 판정하므로 UI는 낙관적 반영 + 에러 표면화. 편집 진입 버튼은 노출하되
잠금/저장 로직은 s20에 위임.

## Scope
- **In**: 문서 트리·breadcrumb·CRUD·이동(DnD)·읽기 전용 뷰어, 휴지통 목록/복구/완전삭제 화면.
- **Out**: 편집·잠금·자동저장·버전 뷰어(s20), 첨부 업로드/렌더(s21), 공유 링크(s22), WS 컨텍스트·권한 유틸(s16·s18).

## Boundary Candidates
- 문서 트리 네비게이션 + breadcrumb
- 문서 CRUD
- 이동(DnD)/재정렬
- 읽기 전용 뷰어
- 휴지통 화면(목록/복구/완전삭제)

## Out of Boundary
- 편집/잠금/버전(s20)
- 첨부(s21)
- 공유(s22)
- status·bundle 전이 판정(백엔드 엔진)

## Upstream / Downstream
- **Upstream**: s16-fe-foundation(뷰어 래퍼·권한·라우팅), s01(document·trash 계약, 문서 엔드포인트는 WS-scoped)
- **Downstream**: s20-fe-editor(문서 뷰 위에서 편집 진입), s21·s22(문서 컨텍스트 소비)

## Existing Spec Touchpoints
- **Extends**: 없음(신규)
- **Adjacent (동일 wave, 병렬 생성 — cross-spec 리뷰에서 정합)**: s18-fe-workspace(현재 WS 컨텍스트를
  소비 — 컨텍스트 소비 규약은 s16 세션/컨텍스트 레이어 경유로 정합), s20-fe-editor(같은 문서 화면의 편집 측),
  s22-fe-sharing(같은 뷰어 mode 재사용)

## Constraints
읽기/편집 렌더 경로 이원화 금지(s16 viewer mode 재사용). 묶음 원자성·순환 제약은 백엔드 판정 표면화.
검증 기준 s01 계약. 산출물 한국어.
