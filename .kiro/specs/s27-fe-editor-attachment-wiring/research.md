# 갭 분석 (Gap Analysis) — s27-fe-editor-attachment-wiring

> 목적: 요구사항(WHAT)과 기존 코드베이스의 간극을 조사해 설계 단계 전략을 정보로 제공한다. 결정이 아니라 선택지와 근거를 제시한다.
> 분석 언어: 한국어(spec.json.language=ko). 조사 방식: 요구사항이 명시한 파일·행을 직접 코드로 재검증.

## 요약 (Analysis Summary)

- **성격**: 새 기능이 아니라 **조립 갭(assembly gap) 해소**다. s21 브리지(`useEditorUploadBridge`·`buildAttachmentRenderers`)와 s16 슬롯(`onImagePaste`·`onFileDrop`·`renderers`·`onReady`)은 이미 완성·단위테스트되어 있으나, `grep '@/features/attachment' src/` 결과 **전 코드베이스 소비처 0** 을 재확인했다(편집 표면뿐 아니라 s19 읽기 뷰·s22 공유 뷰도 렌더 브리지를 결선하지 않았다). s27 은 편집 표면만 범위로 한다.
- **신규 코드는 소량**: `DocumentEditPage` 에 브리지 호출·`canUpload` 도출·복합 `onReady`·`renderers` 주입, `EditorPane` 에 `renderers`(+에디터 준비 콜백) 통과 prop 추가. 나머지 업로드/치환/blob 로딩/저장 동작은 전부 기존 소유다.
- **핵심 설계 결정 3건**: ① 단일 `EditorHandle` 을 자동저장·업로드 양쪽에 분배하는 **복합 `onReady`** 배선 위치(Req 5), ② `features/editor → @/features/attachment` **교차 feature import 경계**(structure.md 불변식과 충돌·전 코드베이스 최초 사례), ③ s16 `.outerHTML` 직렬화 seam 으로 인해 **인증 blob 실렌더가 런타임 제한**됨 → 통합 테스트 검증 깊이(배선 검증 vs 실 blob DOM 검증) 결정.
- **테스트 전략**: 기존 편집 테스트는 `vi.mock("@/shared/editor/EditorWrapper")` 로 래퍼를 목킹하고 props 를 검증하는 패턴이다. 조립 통합 테스트도 동일 패턴으로 (a) 브리지 핸들러·렌더러가 래퍼에 도달함을 단언하고 (b) 기록된 콜백을 구동해 업로드→자리표시자→치환을 검증한다(실제 Toast/jsdom paste 이벤트 미사용).
- **규모·위험**: **Effort S(1~3일)**, **Risk Low~Medium**. 위험 상승 요인은 복합 `onReady` 의 exactly-once 자동저장 불변식 보존, `.outerHTML` seam 의 검증 한계, jsdom 조립 테스트 배선 방식이다.

---

## 1. 현재 상태 조사 (Current State Investigation)

### 1.1 기존 자산 (코드 직접 검증 완료)

| 자산 | 위치 | 상태 | s27 관련 계약 |
|---|---|---|---|
| 업로드 브리지 | `features/attachment/hooks/useEditorUploadBridge.ts` | 완성·단위테스트 | `useEditorUploadBridge({documentId: number\|null, canUpload})` → `{ onReady, onImagePaste, onFileDrop }`. 내부에서 `canUpload && documentId!==null` 게이팅(no-op guard). `onReady` 는 handle 을 ref 저장 후 `InsertContext`(insert/replaceRange 위) 구현. |
| 낙관 업로드 | `features/attachment/hooks/useAttachmentUpload.ts` | 완성 | `startUpload` → placeholder 삽입 → 201 성공 시 `/attachments/{id}` 참조 치환, 실패 시 오류 마커 치환. `locateToken` 으로 콘텐츠 문자열에서 토큰 재탐색(Req 3.4·3.5). |
| 렌더 브리지 | `features/attachment/components/AttachmentRenderBridge.tsx` | 완성·단위테스트 | `buildAttachmentRenderers()` → `{customImageRenderer, customHTMLRenderer.link}`. edit·read 공통 단일 객체. |
| 배럴 | `features/attachment/index.ts` | 완성 | 위 두 브리지 + 렌더 컴포넌트를 export. 문서상 **s20 편집 표면 소비용 진입점**으로 자기규정. |
| s16 래퍼 슬롯 | `shared/editor/EditorWrapper.tsx` | 완성 | `onImagePaste`(Toast `addImageBlobHook`, 209행 조건 결선)·`onFileDrop`(루트 DOM `drop`, 247·263행 조건 결선)·`renderers`·`onReady`(단 1회 호출, 194·276행). |
| 권한 게이팅 유틸 | `shared/auth/permissions.ts` | 완성 | `hasWorkspaceRole({currentRole, isAdmin, minimum})` 순수함수. admin bypass → role null false → `currentRole>=minimum`. |
| role enum | `shared/auth/roles.ts` | 완성 | `Role.MEMBER=1 < OWNER=2`. **viewer 상수 없음** — 비멤버·미확정은 `role===null`(global-read-openness 정책). |
| 편집 스코프 | `features/editor/hooks/useEditorScope.ts` | 완성 | `{ workspaceId, role: Role\|null, isAdmin, currentUserId }`. s16 `useCurrentWorkspace().role` + 세션 파생. |
| 세션 훅 | `features/editor/hooks/useEditSession.ts` | 완성 | `bindHandle(handle)` → handleRef 저장. 이탈 cleanup 이 `handle.getMarkdown()` 로 **정확히 1회** 자동저장(savedRef/releasedRef 가드). |

### 1.2 조립 공백 지점 (미결선, 코드 확인)

- **`DocumentEditPage.tsx:112`** — `<EditorPane session={session} />` 만 렌더. 브리지 미호출, `canUpload` 미도출, `renderers` 미주입. `useEditorScope()` 는 이미 호출(56행)하나 `role` 을 업로드 게이팅에 쓰지 않는다.
- **`EditorPane.tsx:29-40, 71-77`** — `onImagePaste`·`onFileDrop` prop 은 **존재하나 상위가 바인딩하지 않아 항상 undefined** → 래퍼가 두 캡처 경로를 등록하지 않음(EditorWrapper `wireImagePaste`/`wireFileDrop` false). **`renderers` prop 자체가 없음** → 렌더 override 미전달. `onReady={session.bindHandle}` 를 내부 하드코딩(복합 배선 부재).
- **소비처 0 재확인** — `grep -rl '@/features/attachment' src/` = 0. 배럴이 소비용으로 설계됐으나 어디서도 import 되지 않음.

### 1.3 관례·경계

- **feature 격리 불변식**(structure.md): "feature 는 다른 feature 를 직접 import 하지 않는다. 교차 관심사는 공통 레이어(`src/app`·`src/shared`)가 단일 소유." 현재 코드베이스에 feature→feature import **사례 0**(grep 확인). s27 이 이를 처음 도입할지가 결정 사항.
- **DocumentEditPage 문서화된 비의존 목록**(Req 7.5): "`@/features/document`·`@/features/workspace` 를 import 하지 않는다" — **attachment 는 목록에서 의도적으로 제외**됨(s21 배럴이 인가된 소비 seam). 단 structure.md 는 더 절대적 표현.
- **테스트 배치**: feature 폴더 co-locate(`*.test.tsx`/`*.integration.test.tsx`). 편집 테스트는 `vi.mock("@/shared/editor/EditorWrapper")` 로 heavy Toast 를 목킹하고 전달 props 를 기록·단언(`EditorPane.test.tsx:34`).

---

## 2. 요구사항 실현성 분석 (Requirement → Asset Map)

태그: **[결선]** 배선만 필요 / **[제약]** 기존 아키텍처 제약 / **[미지]** 설계 조사 필요.

| 요구사항 | 기존 자산 | 갭 | 태그 |
|---|---|---|---|
| **R1** 마크다운 업로드 진입점 결선 | 브리지 핸들러·래퍼 슬롯·EditorPane 슬롯 prop 모두 존재 | `DocumentEditPage` 가 `useEditorUploadBridge` 호출 후 `onImagePaste`/`onFileDrop` 를 EditorPane 에 바인딩 | [결선] |
| **R2** 첨부 렌더 결선 | `buildAttachmentRenderers()`·래퍼 `renderers` 슬롯 존재. **EditorPane 에 `renderers` prop 부재** | EditorPane 에 `renderers` 통과 prop 추가 + 페이지가 `buildAttachmentRenderers()` 주입 | [결선] |
| R2.1 인증 blob 이미지 실렌더 | `customImageRenderer`→`AttachmentImage`(createRoot 마운트) | **s16 `.outerHTML` 동기 직렬화 seam** 으로 React19 async 마운트가 포착 안 됨(AttachmentRenderBridge 자기문서 REVALIDATION TRIGGER). 실 blob 렌더는 런타임 제한 | [제약][미지] |
| **R3** 낙관 자리표시자 종단 치환 | `useAttachmentUpload`+`locateToken`+`InsertContext` 완성 | 신규 코드 0 — 통합 테스트로만 종단 검증 | [결선] |
| **R4** `canUpload` 도출 | `hasWorkspaceRole`(s16)·`useEditorScope().role/isAdmin` | `canUpload = hasWorkspaceRole({currentRole: role, isAdmin, minimum: Role.MEMBER})` 도출. 자체 role 비교 금지(R4.5 → s16 위임) | [결선] |
| R4.3 documentId 미확보 no-op | 브리지가 `documentId: number\|null` 수용 | 페이지의 `Number(id)` NaN 가드 → `number\|null` 정규화 | [결선] |
| **R5** 단일 `EditorHandle` 공유 | `session.bindHandle`·`bridge.onReady` 모두 handle 요구. 래퍼 `onReady` **1회만 호출** | **복합 `onReady`** 로 한 handle 을 양쪽에 분배(배선 위치 결정 필요) | [제약][미지] |
| **R6** 경계 존중·조립 회귀 방지 | 목킹 기반 테스트 하네스 존재 | 조립 레벨 통합 테스트 신규 작성(단위테스트 사각 보완) | [결선][미지] |

### 비기능·경계
- **보안 경계**(R4.4): 클라이언트 `canUpload` 는 UI 편의, 서버 403 이 최종. `hasWorkspaceRole` 자기문서와 일치 — 재확인만.
- **백엔드 무수정**(R6.2): s12 첨부 저장·서빙 미변경. FE 전용.
- **위지윅 제외**(R6.5·요구 배경): `WysiwygEditor.replaceSelection` 배열 좌표 결함은 범위 밖. 마크다운 모드만 종단 보장 — 삽입 로직 수정 불요.

---

## 3. 구현 접근 선택지 (Implementation Approach Options)

핵심 결정은 **① 복합 `onReady` 배선 위치**와 **② 교차 feature import 경계** 두 축이며, 이를 조합해 제시한다.

### 축 ① — 복합 `onReady`(단일 handle 분배, Req 5) 배선 위치

**Option A-1 · EditorPane 내부 합성 (권장)**
EditorPane 이 기존 `onReady={session.bindHandle}` 책임을 유지하면서, 추가 `onEditorReady?: (h)=>void`(브리지 onReady) prop 을 받아 내부에서 합성:
```
onReady={(h) => { session.bindHandle(h); onEditorReady?.(h); }}
```
- ✅ EditorPane 의 "세션 결선 소유" 책임 유지, 최소 surface(prop 1개 추가). 복합 콜백이 신원 안정성 위해 EditorPane 내 `useCallback`/ref 로 안정화 가능.
- ✅ 두 소비자 모두 자기 ref 에 동일 handle 저장 → **단일 Toast 인스턴스 handle 공유** → 업로드 삽입분이 이탈 자동저장(`getMarkdown`)에 반영(R5.1·5.2).
- ❌ EditorPane 이 브리지 존재를 약하게 인지(콜백 하나 추가) — 순수 슬롯성 미세 약화.

**Option A-2 · DocumentEditPage 가 복합 콜백 소유 + EditorPane `onReady` prop 노출**
EditorPane 의 `onReady` 를 prop 으로 완전 외부화하고, 페이지가 `(h)=>{session.bindHandle(h); bridge.onReady(h);}` 를 주입.
- ✅ 조립 로직 전량이 "조립부" DocumentEditPage 에 집중(응집).
- ❌ EditorPane 의 현재 `onReady={session.bindHandle}` 자기소유를 페이지로 이관 → 기존 EditorPane 테스트/계약 변경 폭 증가. 복합 콜백 신원 안정화를 페이지가 책임.

> 두 안 모두 동작상 동일(단일 handle 공유). 차이는 **합성 소유 위치**와 기존 계약 변경 폭. A-1 이 변경 최소·기존 책임 보존 측면에서 우위.

### 축 ② — `@/features/attachment` 소비 경로 (교차 import 경계)

**Option B-1 · editor feature 에서 직접 import (실용·요구 암시)**
`DocumentEditPage` 가 `import { useEditorUploadBridge, buildAttachmentRenderers } from "@/features/attachment"`.
- ✅ s21 배럴의 설계 의도(소비 진입점) 그대로 실현. 최소 배선. Req 7.5 비의존 목록에 attachment 부재 = 암묵 허용.
- ❌ structure.md "feature→feature 직접 import 금지" 불변식과 표면 충돌. 전 코드베이스 **최초** 교차 import 선례.

**Option B-2 · 공통/앱 레이어 조립 후 prop 주입 (불변식 보존)**
`src/app` 라우트 조립 레이어가 두 feature 를 import 해 브리지·렌더러를 `DocumentEditPage` 에 props 로 주입. editor feature 는 attachment 를 모른다.
- ✅ structure.md 불변식 유지, feature 격리 순수.
- ❌ 새 조립 레이어/주입 배관 도입 → surface 증가. `useEditorUploadBridge` 는 훅이라 컴포넌트 밖 조립이 부자연(훅은 렌더 트리 안에서 호출돼야 함) → 앱 레이어 컴포넌트가 훅을 호출해 render-prop/children 으로 주입하는 간접층 필요(과설계 위험).

**Option B-3 · 소비 계약을 shared 로 재홈 (비권장)**
브리지를 `shared` 로 이동 — s21 소유 재홈. R6.1·R6.3 "재구현·재소유 금지" 위반. 배제.

### 권장 조합 (설계 판단은 design 단계)
**A-1 + B-1** — EditorPane 내부 복합 `onReady` + editor feature 직접 import. 근거: (a) Req 7.5 가 attachment 를 비의존 목록에서 의도적으로 제외, (b) s21 배럴이 소비 진입점으로 자기규정, (c) 훅 특성상 컴포넌트 트리 내 호출이 자연스러움, (d) 변경 surface 최소. 단 **structure.md 불변식과의 긴장은 design.md 에서 명시적으로 문서화**하고, "attachment 배럴은 인가된 소비 seam" 예외를 스티어링 관점에서 정당화할 것.

---

## 4. Research Needed (설계 단계 이월)

1. **`.outerHTML` 직렬화 seam 의 R2 검증 깊이** — s16 `EditorWrapper.toToastHTMLRenderer` 가 반환 HTMLElement 를 동기 `.outerHTML` 로 직렬화하고 React19 `createRoot` 는 async 커밋이라 인증 blob 실렌더가 직렬화 시점 DOM 에 부재. R6.3 이 s16 수정을 금지하므로, R2 통합 테스트는 **"buildAttachmentRenderers 가 래퍼 `renderers` 에 결선됨"(배선 검증)** 까지 단언하고 실 blob DOM 검증은 seam 한계로 유보할지 design 에서 확정. (관련 upstream seam 은 s16/s21 memory 에 이미 기록됨.)
2. **조립 통합 테스트 배선 방식** — 기존 패턴대로 `EditorWrapper` 목킹 후 (a) 전달된 `onImagePaste`/`onFileDrop`/`renderers`/`onReady` 신원 단언, (b) 기록 콜백 구동(`onReady(mockHandle)` → `onImagePaste(file)`)으로 `attachmentApi` 목킹 하에 placeholder 삽입→치환 종단 검증. 실제 Toast paste/drop DOM 이벤트는 jsdom 미지원 → 구동 방식 확정 필요.
3. **`canUpload` 최소 role 확정** — `minimum: Role.MEMBER` 로 편집 권한자(member↑)+admin bypass 통과, role null(비멤버·미확정)·미확정 로딩 시 비활성(R4.2). s24 role 복원 경로가 편집 라우트에서 role 을 시드함을 전제(s18~s22 "role=null 상위갭" 해소분). 로딩 중 순간 null → 진입점 방어적 비활성(허용).
4. **복합 `onReady` 신원 안정성** — EditorWrapper 는 `onReady` 를 ref 로 캡처해 재실행을 막지만, 복합 콜백이 매 렌더 재생성되면 최신 브리지/세션을 참조하도록 `useCallback` 또는 ref-latch 로 안정화. exactly-once 자동저장 가드(savedRef)와 상호작용 무해함을 확인.
5. **documentId 정규화** — `Number(useParams().id)` 의 NaN 케이스를 `number|null` 로 정규화해 브리지 R4.3 no-op 을 만족.

---

## 5. 규모·위험 (Effort & Risk)

- **Effort: S (1~3일)** — 신규 로직 소량(브리지 호출·canUpload 도출·복합 onReady·renderers prop). 대부분 배선 + 조립 통합 테스트 작성. 기존 패턴(목킹 테스트·hasWorkspaceRole·useEditorScope) 재사용.
- **Risk: Low~Medium**
  - *Low 근거*: 업로드/치환/blob/저장 동작 전부 기존 소유·단위테스트 완료. 백엔드 무수정. 마이그레이션 없음.
  - *Medium 상승 요인*: ① 복합 `onReady` 가 exactly-once 자동저장 불변식을 깨지 않아야 함(회귀 민감), ② `.outerHTML` seam 으로 R2 실렌더 검증이 배선 수준에 그침(요구와 런타임 간 간극 명문화 필요), ③ jsdom 에서 실제 Toast paste/drop 미지원 → 통합 테스트가 콜백 구동식이라 "진짜 사용자 경로"와 한 겹 떨어짐.

---

## 6. 설계 단계 권고 (Recommendations for Design)

- **선호 접근**: A-1(EditorPane 내부 복합 onReady) + B-1(editor→attachment 직접 import). 변경 surface 최소, s21 배럴 설계 의도 실현, 훅 트리내 호출 자연스러움.
- **핵심 결정 문서화**: (1) 복합 onReady 소유 위치와 단일 handle 공유 불변식, (2) 교차 feature import 예외를 structure.md 불변식 대비 명시 정당화, (3) `.outerHTML` seam 으로 인한 R2 검증 범위(배선 vs 실 blob) 확정.
- **이월 조사 항목**: §4 의 5건(검증 깊이·테스트 배선·최소 role·onReady 안정성·documentId 정규화).
- **비범위 재확인**: 위지윅 replaceSelection 결함·s16 래퍼 내부·백엔드 s12 는 손대지 않음(R6.2·6.3·6.5).

---

## 7. 설계 합성 결과 (Design Synthesis Outcomes)

design.md 작성 시 확정한 합성 결과.

- **채택 결정(build vs adopt)**: 전량 adopt. 신규 컴포넌트·신규 파일 0. s21 브리지·s16 래퍼·`hasWorkspaceRole` 을 소비만 한다. 신규 코드는 기존 2파일(`DocumentEditPage`·`EditorPane`)의 배선 확장뿐.
- **일반화(generalization)**: 없음. 이 스펙은 결선만 하므로 새 추상화를 만들지 않는다. `buildAttachmentRenderers` 소비 경로는 향후 s19 읽기 뷰·s22 공유 뷰가 동일하게 재사용할 선례가 되나, 그 일반화는 각 스펙의 몫이며 여기서 선반영하지 않는다.
- **단순화(simplification)**: 복합 `onReady` 를 EditorPane 내부에 국소화(A-1)해 DocumentEditPage 조립부의 콜백 신원 안정화 부담을 제거. `uploadDocumentId` 는 기존 `documentId=Number(id)` 를 건드리지 않고 브리지용 정규화 값만 파생(세션·배너 계약 무변경).
- **확정된 3대 결정**: D1(EditorPane 내부 복합 onReady·단일 handle 공유), D2(editor→attachment 직접 import 를 인가된 소비 seam 예외로 문서화), D3(`.outerHTML` seam 으로 R2 통합 테스트를 배선 검증 깊이로 확정·실 blob DOM 유보). 셋 다 §3 선택지 중 권장안(A-1+B-1) + §4.1 검증 깊이 이월 항목의 귀결.
- **검증**: design.md 의 모든 기술 주장(EditorWrapper exactly-once onReady·209/247행 조건·131-138행 `.outerHTML`·`hasWorkspaceRole` 시그니처·`Role.MEMBER=1`·브리지 `isEnabled`)을 실제 코드로 재확인함.
