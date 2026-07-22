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
 * 트리 패널 표시 토글: 읽기 화면 왼쪽 문서 트리 패널의 노출 여부를 로컬 UI 상태(`treeVisible`)로
 * 소유한다. 서버·URL 과 무관한 순수 화면 표시 상태이므로 훅에 위임하지 않고 조립부가 직접 보유한다.
 * 숨김 시 `<aside>` 를 렌더에서 제외하면 남은 `flex-1` 뷰어가 전폭을 차지한다(권한과 무관하게
 * owner 를 포함한 모든 사용자가 사용 가능). 토글 버튼은 `aria-expanded`/`aria-controls` 로 aside 를
 * 가리켜 스크린리더에 의미를 전달한다.
 *
 * 변이 오류 단일 sink: 생성·이름변경·삭제가 공유하는 `mutations.state.error` 를 헤더 바로 아래에
 * 항상 노출되는 `ErrorMessage` 로 표면화한다. 삭제 버튼은 접힐 수 있는 설정 판넬이 아니라 항상 보이는
 * 뷰어 헤더가 소유하므로, 오류도 판넬 개폐와 무관하게 보여야 하기 때문이다 — 따라서 오류 표시를
 * 툴바에서 페이지로 끌어올려 단일화한다.
 *
 * 문서 설정 판넬 표시 토글: 상단 `DocumentToolbar`(문서·하위 문서 생성, 제목 변경 컨트롤)의
 * 노출 여부를 트리 토글과 동일한 성격의 로컬 UI 상태(`settingsVisible`)로 소유한다. 판넬 자체는
 * `RequireRole(MEMBER)` 게이트를 내부 소유하므로 비멤버에겐 빈 판넬이다 — 따라서 토글 버튼도
 * `canEdit`(admin override 포함) 로 게이팅해 편집 권한이 있는 사용자(owner 포함)에게만 노출한다.
 * 트리 토글과 달리 세션 시작 시 기본 숨김(`false`)이며, 사용자가 토글로 펼쳐야 판넬이 나타난다.
 * 토글은 "문서" 제목 옆의 작은 삼각형 버튼으로, 보임 상태=위쪽(▴, 접기)·숨김 상태=아래쪽(▾, 펼치기)을
 * 가리키며 방향 글리프는 aria-hidden, 의미는 aria-label 로 스크린리더에 전달한다.
 *
 * Requirements: 7.1(트리·상세 조립), 9.1(현재 WS 스코프 단일 바인딩·안내), 9.5(전역 401 위임),
 *   9.6(role 기반 조작 컨트롤 노출).
 */

import type { ReactElement } from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Role } from "@/shared/auth/roles";
import { hasWorkspaceRole } from "@/shared/auth/permissions";
import { EmptyState, Spinner, ErrorMessage, Button } from "@/shared/ui";

import { useDocumentScope } from "../hooks/useDocumentScope";
import { useDocumentTree } from "../hooks/useDocumentTree";
import { useDocumentMutations } from "../hooks/useDocumentMutations";
import { DocumentToolbar } from "../components/DocumentToolbar";
import { DocumentTree } from "../components/DocumentTree";
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
  // 상단 문서 설정 판넬(생성·이름변경·삭제 툴바) 노출 여부(기본 숨김). 순수 화면 표시 상태.
  const [settingsVisible, setSettingsVisible] = useState(false);

  const canEdit = hasWorkspaceRole({
    currentRole: scope.role,
    isAdmin: scope.isAdmin,
    minimum: Role.MEMBER,
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
      <header className="flex items-center gap-2">
        <h1 id="document-workspace-heading" className="text-lg font-semibold text-slate-900">
          문서
        </h1>
        {/* 문서 설정 판넬 토글: 편집 권한이 있는 사용자(owner 포함)에게만 노출한다. 제목 옆
            작은 삼각형 버튼으로, 보임 상태=위쪽(▴, 접기)·숨김 상태=아래쪽(▾, 펼치기)을 가리킨다.
            판넬 내부는 RequireRole 이 다시 게이팅하므로 이 버튼은 노출 편의만 담당한다. */}
        {canEdit ? (
          <button
            type="button"
            onClick={() => setSettingsVisible((visible) => !visible)}
            aria-expanded={settingsVisible}
            aria-controls="document-settings-panel"
            aria-label={settingsVisible ? "문서 설정 숨기기" : "문서 설정 보기"}
            title={settingsVisible ? "문서 설정 숨기기" : "문서 설정 보기"}
            className="flex h-12 w-12 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
          >
            <span aria-hidden="true" className="text-4xl leading-none">
              {settingsVisible ? "▴" : "▾"}
            </span>
          </button>
        ) : null}
      </header>

      {/* 변이 오류 단일 sink: create/rename/삭제가 공유하는 오류를 판넬 개폐와 무관하게 항상 노출. */}
      <ErrorMessage error={mutations.state.error} />

      {settingsVisible ? (
        <div id="document-settings-panel">
          <DocumentToolbar
            mutations={mutations}
            currentRole={scope.role}
            selectedId={tree.selectedId}
            selectedTitle={selectedTitle}
          />
        </div>
      ) : null}

      <div>
        <Button
          variant="secondary"
          onClick={() => setTreeVisible((visible) => !visible)}
          aria-expanded={treeVisible}
          aria-controls="document-tree-panel"
        >
          {treeVisible ? "문서 목록 숨기기" : "문서 목록 보기"}
        </Button>
      </div>

      <div className="flex flex-col gap-6 md:flex-row">
        {treeVisible ? (
          <aside id="document-tree-panel" className="md:w-72 md:shrink-0">
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
        ) : null}

        <div className="min-w-0 flex-1">
          <Breadcrumb tree={tree} />
          {tree.selectedId !== null ? (
            <DocumentViewer
              documentId={tree.selectedId}
              canEdit={canEdit}
              onEnterEdit={(documentId) => {
                navigate(buildDocumentEditPath(documentId));
              }}
              onDelete={(documentId) => {
                void mutations.remove(documentId);
              }}
            />
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
