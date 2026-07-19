/**
 * DocumentWorkspacePage — 문서 메인 화면 조립부
 * (design.md §화면 컴포넌트 ~604-606; Req 7.1, 9.1, 9.5, 9.6).
 *
 * 현재 워크스페이스의 문서 트리·브레드크럼·상세 뷰어·조작 툴바를 하나의 화면으로 조립하는
 * in-boundary 페이지다. 상태·변이·권한 판정은 소유하지 않고 이미 구현된 훅·컴포넌트에 위임한다:
 * - `useDocumentScope()`: s16 앰비언트에서 현재 WS 스코프(status·workspaceId·role·isAdmin)를 투영.
 * - `useDocumentTree()`: 현재 WS 의 활성 문서를 로드해 트리·선택·조상·낙관 반영 seam 을 노출.
 * - `useDocumentMutations(tree, workspaceId)`: 생성·이름변경·삭제·이동 오케스트레이션.
 * - `hasWorkspaceRole({ currentRole, isAdmin, minimum: EDITOR })`: 편집 가능(canEdit) 판정(순수
 *   함수, admin override 포함). 실제 강제는 서버가 소유하며 여기선 노출 편의만 결정한다.
 *
 * 현재 WS 없음(Req 9.1): `scope.workspaceId === null` 이면 트리 대신 워크스페이스 선택 안내를
 * 표시한다(훅은 방어적으로 빈 트리로 수렴하지만 화면은 명시적 안내를 제공). 401 은 apiClient 의
 * 전역 인터셉터가 처리하므로 여기서 특별 취급하지 않는다(Req 9.5).
 *
 * 툴바는 RequireRole(EDITOR) 단일 게이트를 내부 소유하므로(DocumentToolbar) 여기서 role 을 다시
 * 비교하지 않고 `currentRole` 만 주입한다. `canEdit` 는 트리 DnD·뷰어 편집 seam 노출에 쓴다.
 *
 * Requirements: 7.1(트리·상세 조립), 9.1(현재 WS 스코프 단일 바인딩·안내), 9.5(전역 401 위임),
 *   9.6(role 기반 조작 컨트롤 노출).
 */

import type { ReactElement } from "react";

import { Role } from "@/shared/auth/roles";
import { hasWorkspaceRole } from "@/shared/auth/permissions";
import { EmptyState, Spinner, ErrorMessage } from "@/shared/ui";

import { useDocumentScope } from "../hooks/useDocumentScope";
import { useDocumentTree } from "../hooks/useDocumentTree";
import { useDocumentMutations } from "../hooks/useDocumentMutations";
import { DocumentToolbar } from "../components/DocumentToolbar";
import { DocumentTree } from "../components/DocumentTree";
import { Breadcrumb } from "../components/Breadcrumb";
import { DocumentViewer } from "../components/DocumentViewer";

/** 문서 메인 화면. 현재 WS 스코프에 트리·브레드크럼·뷰어·툴바를 조립한다. */
export function DocumentWorkspacePage(): ReactElement {
  const scope = useDocumentScope();
  const tree = useDocumentTree();
  const mutations = useDocumentMutations(tree, scope.workspaceId ?? "");

  const canEdit = hasWorkspaceRole({
    currentRole: scope.role,
    isAdmin: scope.isAdmin,
    minimum: Role.EDITOR,
  });

  const selectedTitle =
    tree.selectedId !== null
      ? tree.nodeById.get(tree.selectedId)?.doc.title ?? null
      : null;

  // 현재 WS 없음(Req 9.1): 본문 전체를 단락한다. 툴바·트리·뷰어를 렌더하지 않아
  // admin(RequireRole 우회)이라도 워크스페이스 없이는 생성 컨트롤이 노출되지 않는다.
  if (scope.workspaceId === null) {
    return (
      <section aria-labelledby="document-workspace-heading" className="flex flex-col gap-6">
        <header>
          <h1 id="document-workspace-heading" className="text-lg font-semibold text-slate-900">
            문서
          </h1>
        </header>
        <EmptyState
          title="워크스페이스를 선택하세요"
          message="문서를 보려면 먼저 워크스페이스를 선택하세요."
        />
      </section>
    );
  }

  return (
    <section aria-labelledby="document-workspace-heading" className="flex flex-col gap-6">
      <header>
        <h1 id="document-workspace-heading" className="text-lg font-semibold text-slate-900">
          문서
        </h1>
      </header>

      <DocumentToolbar
        mutations={mutations}
        currentRole={scope.role}
        selectedId={tree.selectedId}
        selectedTitle={selectedTitle}
      />

      <div className="flex flex-col gap-6 md:flex-row">
        <aside className="md:w-72 md:shrink-0">
          {/* 트리 로드 상태를 트래시 페인과 동일하게 표면화한다(Req 1.5·1.6). */}
          {tree.status === "loading" ? (
            <Spinner />
          ) : tree.status === "error" ? (
            <ErrorMessage error={tree.error} />
          ) : tree.roots.length === 0 ? (
            // 빈 워크스페이스: 트리 목록만 안내로 대체한다(툴바는 위에서 유지, Req 1.6).
            <EmptyState
              title="이 워크스페이스에 문서가 없습니다"
              message="위 툴바에서 첫 문서를 만들어 시작하세요."
            />
          ) : (
            <DocumentTree
              tree={tree}
              canEdit={canEdit}
              onMove={(dragId, drop) => {
                void mutations.move(dragId, drop);
              }}
            />
          )}
        </aside>

        <div className="min-w-0 flex-1">
          <Breadcrumb tree={tree} />
          {tree.selectedId !== null ? (
            <DocumentViewer documentId={tree.selectedId} canEdit={canEdit} />
          ) : (
            <EmptyState
              title="문서를 선택하세요"
              message="왼쪽 트리에서 문서를 선택하면 내용이 표시됩니다."
            />
          )}
        </div>
      </div>
    </section>
  );
}
