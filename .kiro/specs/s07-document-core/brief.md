# Brief: s07-document-core

## Problem
서비스의 핵심 도메인. 계층적 markdown 문서의 CRUD·이동·재정렬과, 3단계 상태(active/trashed/deleted)
전이를 지배하는 **묶음(bundle) 비흡수 엔진**이 필요하다. 이 엔진은 §5의 가장 까다로운 불변식
(INV-10·11·12)과 복구 위치 규칙(§4.2, 6.5)을 단일 구현으로 캡슐화해야 한다.

## Current State
s01의 document·document_version 스키마(status·parent_id·sort_order·lock 필드·trashed_at 등) 존재.
s05로 권한 경계 확보. 문서 CRUD·계층·이동·상태 전이 엔진 미구현.

## Desired Outcome
- editor+ 문서/하위문서 생성(REQ-4.1·4.2), viewer 읽기전용(4.3, INV-2).
- 현재 버전 markdown 렌더(4.4), 편집 화면 preview(4.5).
- 같은 WS 내 이동/재정렬(parent_id·sort_order, 4.6·4.7), 자기/후손 이동 거부(4.8, INV-5),
  WS 경계 불가(INV-6).
- **bundle 전이 엔진**:
  - active→trashed: 삭제 시점 active 하위만 하나의 묶음으로 포착, 공통 trashed_at 기록;
    이미 trashed 하위는 제외(6.2·6.2.1).
  - active 상태 하위 개별 삭제 → 독립 묶음(6.3). 부모 나중 삭제 시 비흡수(6.4), `child.trashed_at ≤
    parent.trashed_at`(INV-11).
  - 복구 위치 = 복구 시점 부모 상태(6.5): 부모 active→부모 밑(sort_order 원위치 복원 6.7),
    non-active→root append(6.5.2, 6.7.2). 자동 재중첩 없음(6.5.3).
  - 완전삭제 primitive(묶음 단위 원자적, INV-10).

## Approach
문서 구조(엔티티·계층·이동·CRUD·렌더/preview)와 상태/bundle 전이 엔진을 document-core 서비스 레이어에
단일 구현으로 캡슐화(tech.md·structure.md 지침). trash·sharing 등 상위 spec은 이 엔진을 재사용.
엔진은 property/edge-case 테스트로 불변식 검증.

## Scope
- **In**: 문서 CRUD, 계층/parent_id, 이동·재정렬(순환·동일WS), 렌더·preview, status 필드,
  bundle 전이 엔진(cascade·비흡수·복구 위치·완전삭제 primitive), lock 필드 정의(사용은 s09).
- **Out**: 휴지통 UX/API·보관 타이머(s10), 편집 잠금 동작·버전 저장(s09), 공유(s14), 첨부(s12).

## Boundary Candidates
- 문서 구조(엔티티·계층·이동·CRUD·렌더/preview)
- status/bundle 전이 엔진(불변식 캡슐화)

## Out of Boundary
- 휴지통 목록/복구/완전삭제 "API·UX"와 자동 보관 타이머(s10) — 엔진 primitive만 여기 소유
- 편집 잠금 흐름·버전 스냅샷 생성(s09)

## Upstream / Downstream
- **Upstream**: s01(스키마), s06(게이트 통과), 권한 경계(s05)
- **Downstream**: s09-lock-version, s10-trash, s12-attachment, s14-sharing이 엔진·문서 구조에 의존

## Existing Spec Touchpoints
- **Extends**: 없음(신규 코어)
- **Adjacent**: s05-workspace(권한 게이팅), s10-trash(엔진 소비자)

## Constraints
INV-5·6·10·11·12, §4.2 비흡수 모델, 물리 삭제 없음(INV-4). sort_order DECIMAL 권장(중간 삽입). 한국어.
