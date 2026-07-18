# Roadmap — Notion-lite

## Overview

Notion-lite(소규모 폐쇄형 협업 문서 서비스)를 **contract-first + 의존성 계층(layer) 분해**로 구축한다.
전체 프로젝트가 공유하는 계약(데이터 스키마 · API · 공용 인터페이스)을 `s01-contract-foundation`에서
단일 소스로 먼저 확정한 뒤, feature spec을 의존성 계층 순서로 얹는다. 각 계층 경계마다 **누적 통합 검증
체크포인트**(`integration-check-L{n}`)를 삽입하여, 그 시점까지 완성된 upstream 전체가 공유 계약과
정합하는지 mock 없이 실제 구현으로 검증한다. 뒤쪽 체크포인트일수록 검증 범위가 넓어지는 누적 구조다.

목표: 각 spec을 **단독으로 기능·코드를 검증할 수 있는 작은 크기**로 유지하고, 계층 경계를 넘는
불변식(§5 INV-1~12) 회귀를 체크포인트에서 조기에 포착한다.

## Approach Decision

- **Chosen**: Contract-first, layered decomposition with cumulative per-layer integration checkpoints.
  공유 계약(`s01`)을 단일 검증 기준으로 삼고, feature spec을 L1~L6 계층으로 정렬, 각 계층 경계에
  누적 통합 체크포인트를 배치.
- **Why**:
  - `docs/projects.md` §5의 12개 불변식이 여러 spec에 걸쳐 있어(예: INV-3 admin override는 전 계층,
    INV-10~12 bundle 규칙은 document-core+trash+sharing), 개별 design N개를 서로 대조하는 대신
    **단일 계약**에 대조하는 편이 드리프트를 막는다.
  - 의존성 DAG가 비대칭이라(attachment가 lock-version·trash 위에, sharing이 attachment 위에)
    "맨 끝 통합 검증 1회"로는 계층 회귀를 조기에 못 잡는다. 누적 체크포인트가 각 경계에서 아래층
    결합까지 재검증한다.
- **Rejected alternatives**:
  - *큰 단일 spec*: 20+ 태스크로 검증 단위가 비대해지고 계약 드리프트 추적 불가. 기각.
  - *맨 끝 통합 검증 1회*: 사용자 지시로 명시 금지. 계층별 회귀 조기 포착 불가. 기각.
  - *더 잘게(18개) / 더 크게(11개) 분해*: workspace·document-core를 각각 단일 spec으로 두는 15개
    입도가 검증 단위 크기와 계층/체크포인트 오버헤드의 균형점으로 선택됨.

## Scope

- **In**: 인증·계정, admin 계정관리, 워크스페이스·권한, 문서 코어(계층·이동·상태/bundle 엔진),
  편집잠금·버전, 휴지통, 첨부·이미지, 읽기전용 공유. 각 계층 경계의 통합 검증.
- **Out** (`docs/projects.md` §6): 문서 검색, 과거버전 rollback, lock 자동 타임아웃, 실시간 동시편집(CRDT),
  self sign-up/SSO/OAuth, 보관 폴더 자동 정리, 다중 admin, 자식→부모 자동 재중첩.

## Constraints

- Backend: FastAPI(Python 3.13+) + MySQL 8, 실행·의존성은 **uv** 기준(`uv run`, `uv add`).
- Frontend: React + Vite + Tailwind CSS 4 SPA.
- 설정 단일화: 비밀 아닌 값은 단일 `config.yml`, secret은 `.env`, 접근은 pydantic-settings 공용
  `Settings`로만(모듈별 설정 파일·`os.environ` 직접 접근 금지).
- 물리 삭제 없음(INV-4): user/document/attachment는 flag·status 전환 또는 보관 폴더 이동만.
- `.kiro/specs/` 산출물은 **한국어**로 작성.

## Boundary Strategy

- **Why this split**:
  - 공유 계약(`s01`)을 먼저 고정해 모든 feature와 체크포인트가 동일 단일 소스를 참조.
  - 권한 검사(INV-1·3)와 bundle 엔진(INV-10~12)은 공용/코어 레이어에 단일 구현으로 캡슐화하고
    나머지 spec이 재사용 → 중복·드리프트 방지(steering `structure.md` 정렬).
  - 의존성 방향이 항상 아래층을 향하도록 계층을 정렬(같은 계층 spec은 서로 독립, 동일 upstream 의존).
- **Shared seams to watch** (체크포인트 집중 대상):
  - 세션/권한 resolver ↔ 각 라우터 (INV-1·2·3)
  - document-core status/bundle 엔진 ↔ trash·sharing (INV-10~12, 6.5 복구 위치 규칙)
  - lock/version ↔ attachment 참조 소멸 아카이브(8.7)
  - trash 완전삭제 ↔ attachment 보관 이동(8.6)
  - 문서 status·WS `is_shareable` ↔ 공유 링크 무효화·재발급(7.8~7.10, INV-8)

## 구현 순서 (Implementation Order)

계층 → 체크포인트 → 다음 계층 순으로 진행한다. `s{NN}-` prefix가 곧 진행 순서다.

```
[L1] s02-auth, s03-admin-account
   → s04-integration-check-L1        (계약 ⊕ auth ⊕ admin-account)
[L2] s05-workspace
   → s06-integration-check-L2        (⊕ workspace)
[L3] s07-document-core
   → s08-integration-check-L3        (⊕ document-core)
[L4] s09-lock-version, s10-trash
   → s11-integration-check-L4        (⊕ lock-version ⊕ trash)
[L5] s12-attachment
   → s13-integration-check-L5        (⊕ attachment)
[L6] s14-sharing
   → s15-integration-check-L6        (⊕ sharing = 전체 시스템 e2e)
```

`s01-contract-foundation`은 L0(공유 계약 단일 소스 + 공용 런타임 인프라)로, 모든 spec의 upstream이며
모든 체크포인트의 **검증 기준**이다. 계약 단독은 결합 대상이 없으므로 별도 체크포인트를 두지 않되,
spec 자체 검증(마이그레이션 적용·앱 부팅·Settings 로드·권한 resolver 존재)은 수행한다.

## 게이트 (Gates)

- **G-1**: `integration-check-L{n}`이 **통과하기 전에는 계층 {n+1}의 impl을 금지**한다.
  각 체크포인트는 바로 위 계층 impl 착수의 선행 조건이다.
- 체크포인트는 feature 로직을 구현하지 않는다. 오직 해당 시점까지의 upstream **누적 집합**에 대한
  계약·경계 정합 검증과 그 테스트(integration/e2e, mock 없음)만 범위로 삼는다.
- 검증 기준은 항상 `s01-contract-foundation`의 단일 소스(인터페이스/데이터 스키마/API 계약)이며,
  개별 spec의 design이 아니라 이 단일 소스에 대조한다.

## 재검증 트리거 (Re-validation Triggers)

- 어떤 계층 {k}의 upstream spec이 수정되면, **그 계층 이후의 모든 체크포인트(L{k} 및 그 이상)**를
  누적 집합 기준으로 다시 실행해야 한다.
  - 예: `s05-workspace`(L2) 수정 → L2·L3·L4·L5·L6 체크포인트 전부 재실행.
  - 예: `s01-contract-foundation`(계약) 수정 → **모든** 체크포인트 재실행.
- 재실행 시에도 mock 없이 실제 구현을 결합한 상태로 검증한다.

## Specs (dependency order)

- [x] s01-contract-foundation -- 공유 계약 단일 소스(DB 스키마·API 계약·공용 인터페이스) + 공용 런타임 인프라(Settings·에러모델·세션/권한 resolver). Dependencies: none
- [x] s02-auth -- id/password 로그인·로그아웃·세션, 본인 비밀번호 변경. Dependencies: s01-contract-foundation
- [x] s03-admin-account -- admin의 사용자 CRUD·비활동·삭제·재활성화·비밀번호 재설정(계정 생명주기). Dependencies: s01-contract-foundation
- [x] s04-integration-check-L1 -- 누적 검증: 계약 ⊕ auth ⊕ admin-account 경계 정합(계정 생명주기↔로그인). Dependencies: s01-contract-foundation, s02-auth, s03-admin-account
- [x] s05-workspace -- 워크스페이스 CRUD·멤버십·권한(owner/editor/viewer, INV-1·2·3)·is_shareable·retention 설정·admin 소유권 변경. Dependencies: s04-integration-check-L1
- [x] s06-integration-check-L2 -- 누적 검증: 계약 ⊕ auth ⊕ admin ⊕ workspace(권한 경계·admin override·소유권). Dependencies: s05-workspace
- [x] s07-document-core -- 문서 엔티티·계층·CRUD·이동/재정렬(순환·동일WS)·렌더/preview·status+bundle 전이 엔진(INV-5·6·10·11·12). Dependencies: s06-integration-check-L2
- [x] s08-integration-check-L3 -- 누적 검증: ⊕ document-core(권한 게이팅·bundle 엔진 정합). Dependencies: s07-document-core
- [x] s09-lock-version -- 편집 잠금(시작/저장/취소/강제해제, 타임아웃 없음)·저장 시 버전 생성(무한보관·rollback 없음). Dependencies: s08-integration-check-L3
- [x] s10-trash -- 휴지통 목록/복구/완전삭제 API·묶음별 보관 타이머 자동 영구삭제·editor+ WS 전체 접근. Dependencies: s08-integration-check-L3
- [x] s11-integration-check-L4 -- 누적 검증: ⊕ lock-version ⊕ trash(잠금↔삭제 독립·묶음 타이머·엔진 결합). Dependencies: s09-lock-version, s10-trash
- [x] s12-attachment -- 붙여넣기 이미지·파일 첨부·WS 격리·완전삭제 시 보관 이동(8.6)·저장 참조 소멸 아카이브(8.7). Dependencies: s11-integration-check-L4
- [x] s13-integration-check-L5 -- 누적 검증: ⊕ attachment(보관 이동↔완전삭제·참조 소멸↔버전 저장). Dependencies: s12-attachment
- [x] s14-sharing -- 문서 단위 읽기전용 공유 링크·is_shareable 게이트·동적 하위·재발급 원칙·링크 경유 파일 접근. Dependencies: s13-integration-check-L5
- [x] s15-integration-check-L6 -- 누적 검증(전체 e2e): ⊕ sharing(무효화·재발급·링크 파일 접근, INV-8 포함 전 계층 결합). Dependencies: s14-sharing

### Frontend (React + Vite + Tailwind SPA, backend 계층 미러링)

프론트엔드는 백엔드 feature 계층을 미러링해 분해한다. `s16-fe-foundation`이 프론트 공통 레이어
(라우팅·API 클라이언트·전역 401·권한 게이팅·Toast UI 래퍼)를 단일 소유하는 L0 upstream이며, 나머지
프론트 spec은 이를 소비한다. 검증 기준은 백엔드와 동일하게 `s01-contract-foundation`의 계약 단일 소스
(API 카탈로그·에러 모델·권한 resolver·INV-1~12)다. UI 빌드 순서 기준 계층:
`s16 → {s17,s18,s19} → {s20,s21,s22}`.

**교차관심 단일 소유 정정(cross-spec 리뷰 반영)**: 세션 컨텍스트와 동일하게 **현재 워크스페이스 앰비언트
컨텍스트**(현재 WS id·현재 사용자의 WS 역할·is_shareable 등 WorkspaceRead 스냅샷을 읽는 Provider·
`useCurrentWorkspace` 훅·컨텍스트 타입)와 **feature 라우트/Provider 등록 메커니즘**, **공용 `Page<T>` 타입**,
**읽기 전용 prose 스타일**은 `s16`가 단일 소유한다. `s18`는 WS 관리 화면(스위처·멤버·설정·admin 콘솔)만
소유하고 s16 컨텍스트를 채우고/변경한다(로그인 화면=s17, 세션 컨텍스트=s16의 분업과 동형). 이 정정으로
s19/s20/s22의 형제(같은 wave) 의존이 제거되어 `s16` 단일 upstream으로 수렴한다.

- [x] s16-fe-foundation -- 프론트 공통 레이어: FE 스캐폴드·설정 단일화·라우팅 셸(보호/게스트)·공용 API 클라이언트·전역 401 인터셉터·세션 컨텍스트·현재 WS 앰비언트 컨텍스트·라우트/Provider 등록 메커니즘·권한 게이팅 유틸(RequireRole/RequireAdmin)·공용 Page<T>·ReadOnlyProse·Toast UI Editor 래퍼(paste/drop·insert·custom renderer 포함). Dependencies: s01-contract-foundation
- [x] s17-fe-auth -- 로그인·로그아웃·본인 비밀번호 변경 화면·세션 진입/복귀(returnTo). Dependencies: s16-fe-foundation
- [x] s18-fe-workspace -- WS 스위처·멤버/권한 관리(owner)·설정(is_shareable·retention)·admin 콘솔(계정 생명주기·소유권 변경)·role 멤버십 seam(s16 컨텍스트 주입). Dependencies: s16-fe-foundation
- [x] s19-fe-document -- 문서 트리 네비·breadcrumb·CRUD·이동(DnD)·읽기전용 뷰어·휴지통 화면(목록/복구/완전삭제). Dependencies: s16-fe-foundation
- [x] s20-fe-editor -- 편집 진입/이탈 생명주기·lock UX·강제해제(제한 노출)·이탈 시 1회 자동저장·버전 뷰어. Dependencies: s16-fe-foundation, s19-fe-document
- [x] s21-fe-attachment -- 드롭/붙여넣기 업로드·진행 플레이스홀더·이미지 렌더/다운로드·참조 소멸 placeholder. Dependencies: s16-fe-foundation, s19-fe-document
- [x] s22-fe-sharing -- 공유 링크 관리(발급/토글/무효화 안내)·게스트 라우트(/share/:token) 읽기전용 뷰·링크 경유 첨부 접근. Dependencies: s16-fe-foundation, s19-fe-document
