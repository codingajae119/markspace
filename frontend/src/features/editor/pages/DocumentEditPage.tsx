/**
 * DocumentEditPage — 편집 화면 조립부 (design.md §화면 컴포넌트 ~603-606; Req 1.1, 1.5, 7.1~7.8).
 *
 * 라우트 파라미터(:id)에서 documentId 를 파싱해 편집 세션 생명주기(`useEditSession`)와 s16
 * 앰비언트 스코프(`useEditorScope`: workspaceId·role·isAdmin·currentUserId)를 결선하고,
 * EditorPane + EditLockBanner + VersionHistoryPanel 을 하나의 화면으로 조립하는 in-boundary
 * 페이지다. 상태·잠금·저장·권한 판정은 소유하지 않고 이미 구현된 훅·컴포넌트에 위임한다:
 * - `useEditorScope()`: s16 `useCurrentWorkspace()`(workspaceId·role) + `useSession()`(isAdmin·
 *   userId)의 얇은 투영(Req 7.1). role 비교는 하위 컴포넌트의 RequireRole 이 소유한다.
 * - `useEditSession(documentId)`: 진입 잠금 획득 → 편집 활성 → 이탈 시 1회 자동저장/취소 생명주기.
 *
 * 렌더 결선:
 * - `status === "acquiring"`: 잠금 획득 진행 → {@link Spinner}(EditorPane 미마운트).
 * - EditLockBanner: `lockState` 를 표시(self "내가 편집 중"/other "다른 사용자가 편집 중"/error).
 *   강제 해제 노출·호출은 배너 내부 s16 게이팅(RequireRole OWNER + useForceUnlock)이 소유하며,
 *   여기서는 scope.role·isAdmin·session.retryAcquire(재획득)만 주입한다.
 * - 편집 활성(`session.document` 존재): EditorPane(세션 결선) + VersionHistoryPanel(현재 버전
 *   구분 표시). 콘텐츠 없이 편집 인스턴스를 만들지 않으므로 document 확보 시에만 마운트한다.
 * - "읽기로 돌아가기" back affordance: 타인 잠금(other)·취소(released) 후 읽기 화면 복귀 경로
 *   (Req 2.2). `useNavigate` 로 문서 메인(`/documents`)으로 복귀한다.
 *
 * 경계: viewer 는 편집에 도달하지 않으며(진입점 게이팅은 s19, 서버 403 이 최종 경계) 이 페이지는
 * 로컬 role 게이트를 재구현하지 않는다(Req 1.5·7.2·7.8). 401 은 s16 전역 인터셉터가 처리하므로
 * 여기서 특별 취급하지 않는다(Req 7.4). 오류는 하위 컴포넌트가 `ApiError` 를 그대로 표면화한다
 * (Req 7.3). 다른 feature(`@/features/document`·`@/features/workspace`)를 import 하지 않는다
 * (Req 7.5).
 *
 * Requirements: 1.1(진입·세션 결선), 1.5(viewer 미도달), 7.1(WS·세션 스코프 주입), 7.2(권한
 *   게이팅 위임), 7.3(ApiError 표면화 위임), 7.4(401 전역 위임), 7.5(다른 feature 비의존·s16
 *   래퍼 단일), 7.6(보호 라우트 등록), 7.8(클라이언트 게이팅은 보안 경계 아님).
 */

import type { ReactElement } from "react";
import { useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Spinner } from "@/shared/ui";

import { useEditorScope } from "../hooks/useEditorScope";
import { useEditSession } from "../hooks/useEditSession";
import { EditorPane } from "../components/EditorPane";
import { EditLockBanner } from "../components/EditLockBanner";
import { VersionHistoryPanel } from "../components/VersionHistoryPanel";

// 읽기 화면 복귀 경로(문서 메인). s19 소유 라우트지만 feature import 를 피하기 위해 경로 문자열만
// 사용한다(두 feature 는 서로 직접 import 하지 않는다, Req 7.5).
const READING_PATH = "/documents";

/** 편집 화면. 라우트 파라미터의 documentId 에 세션·스코프를 결선해 편집 표면을 조립한다. */
export function DocumentEditPage(): ReactElement {
  const { id } = useParams();
  const documentId = Number(id);
  const scope = useEditorScope();
  const session = useEditSession(documentId);
  const navigate = useNavigate();

  const goToReading = useCallback(() => {
    navigate(READING_PATH);
  }, [navigate]);

  return (
    <section aria-labelledby="document-edit-heading" className="flex flex-col gap-6">
      <header className="flex items-center justify-between">
        <h1 id="document-edit-heading" className="text-lg font-semibold text-slate-900">
          문서 편집
        </h1>
        {/* 타인 잠금·취소 후 읽기 화면으로 복귀하는 경로(Req 2.2). 편집 중 이탈도 이 경로로
            일어나며 useEditSession cleanup 이 이탈 시 1회 자동저장을 수행한다. */}
        <button
          type="button"
          onClick={goToReading}
          className="text-sm font-medium text-slate-600 hover:text-slate-900"
        >
          읽기로 돌아가기
        </button>
      </header>

      {session.status === "acquiring" ? (
        <div className="flex justify-center py-8">
          <Spinner label="편집 잠금을 확보하는 중" />
        </div>
      ) : (
        <>
          {/* 잠금 상태 표시(self/other/error) + 강제 해제 노출은 배너 내부 s16 게이팅이 소유. */}
          <EditLockBanner
            lockState={session.lockState}
            documentId={documentId}
            currentRole={scope.role}
            isAdmin={scope.isAdmin}
            onRetry={session.retryAcquire}
          />

          {/* 잠금 보유(self)로 초기 콘텐츠가 확보된 경우에만 편집 표면·버전 이력을 마운트한다. */}
          {session.document !== null ? (
            <div className="flex flex-col gap-6 lg:flex-row">
              <div className="min-w-0 flex-1">
                <EditorPane session={session} />
              </div>
              <aside className="lg:w-80 lg:shrink-0">
                <VersionHistoryPanel
                  documentId={documentId}
                  currentVersionId={session.document.current_version_id ?? null}
                />
              </aside>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
