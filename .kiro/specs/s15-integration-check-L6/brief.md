# Brief: s15-integration-check-L6

## Problem
계층 6(sharing)이 완성된 시점 = 전체 시스템 완성. 공유 링크 생명주기·무효화·재발급과 링크 경유
파일 접근이, 그 아래 **모든 계층**(계약·인증·계정·권한·문서 코어·잠금/버전·휴지통·첨부) 누적 결합과
성립하는지 전체 e2e로 최종 검증한다. 가장 넓은 누적 검증 범위다.

## Current State
s14-sharing 구현 완료 가정 = 전체 spec 구현 완료. L5 체크포인트(s13) 통과 상태.

## Desired Outcome (누적 = 전체: 계약 ⊕ auth ⊕ admin ⊕ workspace ⊕ document-core ⊕ lock-version ⊕ trash ⊕ attachment ⊕ sharing)
- **계약 정합**: share_link 스키마·공유 API·공개 접근 계약이 s01 단일 소스와 일치. 전체 API 표면이
  계약과 일치하는지 최종 확인.
- **cross-spec 시나리오(이번 계층 신규 경계 = 공유, + 전 계층 결합)**:
  - is_shareable 게이트(7.1·7.2) → editor+ 링크 발급(7.3) → 공개 읽기전용 접근, 문서+active 하위(7.5),
    새 하위 동적 포함(7.6).
  - 토글 off/on 동일 링크(7.7); 문서 trashed 즉시 무효(7.8, trash L4 결합); 복구 시 재발급(7.9);
    WS 게이트 off 즉시 무효·재 on 재발급(7.10); INV-8.
  - **링크 경유 첨부(L5↔L6)**: 활성 링크로 이미지 로딩·파일 다운로드(8.4); 게이트 off 또는 문서
    trashed 시 파일 접근 함께 차단(8.5).
  - **전 계층 회귀 재확인**: admin override(INV-3), 권한 경계(INV-1·2), bundle 불변식(INV-10~12),
    물리 삭제 없음(INV-4), 잠금 단일성(INV-9), 보관=복원 불가(INV-7) 등이 최종 결합에서도 성립.
  - 대표 e2e 흐름: admin이 사용자 생성 → owner가 WS·문서·하위문서 구성 → 편집 잠금·저장(버전) →
    이미지 붙여넣기 → 공유 링크 발급·외부 열람(첨부 포함) → 하위 문서 삭제(묶음·링크 무효) →
    복구(위치 규칙)·재발급 → 완전삭제(첨부 보관 이동).

## Approach
mock 없이 전체 실제 구현을 결합한 e2e. 검증 기준은 s01 단일 소스. feature 미구현. 가장 넓은 누적
집합을 대상으로 계약·경계 정합과 전 계층 불변식 회귀를 최종 확인.

## Scope
- **In**: 전체 계약 대조 + 공유 생명주기·링크 파일 접근·전 계층 불변식 회귀 e2e 테스트.
- **Out**: feature 구현, 범위 밖 항목(§6: 검색·rollback·CRDT 등).

## Boundary Candidates
- 공유 링크 무효화·재발급 e2e 스위트
- 링크 경유 첨부 접근·차단 스위트
- 전 계층 불변식 회귀 스위트(대표 e2e 흐름)

## Out of Boundary
- feature 구현 일체, §6 범위 밖 기능

## Upstream / Downstream
- **Upstream**: s01~s13, s14 (전체)
- **Downstream**: 없음. 통과 시 전체 시스템 GO.

## Existing Spec Touchpoints
- **Extends**: 없음(검증 전용)
- **Adjacent**: s14(주 검증 대상), 전 계층(누적 결합)

## Constraints
mock 금지. 기준은 s01 단일 소스. 누적 대상 = 전체 spec. 어떤 계층 수정 시에도 이 최종 체크포인트는
항상 재실행(재검증 트리거의 종단). 산출물 한국어.
