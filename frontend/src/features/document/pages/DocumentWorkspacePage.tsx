/**
 * DocumentWorkspacePage — 문서 메인 화면 조립부
 * (design.md §화면 컴포넌트 ~604-606; Req 7.1, 9.1, 9.5, 9.6).
 *
 * 현재 워크스페이스의 문서 트리·브레드크럼·상세 뷰어·조작 툴바를 하나의 화면으로 조립하는
 * in-boundary 페이지다. 상태·변이·권한 판정은 소유하지 않고 이미 구현된 훅·컴포넌트에 위임한다:
 * - `useDocumentScope()`: s16 앰비언트에서 현재 WS 스코프(status·workspaceId·role·isAdmin)를 투영.
 * - `useDocumentTree()`: 현재 WS 의 활성 문서를 로드해 트리·선택·조상·낙관 반영 seam 을 노출.
 * - `useDocumentMutations(tree, workspaceId)`: 생성·이름변경·삭제·이동 오케스트레이션.
 * - `hasWorkspaceRole({ currentRole, isAdmin, minimum: MEMBER })`: 편집 가능(canEdit) 판정(순수
 *   함수, admin override 포함). 실제 강제는 서버가 소유하며 여기선 노출 편의만 결정한다.
 *
 * 현재 WS 없음(Req 9.1): `scope.workspaceId === null` 이면 트리 대신 워크스페이스 선택 안내를
 * 표시한다(훅은 방어적으로 빈 트리로 수렴하지만 화면은 명시적 안내를 제공). 401 은 apiClient 의
 * 전역 인터셉터가 처리하므로 여기서 특별 취급하지 않는다(Req 9.5).
 *
 * 툴바는 RequireRole(MEMBER) 단일 게이트를 내부 소유하므로(DocumentToolbar) 여기서 role 을 다시
 * 비교하지 않고 `currentRole` 만 주입한다. `canEdit` 는 트리 DnD·뷰어 편집 seam 노출에 쓴다.
 *
 * 단일 컨트롤 행: 트리 표시 토글 · 생성/이름변경 입력 · 편집/삭제를 상단 `DocumentToolbar` 한 행에
 * 합쳐 소유한다. 트리 토글 상태(`treeVisible`)는 서버·URL 과 무관한 순수 화면 표시 상태이므로 조립부가
 * 직접 보유하고 seam(`onToggleTree`)으로 툴바에 주입한다. 숨김 시 `<aside>` 를 렌더에서 제외하면 남은
 * `flex-1` 뷰어가 전폭을 차지한다(토글은 권한과 무관하게 모든 사용자가 사용 가능). 편집·삭제는
 * `canEdit`(admin override 포함) + 선택 문서 존재 시에만 툴바가 우측 정렬로 노출하며, 편집 진입(navigate)·
 * 삭제 변이(remove) seam 을 페이지가 배선한다.
 *
 * 문서 목록 패널의 두 모드(활성 문서 ↔ 휴지통): 같은 `<aside>` 자리에서 `PanelModeTabs` 로 전환한다.
 * 휴지통은 member+ 전용이므로 뷰어에게는 탭 자체를 노출하지 않고, 권한이 사라진 경우까지 대비해
 * effect 대신 파생값(`trashMode = canEdit && panelMode === "trash"`)으로 모드를 강제 수렴시킨다.
 * 목록은 휴지통 모드에서만 로드한다 — `useTrash` 가 빈 workspaceId 를 API 호출 없이 빈 목록으로
 * 수렴시키는 방어 경로를 이용해, 조건부 훅 호출 없이 지연 로드를 얻는다.
 *
 * 휴지통 선택은 **2단**이다: 행 클릭이 `{bundleId, docId}` 를 함께 올려 뷰어는 클릭한 그 문서를
 * (`GET /documents/{id}` 가 상태로 필터하지 않아 삭제 문서도 조회된다) 읽기 전용으로 렌더하고,
 * 툴바의 복구·완전삭제는 항상 **묶음**을 대상으로 한다(`restoreBundle`/`purgeBundle` 계약). 선택
 * 묶음이 재조회 후 목록에서 사라지면 툴바 버튼과 뷰어가 함께 비워진다. 복구 성공 시에는 문서 모드로
 * 자동 복귀해 복구된 루트를 선택·가시화한다(신규 생성 시 조상을 펼치는 것과 동일 원칙).
 *
 * 변이 오류 단일 sink: 생성·이름변경·삭제가 공유하는 `mutations.state.error` 를 헤더 바로 아래에
 * 항상 노출되는 `ErrorMessage` 로 표면화한다(컨트롤 행 개폐와 무관하게 오류가 보이도록 단일화).
 *
 * Requirements: 7.1(트리·상세 조립), 9.1(현재 WS 스코프 단일 바인딩·안내), 9.5(전역 401 위임),
 *   9.6(role 기반 조작 컨트롤 노출).
 */

import type { ReactElement } from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Role } from "@/shared/auth/roles";
import { hasWorkspaceRole } from "@/shared/auth/permissions";
import { EmptyState, Spinner, ErrorMessage } from "@/shared/ui";

import { useDocumentScope } from "../hooks/useDocumentScope";
import { useDocumentTree } from "../hooks/useDocumentTree";
import { useDocumentMutations } from "../hooks/useDocumentMutations";
import { useTrash } from "../hooks/useTrash";
import { DocumentToolbar } from "../components/DocumentToolbar";
import { DocumentTree } from "../components/DocumentTree";
import { PanelModeTabs, type PanelMode } from "../components/PanelModeTabs";
import { TrashPanel } from "../components/TrashPanel";
import { Breadcrumb } from "../components/Breadcrumb";
import { DocumentViewer } from "../components/DocumentViewer";

// 편집 화면 진입 경로 빌더(s20 소유 `/documents/:id/edit`). 두 feature 는 서로 직접 import 하지
// 않으므로(Req 7.5, DocumentEditPage 의 READING_PATH 대칭) editor 의 DOCUMENT_EDIT_PATH 를
// import 하지 않고 경로 문자열만 로컬에서 조립한다.
function buildDocumentEditPath(documentId: number): string {
  return `/documents/${documentId}/edit`;
}

/** 문서 메인 화면. 현재 WS 스코프에 트리·브레드크럼·뷰어·툴바를 조립한다. */
export function DocumentWorkspacePage(): ReactElement {
  const scope = useDocumentScope();
  const tree = useDocumentTree();
  const mutations = useDocumentMutations(tree, scope.workspaceId ?? "");
  const navigate = useNavigate();

  // 읽기 화면 왼쪽 문서 트리 패널 노출 여부(기본 표시). 순수 화면 표시 상태.
  const [treeVisible, setTreeVisible] = useState(true);
  // 패널이 표시하는 대상(활성 문서 ↔ 휴지통). 서버·URL 과 무관한 순수 화면 표시 상태.
  const [panelMode, setPanelMode] = useState<PanelMode>("active");
  // 휴지통 2단 선택: 뷰어가 표시할 문서(docId) + 복구·완전삭제 대상 묶음(bundleId).
  const [trashSelection, setTrashSelection] = useState<{
    bundleId: number;
    docId: number;
  } | null>(null);

  const canEdit = hasWorkspaceRole({
    currentRole: scope.role,
    isAdmin: scope.isAdmin,
    minimum: Role.MEMBER,
  });

  // 휴지통은 member+ 전용(서버 권한과 동일 기준). 뷰어에게는 모드 탭 자체를
  // 노출하지 않으므로, 권한이 사라진 경우까지 대비해 effect 대신 파생값으로 모드를 강제 수렴시킨다.
  const trashMode = canEdit && panelMode === "trash";

  // 휴지통 모드일 때만 목록을 로드한다. useTrash 는 빈 workspaceId 를 API 호출 없이 빈 목록으로
  // 수렴시키므로(방어 경로), 이 자리에서 조건부 훅 호출 없이 지연 로드를 얻는다.
  const trash = useTrash(trashMode ? scope.workspaceId ?? "" : "");

  // 선택 묶음이 목록에서 사라졌으면(복구·완전삭제·만료 후 재조회) 툴바 버튼과 뷰어를 함께 비운다.
  const selectedBundle =
    trashSelection !== null
      ? trash.bundles.find((b) => b.bundle_id === trashSelection.bundleId) ?? null
      : null;
  const trashViewDocId = selectedBundle !== null ? trashSelection!.docId : null;

  /** 묶음 전체 복구 → 문서 모드로 자동 복귀하고 복구된 루트를 선택·가시화한다. */
  const handleRestore = async (): Promise<void> => {
    if (selectedBundle === null) {
      return;
    }
    const rootId = selectedBundle.root_document_id;
    const ok = await trash.restore(selectedBundle.bundle_id);
    if (!ok) {
      // 실패 오류는 useTrash 가 목록과 함께 표면화한다(휴지통에 머문다).
      return;
    }
    setTrashSelection(null);
    setPanelMode("active");
    // 복구 결과를 눈으로 확인시킨다: 재조회 → 루트 선택 → 조상 펼침(신규 생성과 동일 원칙).
    await tree.reload();
    tree.select(rootId);
    tree.revealAncestors(rootId);
  };

  /** 묶음 완전삭제(비가역 확인은 툴바 소유). 성공/실패 모두 선택을 비운다. */
  const handlePurge = async (): Promise<void> => {
    if (selectedBundle === null) {
      return;
    }
    await trash.purge(selectedBundle.bundle_id);
    setTrashSelection(null);
  };

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

      {/* 변이 오류 단일 sink: create/rename/삭제가 공유하는 오류를 항상 노출. */}
      <ErrorMessage error={mutations.state.error} />

      {/* 단일 컨트롤 행: 트리 토글 + 생성/이름변경(RequireRole) + 편집/삭제(canEdit, 우측 정렬). */}
      <DocumentToolbar
        mutations={mutations}
        currentRole={scope.role}
        selectedId={tree.selectedId}
        selectedTitle={selectedTitle}
        treeVisible={treeVisible}
        onToggleTree={() => setTreeVisible((visible) => !visible)}
        canEdit={canEdit}
        onEnterEdit={(documentId) => {
          navigate(buildDocumentEditPath(documentId));
        }}
        onDelete={(documentId) => {
          void mutations.remove(documentId);
        }}
        trashMode={trashMode}
        canUseTrash={canEdit}
        trashSelection={
          selectedBundle !== null
            ? {
                rootTitle: selectedBundle.root_title,
                memberCount: selectedBundle.member_count,
              }
            : null
        }
        onRestore={() => {
          void handleRestore();
        }}
        onPurge={() => {
          void handlePurge();
        }}
      />

      <div className="flex flex-col gap-6 md:flex-row">
        {treeVisible ? (
          <aside
            id="document-tree-panel"
            // 휴지통 모드는 배경색으로도 구분하되(요구), 모드 탭 라벨이라는 텍스트 신호와
            // 항상 함께 쓴다 — 색상 단독 신호는 색각 이상·고대비 모드에서 소실된다.
            className={
              "md:w-72 md:shrink-0 " +
              (trashMode ? "rounded-lg bg-slate-100 p-2" : "")
            }
          >
            {/* 모드 탭은 member+ 에게만 노출한다(뷰어는 활성 문서 목록만 본다). */}
            {canEdit ? (
              <PanelModeTabs
                mode={trashMode ? "trash" : "active"}
                onChange={(next) => {
                  setPanelMode(next);
                  setTrashSelection(null);
                }}
                trashCount={trashMode ? trash.total : null}
              />
            ) : null}

            {trashMode ? (
              <TrashPanel
                trash={trash}
                selectedBundleId={trashSelection?.bundleId ?? null}
                selectedDocId={trashSelection?.docId ?? null}
                onSelect={(bundleId, docId) =>
                  setTrashSelection({ bundleId, docId })
                }
              />
            ) : /* 트리 로드 상태를 트래시 페인과 동일하게 표면화한다(Req 1.5·1.6). */
            tree.status === "loading" ? (
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
        ) : null}

        <div className="min-w-0 flex-1">
          {trashMode ? (
            /* 휴지통 모드: 브레드크럼(활성 트리 파생)은 삭제 문서에 의미가 없으므로 렌더하지 않고,
               읽기 전용 배너로 대체한다. 본문은 동일한 DocumentViewer 로 렌더한다 —
               `GET /documents/{id}` 가 상태로 필터하지 않아 삭제 문서도 조회된다. */
            trashViewDocId !== null ? (
              <>
                <p className="rounded-md bg-slate-100 px-3 py-2 text-sm text-slate-600">
                  휴지통에 있는 문서입니다. 읽기 전용이며, 복구하면 편집할 수 있습니다.
                </p>
                <DocumentViewer documentId={trashViewDocId} />
              </>
            ) : (
              <EmptyState
                title="휴지통 문서를 선택하세요"
                message="왼쪽 휴지통 목록에서 문서를 선택하면 내용이 표시됩니다."
              />
            )
          ) : (
            <>
              <Breadcrumb tree={tree} />
              {tree.selectedId !== null ? (
                <DocumentViewer documentId={tree.selectedId} />
              ) : (
                <EmptyState
                  title="문서를 선택하세요"
                  message="왼쪽 트리에서 문서를 선택하면 내용이 표시됩니다."
                />
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
