/**
 * DocumentEditPage — 편집 화면 조립부 (design.md §화면 컴포넌트 ~603-606; Req 1.1, 1.5, 7.1~7.8).
 *
 * 라우트 파라미터(:id)에서 documentId 를 파싱해 편집 세션 생명주기(`useEditSession`)와 s16
 * 앰비언트 스코프(`useEditorScope`: workspaceId·role·isAdmin·currentUserId)를 결선하고,
 * EditorPane + EditLockBanner 를 하나의 화면으로 조립하는 in-boundary 페이지다. 편집창 폭을
 * 최대한 확보하기 위해 버전 이력 사이드 패널은 두지 않고 편집 표면을 전폭으로 렌더한다.
 * 상태·잠금·저장·권한 판정은 소유하지 않고 이미 구현된 훅·컴포넌트에 위임한다:
 * - `useEditorScope()`: s16 `useCurrentWorkspace()`(workspaceId·role) + `useSession()`(isAdmin·
 *   userId)의 얇은 투영(Req 7.1). role 비교는 하위 컴포넌트의 RequireRole 이 소유한다.
 * - `useEditSession(documentId)`: 진입 잠금 획득 → 편집 활성 → 이탈 시 1회 자동저장/취소 생명주기.
 *
 * 렌더 결선:
 * - `status === "acquiring"`: 잠금 획득 진행 → {@link Spinner}(EditorPane 미마운트).
 * - EditLockBanner: `lockState` 를 표시(self "내가 편집 중"/other "다른 사용자가 편집 중"/error).
 *   강제 해제 노출·호출은 배너 내부 s16 게이팅(RequireRole OWNER + useForceUnlock)이 소유하며,
 *   여기서는 scope.role·isAdmin·session.retryAcquire(재획득)만 주입한다.
 * - 편집 활성(`session.document` 존재): EditorPane(세션 결선)을 전폭으로 마운트한다. 콘텐츠
 *   없이 편집 인스턴스를 만들지 않으므로 document 확보 시에만 마운트한다.
 * - "읽기로 돌아가기" back affordance: 타인 잠금(other) 등에서 읽기 화면으로 복귀하는 수동
 *   경로(Req 2.2). `useNavigate` 로 문서 메인(`/documents`)으로 복귀한다.
 * - 취소 자동 복귀: 취소 성공은 세션을 `released` 로 확정하며(useEditSession), 조립부가 그
 *   신호를 이펙트로 소비해 읽기 화면으로 자동 전이한다(Req 4.2). 훅은 상태로 표면화만 하고
 *   라우터에 결합되지 않으며, 화면 전이는 이 페이지가 소유한다.
 *
 * 경계: viewer 는 편집에 도달하지 않으며(진입점 게이팅은 s19, 서버 403 이 최종 경계) 이 페이지는
 * 로컬 role 게이트를 재구현하지 않는다(Req 1.5·7.2·7.8). 401 은 s16 전역 인터셉터가 처리하므로
 * 여기서 특별 취급하지 않는다(Req 7.4). 오류는 하위 컴포넌트가 `ApiError` 를 그대로 표면화한다
 * (Req 7.3). 다른 feature(`@/features/document`·`@/features/workspace`)를 import 하지 않는다
 * (Req 7.5). 예외로 `@/features/attachment` 배럴은 편집 표면이 업로드 브리지·첨부 렌더러를
 * 소비하는 **인가된 소비 seam** 이며(s27 D2), 이 단방향 소비에 한해 허용된다 — document·
 * workspace 는 여전히 비의존이다.
 *
 * s21 첨부 결선(s27): 라우트 `:id` 를 브리지용 `uploadDocumentId`(number|null 정규화, R4.3)로
 * 파생하고, 편집 권한 `canUpload` 를 s16 `hasWorkspaceRole`(minimum: MEMBER) 단일 경로로만
 * 도출한다(자체 role 비교 금지, R4.5). `useEditorUploadBridge` 는 렌더 트리 안에서 무조건
 * 호출하고(hook 규칙) `buildAttachmentRenderers()` 는 `useMemo([])` 로 안정화해 EditorWrapper
 * effect 재실행을 막는다. 게이팅 실판정은 브리지 내부 `isEnabled(canUpload && documentId!==null)`
 * 이 소유하며 조립부는 두 입력의 올바른 주입만 책임진다(R4.1·4.2·4.3).
 *
 * Requirements: 1.1(진입·세션 결선), 1.5(viewer 미도달), 7.1(WS·세션 스코프 주입), 7.2(권한
 *   게이팅 위임), 7.3(ApiError 표면화 위임), 7.4(401 전역 위임), 7.5(다른 feature 비의존·s16
 *   래퍼 단일), 7.6(보호 라우트 등록), 7.8(클라이언트 게이팅은 보안 경계 아님).
 */

import type { ReactElement } from "react";
import { useCallback, useEffect, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Spinner } from "@/shared/ui";
import { hasWorkspaceRole } from "@/shared/auth/permissions";
import { Role } from "@/shared/auth/roles";
import { useEditorUploadBridge, buildAttachmentRenderers } from "@/features/attachment";

import { useEditorScope } from "../hooks/useEditorScope";
import { useEditSession } from "../hooks/useEditSession";
import { EditorPane } from "../components/EditorPane";
import { EditLockBanner } from "../components/EditLockBanner";

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

  // s21 업로드 브리지 결선(s27). 세션·배너용 `documentId`(number)는 유지하고, 브리지용
  // `uploadDocumentId` 만 별도로 정규화한다: 비수치 `:id` → NaN → null 로 접어 브리지가
  // documentId 미확보를 no-op 으로 처리하게 한다(R4.3).
  const uploadDocumentId = Number.isNaN(documentId) ? null : documentId;
  // 편집 권한 게이팅은 s16 공통 유틸 단일 경로로만 도출한다 — 자체 role 비교를 흩뿌리지
  // 않는다(R4.1·4.2·4.5). admin override·role null→false 판정은 hasWorkspaceRole 이 소유.
  const canUpload = hasWorkspaceRole({
    currentRole: scope.role,
    isAdmin: scope.isAdmin,
    minimum: Role.MEMBER,
  });
  // 브리지 훅은 렌더 트리 안에서 무조건 호출한다(hook 규칙) — session.document 유무와 무관.
  const bridge = useEditorUploadBridge({ documentId: uploadDocumentId, canUpload });
  // 렌더러 팩토리는 순수하므로 마운트당 1회로 안정화해 EditorWrapper effect 재실행을 막는다.
  const renderers = useMemo(() => buildAttachmentRenderers(), []);

  const goToReading = useCallback(() => {
    navigate(READING_PATH);
  }, [navigate]);

  // 취소 성공(POST /cancel 204)은 세션을 `released` 로 확정하며(useEditSession) 그 자체가
  // 읽기 복귀 신호다(Req 4.2·design §편집 취소). 조립부가 이 신호를 소비해 읽기 화면으로
  // 전이한다 — 훅은 라우터에 결합되지 않고 상태로 표면화만 하고, 화면 전이는 페이지가 소유한다.
  useEffect(() => {
    if (session.status === "released") {
      goToReading();
    }
  }, [session.status, goToReading]);

  return (
    <section
      aria-labelledby="document-edit-heading"
      className="flex min-h-0 flex-1 flex-col gap-6"
    >
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

          {/* 잠금 보유(self)로 초기 콘텐츠가 확보된 경우에만 편집 표면을 마운트한다.
              편집창 폭 확보를 위해 버전 이력 사이드 패널은 표시하지 않고 전폭으로 렌더한다. */}
          {session.document !== null ? (
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              <EditorPane
                session={session}
                onImagePaste={bridge.onImagePaste}
                onFileDrop={bridge.onFileDrop}
                renderers={renderers}
                onEditorReady={bridge.onReady}
              />
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
