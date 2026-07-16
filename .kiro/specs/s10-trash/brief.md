# Brief: s10-trash

## Problem
문서 3단계 생명주기의 휴지통 단계 UX/API가 필요하다: 묶음 목록 열람, 복구, 즉시 완전삭제, 그리고
묶음별 독립 보관 타이머에 따른 자동 영구삭제. editor+는 워크스페이스 휴지통 전체에 접근한다.

## Current State
s07-document-core의 bundle 전이 엔진(cascade·비흡수·복구 위치·완전삭제 primitive)과 trashed_at·
retention 설정(s05) 존재. 휴지통 목록/복구/완전삭제 "API·UX"와 자동 타이머 미구현.

## Desired Outcome
- editor+가 WS 휴지통 전체(본인 삭제분 외 포함) 열람·복구·완전삭제, viewer 접근 불가(REQ-6.11, INV-2).
- 묶음 단위 복구 → 엔진의 복구 위치 규칙(6.5) 적용(부모 밑/root).
- 완전삭제(6.9) → 해당 묶음만 즉시 deleted, 다른 독립 묶음 무영향.
- 완전삭제 확인 절차(6.10).
- 보관일(기본 30, WS 설정) 경과 시 묶음별 독립 타이머로 자동 deleted(6.8, INV-12).

## Approach
s07 bundle 엔진을 재사용하는 얇은 API/UX 레이어 + 보관 만료 배치(스케줄러). 타이머는 각 묶음
trashed_at 기준 독립 산정. 잠금과 삭제는 독립(§4.3).

## Scope
- **In**: 휴지통 목록(묶음 뷰), 복구 API(엔진 호출), 완전삭제 API·확인, 보관 만료 자동 영구삭제 배치,
  editor+ WS 전체 접근 권한.
- **Out**: bundle 전이 로직 자체(s07 엔진), 완전삭제 시 첨부 보관 이동(8.6은 s12가 소유),
  링크 무효화(s14).

## Boundary Candidates
- 휴지통 조회/복구/완전삭제 API·UX
- 보관 만료 자동 영구삭제 스케줄러

## Out of Boundary
- 삭제된 문서 첨부의 보관 폴더 이동(8.6) → s12-attachment
- 삭제 시 공유 링크 무효화(7.8) → s14-sharing

## Upstream / Downstream
- **Upstream**: s07(엔진), s05(retention 설정·권한), s08(게이트 통과)
- **Downstream**: s12-attachment(완전삭제 이벤트에 반응), s14-sharing(문서 status 변화 관찰), s11 체크포인트

## Existing Spec Touchpoints
- **Extends**: 없음(신규). s07 bundle 엔진을 소비.
- **Adjacent**: s09-lock-version(같은 L4, 독립)

## Constraints
INV-7(deleted 복원 경로 없음), INV-10·12(묶음 원자성·독립 타이머), viewer 휴지통 불가(INV-2). 한국어.
