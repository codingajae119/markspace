# Implementation Plan

> 프론트엔드 문서 편집 도메인 feature(`frontend/src/features/editor`). 모든 태스크는 `s16` 공통 레이어
> (`apiClient`·`ApiError`·`Role`/`hasWorkspaceRole`/`RequireRole`·확장 `EditorWrapper`/`EditorHandle`
> (`insert`/`replaceRange`·`onImagePaste`/`onFileDrop`)·현재 WS 앰비언트 컨텍스트 `useCurrentWorkspace()`·
> 공용 `Page<T>`·router shell·`useSession`·공용 UI)를 **소비**하며 재구현하지 않는다(동명 훅 재정의 금지).
> 현재 WS(`workspaceId`·`role`)는 `s16` `useCurrentWorkspace()`에서 소비(`role` 값은 s18 멤버십 경로 주입),
> 편집 진입은 `s19` seam, 편집 표면은 `s16` `EditorWrapper` 슬롯으로 `s21`에 노출한다. 잠금/저장/강제 해제 판정은
> 백엔드 엔진 소유이며 UI는 결과·오류만 표면화한다. 자동저장은 편집 세션 이탈 시 1회로 한정한다(주기 타이머·
> debounce 금지). 각 태스크는 단일 책임 경계 안에서 검증 가능한 산출물을 남긴다.

- [ ] 1. 도메인 타입·API·컨텍스트 기반
- [x] 1.1 계약 미러링 타입 정의 (P)
  - `src/features/editor/types.ts`에 백엔드 계약을 미러링: `DocumentLockRead`·`DocumentVersionRead`
    (content 필드 없음)·`DocumentSaveRequest`·편집용 `EditableDocument`(DocumentRead 부분집합)와
    프론트 파생 타입 `LockState`·`EditSessionStatus`. `Page<T>`는 s16 공용 타입(`@/shared/types/page`) import
    (재정의 금지)
  - 관찰 가능한 완료: 타입이 실제 백엔드 스키마(`lock_version/schemas.py`·`document/schemas.py`)와 필드 1:1로
    일치하고(새 필드 발명 없음, 특히 버전에 content 없음), `Page<T>`가 s16 공용 타입 import임이 확인되며
    `tsc --noEmit` 통과
  - _Requirements: 1.1, 1.2, 2.1, 3.1, 6.1_
  - _Boundary: EditorTypes_
- [x] 1.2 잠금/버전 API 모듈 구현
  - `src/features/editor/api/lockVersionApi.ts`에 5개 엔드포인트(`lockDocument`·`saveDocument`·`cancelEdit`·
    `forceUnlock`·`listVersions`) + 편집 초기 콘텐츠용 `getDocument`를 `s16` `apiClient`로 호출. 경로는 실제
    라우터와 동일(`/documents/{id}/lock`·`/save`·`/cancel`·`/force-unlock`·`/versions`, `GET /documents/{id}`).
    204(cancel·force-unlock)는 void, save는 `DocumentVersionRead` 반환
  - 관찰 가능한 완료: 각 메서드가 올바른 경로·본문으로 `apiClient`를 호출하고 204는 void·save는 버전 메타를
    반환함이 단위 테스트로 확인됨. 오류는 `ApiError`로 전파됨
  - _Requirements: 1.1, 1.3, 3.1, 4.1, 5.2, 6.1, 6.2, 7.5_
  - _Boundary: LockVersionApi_
  - _Depends: 1.1_
- [x] 1.3 편집 스코프(현재 WS·세션) 소비 어댑터 구현 (P)
  - `src/features/editor/hooks/useEditorScope.ts`에 s16 `useCurrentWorkspace()`의 최상위 `workspaceId`(string|null)·
    `role`(Role|null)과 `s16` `useSession()`의 `isAdmin`·`currentUserId`를 결합하는 얇은 래퍼 구현. s16과
    **동명(`useCurrentWorkspace`) 훅을 재정의하지 않는다**(이름 충돌·drift 회피). `role` 값은 s18 멤버십 경로로
    주입되나 소비는 s16 훅 단일 경로
  - 관찰 가능한 완료: 어댑터가 `{workspaceId, role, isAdmin, currentUserId}`를 반환하고 s16
    `useCurrentWorkspace()`·`useSession()`만 소비함(동명 훅·자체 WS 컨텍스트 미정의)이 확인됨
  - _Requirements: 7.1, 7.2_
  - _Boundary: useEditorScope_
  - _Depends: 1.1_

- [ ] 2. 순수 잠금 상태 로직·상태 훅
- [x] 2.1 resolveLockState 순수 함수 구현 (P)
  - `src/features/editor/lib/resolveLockState.ts`에 `/lock` 응답(성공 `DocumentLockRead` | 실패 `ApiError`)을
    `LockState`로 매핑: 200→`self`, 409→`other`, 403/404 등→`error`. 폴링·추측 조회 없음, 계약에 없는 보유자
    정보 미발명
  - 관찰 가능한 완료: 200→self·409→other·기타 오류→error 매핑이 단위 테스트로 확인됨(부수효과 없음)
  - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - _Boundary: resolveLockState_
  - _Depends: 1.1_
- [x] 2.2 useEditSession 생명주기 훅 구현
  - `src/features/editor/hooks/useEditSession.ts`에서 마운트 시 `lockDocument`→`resolveLockState`, self면
    `getDocument`로 초기 콘텐츠 로드·편집 활성(`bindHandle`로 `EditorHandle` 결선), other/error면 편집 비활성.
    언마운트/라우트 전환 cleanup에서 `acquired && !released`일 때만 `saveDocument({content: getMarkdown()})`를
    **정확히 1회** 호출(주기 타이머·debounce 없음). `cancel()`은 `cancelEdit` 후 `released=true`(이탈 저장 억제)·
    읽기 복귀. `retryAcquire()`로 강제 해제 후 재획득
  - 관찰 가능한 완료: 진입 200→편집 활성·409→blocked, 이탈 시 잠금 보유+미취소는 `/save` 1회·취소 후/미획득은
    저장 억제, 세션당 저장 최대 1회가 통합 테스트로 확인됨
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 4.5_
  - _Boundary: useEditSession_
  - _Depends: 1.2, 2.1_
- [x] 2.3 useForceUnlock 강제 해제 훅 구현 (P)
  - `src/features/editor/hooks/useForceUnlock.ts`에 `canForceUnlock`(= `s16` `hasWorkspaceRole({minimum:
    OWNER})`, admin bypass 포함)과 `forceUnlock()`(204→성공, 403/404→`ApiError`) 구현. 컴포넌트 역할 비교
    금지, 서버 OWNER 강제가 최종 경계
  - 관찰 가능한 완료: owner/admin에서만 `canForceUnlock` 참, `/force-unlock` 204 후 재획득 트리거·403/404 오류
    표면화가 단위/통합 테스트로 확인됨
  - _Requirements: 5.1, 5.2, 5.4, 5.5_
  - _Boundary: useForceUnlock_
  - _Depends: 1.2_
- [x] 2.4 useVersionHistory 버전 이력 훅 구현 (P)
  - `src/features/editor/hooks/useVersionHistory.ts`에 `listVersions`(`Page[DocumentVersionRead]`) 로드·
    `loadMore`(offset 이어받기)·`current_version_id` 구분·로딩/오류/빈 상태를 구현. 본문 조회·rollback 없음
  - 관찰 가능한 완료: 버전 목록 로드·더 보기 이어받기·현재 버전 구분·403/404 오류 표면화가 통합 테스트로 확인됨
  - _Requirements: 6.1, 6.2, 6.5, 6.6_
  - _Boundary: useVersionHistory_
  - _Depends: 1.2_

- [ ] 3. 편집 UI 컴포넌트
- [ ] 3.1 EditorPane(s16 EditorWrapper edit 소비 + 핸들 바인딩 + 취소 컨트롤 + s16 래퍼 슬롯 s21 노출) 구현
  - `src/features/editor/components/EditorPane.tsx`에서 `s16` `EditorWrapper(mode:"edit", initialContent=
    document.content)`를 렌더하고 `onReady`의 `EditorHandle`(`getMarkdown`·`insert`·`replaceRange`)를
    `useEditSession.bindHandle`에 결선(저장 시 `getMarkdown`). 취소 컨트롤(`cancel`) 노출, 명시적 저장 버튼
    없음(이탈 자동저장). 자체 에디터 인스턴스 금지(이원화 금지). s20은 자체 편집 표면 API를 발명하지 않고
    `s16` `EditorWrapper`가 문서화한 `onImagePaste`/`onFileDrop` 슬롯·`EditorHandle.insert`/`replaceRange`를
    그대로 통과 노출해 `s21`이 소비하게 함(업로드 동작 미구현)
  - 관찰 가능한 완료: 동일 `EditorWrapper(edit)`로 `content`가 렌더되고 핸들이 세션에 결선되며 취소가 동작함,
    자체 인스턴스·자체 표면 API를 만들지 않고 s16 래퍼 슬롯을 통과 노출함이 UI 테스트로 확인됨
  - _Requirements: 1.2, 1.3, 3.1, 4.1, 7.5, 7.7_
  - _Boundary: EditorPane_
  - _Depends: 2.2_
- [ ] 3.2 EditLockBanner(잠금 상태 표시 + 강제 해제 게이팅 노출) 구현
  - `src/features/editor/components/EditLockBanner.tsx`에서 `LockState`가 `self`면 "내가 편집 중"(획득 시각),
    `other`면 "다른 사용자가 편집 중" 안내를 표시. `other`일 때 `useForceUnlock.canForceUnlock`이 참인
    owner/admin에게만 강제 해제 조작을 `<RequireRole minimum={OWNER}>`로 감싸 노출하고 `/force-unlock`→재획득
    결선. 자기 잠금 해제는 EditorPane cancel 경로. 오류는 `ErrorMessage`
  - 관찰 가능한 완료: self/other 상태 표시가 정확하고, owner/admin에게만 강제 해제가 노출·viewer/editor에게는
    숨겨지며 강제 해제 후 재획득이 호출됨이 UI 테스트로 확인됨
  - _Requirements: 2.1, 2.2, 2.3, 5.1, 5.3, 5.4, 5.5_
  - _Boundary: EditLockBanner_
  - _Depends: 2.2, 2.3_
- [ ] 3.3 VersionHistoryPanel(읽기 전용 버전 목록, rollback 없음) 구현 (P)
  - `src/features/editor/components/VersionHistoryPanel.tsx`에서 `useVersionHistory`로 버전 메타(저장자
    `created_by`·시각 `created_at`)를 읽기 전용 목록으로 렌더하고 `current_version_id`를 구분 표시, 더 보기 제공.
    rollback·복원·과거 본문 표시 UI를 두지 않음(계약 제약)
  - 관찰 가능한 완료: 저장자·시각 메타와 현재 버전 구분이 표시되고 더 보기로 이어받으며, rollback/복원/본문
    조회 UI가 없음이 UI 테스트로 확인됨
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_
  - _Boundary: VersionHistoryPanel_
  - _Depends: 2.4_

- [ ] 4. 페이지 조립·라우트 등록·검증
- [ ] 4.1 DocumentEditPage 조립 및 편집 라우트 등록 (통합)
  - `src/features/editor/pages/DocumentEditPage.tsx`(세션 생명주기 + EditorPane + EditLockBanner +
    VersionHistoryPanel 조립, `useEditorScope`로 workspaceId·role·isAdmin·userId 주입)와
    `src/features/editor/routes.tsx`를 구현하고, 편집 라우트(`/documents/:id/edit`)를 `RouteModule[]`
    (`scope: "protected"`)로 export 하여 `s16` `composeRouter`가 보호 슬롯에 합성하게 함(`router.tsx` 수기 편집
    금지). 진입 경로 규약을 노출해 `s19`
    진입점이 도달하게 함. 401은 전역 인터셉터 위임
  - 관찰 가능한 완료: 보호 라우트 하위에서 편집 화면(에디터 pane·잠금 배너·버전 패널)이 렌더되고 진입→잠금
    획득·이탈→저장 생명주기가 결선되며 현재 WS 컨텍스트가 조작에 연결됨(수동/통합 확인)
  - _Requirements: 1.1, 1.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.8_
  - _Boundary: EditorRoutes, DocumentEditPage_
  - _Depends: 3.1, 3.2, 3.3_
- [ ]* 4.2 단위·통합·UI 테스트 작성
  - `resolveLockState`·`lockVersionApi`·`useForceUnlock.canForceUnlock`(단위), `useEditSession`(진입 획득·
    이탈 1회 저장·취소 억제)·`useVersionHistory`(통합), 강제 해제 게이팅(viewer/editor 미노출·owner/admin
    노출)·`EditorPane` edit 단일 렌더·버전 뷰어 rollback 부재(UI) 테스트를 추가
  - 관찰 가능한 완료: 위 테스트 스위트가 모두 통과함(특히 이탈 저장 정확히 1회·취소 후 억제 검증)
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 3.1, 3.2, 3.5, 3.6, 4.1, 4.2, 5.1, 5.2, 5.5, 6.1, 6.3, 6.4, 7.5_
  - _Boundary: Testing_
  - _Depends: 4.1_
- [ ] 4.3 타입체크·빌드 검증
  - `frontend/`에서 `tsc --noEmit`(strict)와 `vite build`를 실행하여 편집 feature가 오류 없이 타입 통과·번들됨을
    확인(계약 미러링·`any` 금지)
  - 관찰 가능한 완료: 타입체크와 프로덕션 빌드가 오류 없이 완료됨
  - _Requirements: 7.5_
  - _Boundary: Scaffold_
  - _Depends: 4.1_

## Implementation Notes
- (2.2) `useEditSession`는 이탈 1회 저장을 `acquiredRef`·`releasedRef`·`savedRef`·`handleRef`(state 아님)로 가드하고, async `saveDocument` 호출 **직전에** `savedRef=true`를 동기 설정해 재진입을 막는다. cancel(204)은 `releasedRef=true`로 이탈 저장을 억제. EditorPane(3.1)은 `bindHandle(handle)`로 EditorWrapper `onReady` 핸들만 결선하면 되고 자체 저장 트리거를 만들지 않는다. 타이머·debounce 금지.
- s16 계약 확정 경로: `apiClient`(`@/shared/api/client`, delete는 `del`·쿼리는 path로), `ApiError`(`@/shared/api/errors`, 숫자 `status`), `EditorWrapper`/`EditorHandle`(`@/shared/editor/EditorWrapper`, mode는 `"edit"|"read"` — `"viewer"` 없음), `useCurrentWorkspace`(`@/app/workspace-context/useCurrentWorkspace`, role은 s16서 현재 null·상위 주입), `useSession`(`@/app/session/useSession`, 3-state union·top-level isAdmin 없음), `hasWorkspaceRole`/`RequireRole`/`Role`(`@/shared/auth/*`, minimum·currentRole 필수 prop), `Page<T>`(`@/shared/types/page`), `RouteModule`/`composeRouter`(`@/app/routeModule`). 라우트 등록은 `main.tsx`의 `featureRouteModules`에 가산(= s17/s18/s19 선례; `router.tsx` 수기 편집 아님).
