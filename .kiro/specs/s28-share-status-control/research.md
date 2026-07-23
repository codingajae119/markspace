# Gap Analysis — s28-share-status-control

## 분석 요약
- **본 기능은 신규 도메인 로직이 거의 없는 "결선(wiring) + 얇은 조회 엔드포인트" 성격**이다. 백엔드·프론트 모두 필요한 부품이 이미 존재하며, 빠진 것은 (1) 읽기 전용 GET 엔드포인트, (2) 프론트 로드 시 초기 조회, (3) 문서 화면 결선이다.
- **백엔드 갭은 작다**: 리포지토리 `ShareLinkRepository.get_by_document`(기존)를 재사용하는 `ShareLinkService.get_link` 1개 + `GET /documents/{id}/share` 라우트 1개. 권한 게이트·스키마·404/401/403 처리는 모두 기존 자산 재사용. 스키마·마이그레이션 변경 없음.
- **프론트 갭의 핵심은 두 가지 결정**: ① `useShareManager`에 마운트 시 초기 조회를 더하되 INV-8 `reissued` 판정을 오염시키지 않을 것, ② 공유 컨트롤을 문서 화면(`DocumentToolbar`)에 결선하는 방식(교차-feature import 제약 vs attachment 선례).
- **주요 리스크는 아키텍처 경계 결정 1건**(document→sharing import)과 **단일 버튼 동작 매핑**(issue vs toggle)뿐. 그 외는 확립된 패턴의 확장으로 Low.
- 추천: **백엔드 = 기존 확장**, **프론트 = `useShareManager` 확장 + 신규 경량 컨트롤 컴포넌트(features/sharing 소유) + DocumentToolbar 결선(하이브리드)**.

---

## 1. 현재 상태 조사 (재사용 가능한 기존 자산)

### 백엔드 (`backend/app/sharing`)
| 자산 | 위치 | 재사용성 |
|---|---|---|
| `POST /documents/{id}/share`(발급), `PATCH .../share`(토글) | `router.py:77,96` | GET 라우트를 같은 파일·같은 게이트로 추가 |
| 권한 게이트 `ws_role_for_document(Role.MEMBER)` | `router.py:81,101` (from `app.document.dependencies`) | **그대로 재사용** — 문서 부재 404·미인증 401·비멤버 403·admin bypass 를 dependency 단계에서 처리 |
| `ShareLinkRepository.get_by_document(db, id) -> ShareLink \| None` | `repository.py:51` | **핵심 재사용** — 문서당 링크(최대 1개) 단건 조회. `toggle_link`이 이미 사용 중 |
| `ShareLinkRead` (+ `from_share_link`) | `schemas.py:39` | 응답 스키마 그대로. `document_id·token·is_enabled·share_url(/public/{token})` 포함 |
| `ShareLinkService`(발급·토글) | `service.py:38` | `get_link` 메서드를 여기에 추가(리포지토리 주입 이미 존재) |

### 프론트 (`frontend/src/features/sharing`, `features/document`)
| 자산 | 위치 | 재사용성 |
|---|---|---|
| `shareApi.issueLink/toggleLink` | `api/shareApi.ts` | `getLink(id)` GET 래퍼 1개 추가 |
| `useShareManager`(link·issue·toggle·frontShareUrl·error·pending·reissued·invalidated) | `hooks/useShareManager.ts` | **확장** — 마운트 시 초기 조회 추가. issue/toggle/INV-8 로직 보존 |
| `CopyLinkButton`("링크 복사" + "복사됨" 피드백 + 실패 폴백 입력창) | `components/CopyLinkButton.tsx` | **Req 5 그대로 충족** — 순수 복사 버튼, URL 상시 미표시 |
| `buildShareUrl(token)` → 게스트 프론트 링크 | `lib/buildShareUrl.ts` | 재사용(백엔드 `share_url`과 구분) |
| `hasWorkspaceRole({currentRole,isAdmin,minimum})` | `shared/auth/permissions.ts` | **재사용** — `minimum=OWNER`로 canShare 판정(admin override 포함) |
| `useCurrentWorkspace().{role,isShareable}` / `useDocumentScope()` | app/workspace-context, features/document | role·isShareable·isAdmin·workspaceId 신호 |
| `DocumentToolbar`(편집·삭제 우측 클러스터) | `components/DocumentToolbar.tsx:219` | **결선 지점** — 공유 버튼 클러스터 추가 |
| `DocumentWorkspacePage`(canEdit 판정·툴바 조립) | `pages/DocumentWorkspacePage.tsx:89` | canShare 판정·신호 주입 |
| latest-wins 조회 idiom(mountedRef/runIdRef) | `DocumentViewer.tsx:62-96` | Req 2.4 경합 방지에 동일 패턴 적용 |

### 확인된 인프라 사실
- **"링크 없음" 응답 처리**: `apiClient`의 `parseJsonBody`가 **204와 빈 본문·JSON `null`을 모두 falsy(undefined/null)로** 반환한다(`client.ts:58-68`). → GET이 `204` 또는 `200 + null` 어느 쪽이든 프론트가 별도 처리 없이 "링크 없음"으로 받는다.
- **교차 관심사**(fetch·credentials·401·ApiError)는 `apiClient` 단일 소유 — 재구현 불필요(Req 6.3 자동 충족).

---

## 2. Requirement → Asset 맵 (갭 태그: Missing / Constraint / Reuse)

- **Req 1 (백엔드 GET)**:
  - Reuse: `ws_role_for_document(MEMBER)` 게이트, `repository.get_by_document`, `ShareLinkRead`.
  - Missing: `ShareLinkService.get_link` 메서드, `GET .../share` 라우트, 응답 모델 `ShareLinkRead | None`.
  - Constraint: 읽기 전용(발급·전환·무효화 금지, Req 1.3). 404/401/403은 게이트 dependency가 이미 산출(서비스 재검사 불필요, 단 방어적 재조회는 선택).
- **Req 2 (FE 초기 판별)**:
  - Reuse: `apiClient.get`, DocumentViewer의 latest-wins idiom.
  - Missing: `shareApi.getLink`, `useShareManager` 초기 조회 로직.
  - Constraint: 초기 조회로 채운 `link`가 `reissued=true`를 유발하면 안 됨(INV-8은 "이미 링크가 있는 상태의 발급"에만 해당). 문서 전환 시 최신만 반영.
- **Req 3 (게이팅)**:
  - Reuse: `hasWorkspaceRole(minimum=OWNER)`, `isShareable`, 문서 active 신호, `DocumentToolbar`/`DocumentWorkspacePage`.
  - Missing: canShare(OWNER) 판정 + 공유 버튼 노출 조건(canShare && isShareable && active && hasSelection)을 툴바에 결선.
  - Constraint: canShare(OWNER)는 canEdit(MEMBER)과 **다른 threshold** — 두 게이트를 구분해 주입.
- **Req 4 (토글·라벨)**:
  - Reuse: `useShareManager.issue/toggle`, 공개 렌더/404 경로(무변경).
  - Missing: shared 판정(`link && link.is_enabled`) + 단일 버튼 동작 매핑 + 라벨 전환.
  - Constraint(**설계 결정**): "공유" 클릭 시 링크가 없으면 `issue()`(새 토큰), 비활성 링크가 있으면 `toggle(true)`(토큰 유지) vs `issue()`(새 토큰) 중 택1.
- **Req 5 (복사)**:
  - Reuse: `CopyLinkButton` + `frontShareUrl` — **그대로 충족**. shared일 때만 노출.
  - Missing: 없음(결선만).
- **Req 6 (오류·무결성)**:
  - Reuse: `useShareManager`의 error/pending/실패 시 link 불침범, `CopyLinkButton` 폴백, `apiClient` 위임 — **거의 그대로 충족**.
  - Missing: pending 중 버튼 비활성 결선(기존 신호 사용).

---

## 3. 구현 접근 옵션

### 백엔드 — Option A (기존 확장) · 권장
- `router.py`에 `GET /documents/{id}/share` 추가(게이트 `ws_role_for_document(MEMBER)` 재사용, `response_model=ShareLinkRead | None`).
- `service.py`에 `get_link(db, document_id) -> ShareLinkRead | None` 추가: `get_by_document` 로 링크 로드 → 있으면 `ShareLinkRead.from_share_link(link)`, 없으면 `None`. 상태 전이 없음.
- ✅ 신규 파일 0, 기존 패턴 100% 재사용. ❌ 없음(라우터 파일에 라우트 1개 증가).

### 프론트 — 결선 방식이 핵심. 세 안 비교

**Option A (전면 확장)**: `useShareManager` 확장 + 공유 버튼을 `DocumentToolbar` 내부에 직접 삽입.
- ✅ 파일 최소. ❌ `DocumentToolbar`(이미 토글·생성·이름변경·편집·삭제·휴지통 소유)에 공유+복사까지 얹어 비대·인지부하 증가. sharing 도메인 로직이 document feature로 새어나감.

**Option B (신규 컴포넌트, features/sharing 소유)**: 경량 `DocumentShareControl`을 `features/sharing`에 신설(내부에서 `useShareManager` + `CopyLinkButton` 소비), `DocumentToolbar`가 게이팅 prop과 함께 렌더.
- ✅ 관심사 분리, sharing 로직이 sharing feature에 잔류, 단위 테스트 격리 용이. ❌ `features/document` → `features/sharing` **교차-feature import** 발생(아래 제약 참조).

**Option C (슬롯/seam)**: `DocumentToolbar`가 `shareSlot?: ReactNode` 슬롯만 노출하고, 두 feature를 모두 아는 상위 조립점이 sharing 컴포넌트를 주입.
- ✅ structure.md 규칙 완전 준수. ❌ 공유 버튼은 선택 문서 id에 강하게 묶여 툴바 깊숙이 위치 → 슬롯을 상위(페이지/라우트)에서 문서 id·상태와 함께 아래로 관통시켜야 해 배선이 번거로움. 조립점이 결국 `features/document` 안(DocumentWorkspagePage)이라 순수 준수도 어려움.

> **핵심 제약 & 선례**: structure.md:28 — *"feature는 다른 feature를 직접 import 하지 않는다"*. 그러나 **이미 완화 적용된 선례**가 있다: `features/document/components/DocumentViewer.tsx:25` 가 `@/features/attachment`(buildAttachmentRenderers)를 직접 import 한다. 첨부는 "capability feature"로 교차 소비되며, 의존은 비순환이다(attachment/sharing 은 document 를 import 하지 않음). sharing 도 `app/workspace-context`·`shared` 만 소비하므로 `document → sharing` 은 비순환이다.
>
> → **권장은 Option B**: attachment 선례를 따라 `DocumentShareControl`을 `features/sharing`에 두고 `DocumentToolbar`가 import. 단, 이 경계 완화는 사용자·설계 단계에서 명시 승인할 항목으로 남긴다(대안 C도 유효).

---

## 4. Effort & Risk

| 영역 | Effort | Risk | 근거 |
|---|---|---|---|
| 백엔드 GET | **S** | **Low** | 라우트 1 + 서비스 메서드 1, 리포지토리·게이트·스키마 전부 재사용, 스키마·마이그레이션 무변경 |
| 프론트 useShareManager 확장 | **S** | **Medium** | INV-8 `reissued` 판정 오염 방지·latest-wins 경합 처리에 주의 필요 |
| 프론트 컨트롤 신설 + 결선 | **S~M** | **Low~Medium** | 교차-feature import 경계 결정 1건, 게이팅(OWNER≠MEMBER) 구분, 단일 버튼 동작 매핑 |
| 테스트(BE 라우터/서비스, FE api/hook/component/통합) | **S~M** | **Low** | 기존 sharing/toolbar 테스트 패턴 미러 |

**전체: M / Low~Medium.**

---

## 5. 설계 단계로 이월할 핵심 결정 & Research Needed

**핵심 설계 결정(Design이 확정):**
1. **"링크 없음" 응답 형태**: `200 + ShareLinkRead | null`(발급/토글의 200+ShareLinkRead와 균질 → 권장) vs `204 No Content`. 둘 다 `apiClient`가 falsy로 흡수하므로 FE 영향 동일.
2. **단일 버튼 동작 매핑**: shared = `link && link.is_enabled`. "공유" = 링크 없으면 `issue()`(새 토큰), 비활성 링크 있으면 `toggle(true)`(같은 URL 부활, on/off 스위치 의미 → 권장) 또는 `issue()`(새 토큰, INV-8). "공유 해제" = `toggle(false)`.
3. **초기 조회와 INV-8 격리**: GET으로 채운 초기 `link`는 `reissued`를 건드리지 않아야 함. `linkRef` 시드는 하되 `reissued=false` 유지.
4. **결선 경계(Option B vs C)**: `document → sharing` 직접 import 허용(attachment 선례) vs 슬롯 seam. → 설계에서 확정하고 boundary commitment로 기록.
5. **컨트롤 배치**: `DocumentToolbar` 우측 클러스터에 `canShare(OWNER) && isShareable && docActive && hasSelection`으로 게이팅. 휴지통 모드(비active)에서는 자동 미노출.

**Research Needed(경미, 구현 중 확인):**
- FastAPI `response_model=ShareLinkRead | None` 이 본문을 리터럴 `null`로 직렬화하는지(또는 204 선택) — 택일 시 무관.
- `useShareManager`의 현재 소비처는 `ShareLinkPanel`(미마운트)뿐 — 초기 조회 추가가 기존 `ShareLinkPanel.test.tsx`/`integration.test.tsx` 기대를 깨는지 확인(마운트 시 GET 발생 → 모킹 갱신 필요 가능).

---

## 6. 권장 요약
- **백엔드**: 기존 확장(라우트 + 서비스 메서드, 리포지토리 재사용). Effort S / Risk Low.
- **프론트**: `useShareManager` 확장(초기 조회, INV-8 격리, latest-wins) + `features/sharing`에 경량 `DocumentShareControl` 신설(`CopyLinkButton` 재사용) + `DocumentToolbar`/`DocumentWorkspacePage`에 OWNER 게이팅 결선.
- **명시 승인 필요**: 결선 경계(document→sharing 직접 import) — attachment 선례 근거로 권장하되 설계에서 확정.

---

## 7. 설계 합성 결과 (Design Synthesis)

설계 단계에서 확정한 5개 핵심 결정. `-y` fast-track 하에서 attachment 선례를 근거로 자율 확정한다.

### 7.1 확정 결정
1. **BE 응답 형태 = `200 + ShareLinkRead | None`** (204 아님). FastAPI `response_model=ShareLinkRead | None` 이 `None` 을 `200 + 본문 null` 로 직렬화한다(발급/토글의 `200 + ShareLinkRead` 와 균질). FE `apiClient.get` 은 `JSON.parse("null")=null` 을 그대로 반환하므로 `getLink` 는 `ShareLinkRead | null` 을 별도 처리 없이 받는다(`client.ts:60-68` parseJsonBody 는 204·빈 본문을 undefined 로, `null` 본문을 null 로 흡수).
2. **단일 버튼 동작 매핑**: `shared = link !== null && link.is_enabled`.
   - "공유"(미공유): `link === null` → `issue()`(새 토큰) / 비활성 링크 존재 → `toggle(true)`(토큰 유지·같은 URL 부활 = on/off 스위치 의미).
   - "공유 해제"(공유 중): `toggle(false)`.
   - 근거: 단일 버튼의 심상은 on/off 스위치이므로 비활성→활성은 새 토큰(INV-8)이 아니라 토큰 유지 토글이 자연스럽다. 신규 발급만 새 토큰.
3. **초기 조회와 INV-8 격리**: 마운트 GET 이 `link`/`linkRef` 를 시드하되 `reissued` 를 **절대 건드리지 않는다**. 신규 상태 필드 `loading`(초기 조회 in-flight) 추가. 문서 전환 시 runId 가드로 최신 결과만 반영(Req 2.4, DocumentViewer latest-wins idiom 재사용). 조회 실패 시 `error` 표면화 + `link=null` 유지(불확실을 공유 중으로 단정 금지, Req 2.3).
4. **결선 경계 = Option B (document → sharing 직접 import)**. `DocumentToolbar` 가 `@/features/sharing` 배럴에서 `DocumentShareControl` 을 import(선례: `DocumentViewer.tsx:25` → `@/features/attachment`). 비순환(sharing 은 document 를 import 하지 않음). boundary commitment 로 기록.
5. **노출 게이트 = 툴바 결선 지점 소유**: `!trashMode && canShare(OWNER) && isShareable && hasSelection`. `canShare` 는 페이지가 `hasWorkspaceRole({minimum: OWNER})` 로 산정(admin override 포함). `isShareable` 은 `useDocumentScope` 를 **1필드 확장**해 표면화(document feature 의 단일 소비 지점 idiom 유지). active 축은 활성 트리 + 비휴지통 모드로 보장됨.

### 7.2 build-vs-adopt
- **Adopt(무변경 재사용)**: `repository.get_by_document`, `ws_role_for_document(MEMBER)` 게이트, `ShareLinkRead.from_share_link`, `CopyLinkButton`, `buildShareUrl`, `hasWorkspaceRole`, latest-wins idiom, `apiClient.get/parseJsonBody`.
- **Build(신규/확장 최소)**: BE `ShareLinkService.get_link`(1 메서드) + `GET .../share`(1 라우트); FE `shareApi.getLink`(1 래퍼) + `useShareManager` 초기 조회 확장 + `DocumentShareControl`(1 신규 컴포넌트) + `useDocumentScope` isShareable 1필드 + `DocumentToolbar`/`DocumentWorkspacePage` 결선.

### 7.3 재검증 트리거(기존 테스트 영향)
- `useShareManager.test.ts`: 마운트가 이제 `shareApi.getLink` 를 호출 → 모크에 `getLink: vi.fn()` 추가 필요 + 초기 시드/loading/latest-wins 단언 추가.
- `ShareLinkPanel.test.tsx`·`ShareLinkPanel.integration.test.tsx`: 마운트 시 `getLink` 발생 → 모크 갱신 필요. 시드 후 `reissued` 의미가 **더 정확해짐**(사전 링크 존재 반영)이나 패널은 계속 동작(회귀 아님).
- `shareApi.test.ts`: `getLink` GET 계약 테스트 추가.
