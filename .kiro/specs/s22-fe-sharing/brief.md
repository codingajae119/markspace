# Brief: s22-fe-sharing

## Problem
editor+ 사용자가 문서 단위 읽기 전용 공유 링크를 발급/토글/관리하고, 링크를 받은 게스트는 인증 없이
`/share/:token` 경로에서 문서(+active 하위·첨부 이미지)를 읽기 전용으로 볼 수 있어야 한다. WS
`is_shareable` 게이트와 문서 상태에 따라 링크·파일 접근이 함께 차단된다.

## Current State
s16 공통 레이어(게스트 라우트 `/share/:token` 등록·viewer mode 래퍼)·s18 is_shareable 게이트·s19
뷰어·s21 첨부 렌더 확보 가정. 소비 API:
`POST /documents/{id}/share`(ShareLinkRead 발급), `PATCH /documents/{id}/share`(토글),
`GET /public/{token}`(PublicDocumentRead — 인증 우회 공개 읽기),
`GET /public/{token}/attachments/...`(링크 경유 첨부 서빙). 백엔드 s14-sharing 완료.

## Desired Outcome
- 공유 링크 관리(editor+): 공유 가능 WS 문서에서 링크 발급(`POST /share`)·토글 on/off(`PATCH /share`)·
  링크 복사. `is_shareable=false`면 발급/활성 불가(게이트 UI 반영, 게이트 플래그는 s18 소유·여기선 소비).
- 무효화/재발급 안내: 문서 trashed·WS 게이트 off 시 링크 무효 상태 표면화, 재발급 필요 안내(INV-8·재발급 통일 원칙).
- 게스트 라우트 뷰: `/share/:token` — 인증 가드 없는 읽기 전용 뷰어(`GET /public/{token}`), 문서 + active
  하위 동적 표시, s16 viewer mode 래퍼 재사용(편집 경로와 이원화 금지).
- 링크 경유 첨부: 공유 뷰 내 이미지 로딩·첨부 다운로드(`/public/{token}/attachments/...`), 게이트 off/문서
  trashed 시 파일 접근 함께 차단 상태 반영.

## Approach
관리 측(발급/토글)은 인증 세션·권한 게이팅(s16) 경유, 게스트 측은 s16 게스트 라우트에 인증 없는 공개
뷰어를 얹는다. 읽기 렌더는 s19/s16 viewer mode 재사용. 무효화는 백엔드 status/게이트 관찰 결과를
표면화(재발급 원칙 UI 반영).

## Scope
- **In**: 공유 링크 발급/토글/복사·무효화 안내(editor+), 게스트 `/share/:token` 읽기전용 뷰어,
  링크 경유 첨부 이미지/다운로드·차단 반영.
- **Out**: is_shareable 게이트 플래그 관리(s18 소유·여기선 소비), 문서 상태 전이(s19·백엔드),
  인증 문서 뷰어 자체(s19), 게스트 라우트 프레임 등록(s16 소유·여기선 뷰 구현).

## Boundary Candidates
- 공유 링크 관리(발급/토글/복사/무효화 안내)
- 게스트 읽기전용 뷰(`/share/:token`)
- 링크 경유 첨부 접근·차단 반영

## Out of Boundary
- is_shareable 게이트 플래그 소유(s18)
- 문서 상태 전이·인증 뷰어(s19)
- 게스트 라우트 등록 프레임(s16)

## Upstream / Downstream
- **Upstream**: s16-fe-foundation(게스트 라우트·viewer 래퍼·API 클라이언트·권한 게이팅),
  s18-fe-workspace(is_shareable 게이트 소비), s19-fe-document(뷰어 mode 재사용),
  s01(share_link·public 계약)
- **Downstream**: 없음(최상위 프론트 계층 — 전체 e2e 종단)

## Existing Spec Touchpoints
- **Extends**: 없음(신규 최상위)
- **Adjacent (동일 wave, 병렬 생성 — cross-spec 리뷰에서 정합)**: s21-fe-attachment(링크 경유 첨부 렌더 —
  공개 서빙 경로 `/public/{token}/attachments/...`는 s01 계약 경유로 정합)
- **Adjacent**: s18-fe-workspace(게이트 소유), s19-fe-document(뷰어 재사용)

## Constraints
INV-8·재발급 통일 원칙 UI 반영. 게스트 뷰=인증 우회 읽기 전용, 게이트/status 차단 반영. 읽기 렌더
이원화 금지. 검증 기준 s01 계약. 산출물 한국어.
