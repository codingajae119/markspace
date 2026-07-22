/**
 * DocumentToolbar — 생성·이름변경 조작 툴바 (design.md §화면 컴포넌트 DocumentToolbar).
 *
 * 생성·이름변경 컨트롤을 `<RequireRole minimum={MEMBER} currentRole=...>` 단일 게이트로
 * 감싸 비멤버(읽기 전용)에게 미노출한다. **게이팅은 RequireRole 단일 경로**이며(Req 9.2), 여기서
 * 별도 role 비교를 하지 않는다 — admin override(세션 is_admin)는 RequireRole 내부가 소유한다.
 * 조작 자체는 주입된 `useDocumentMutations` 결과에 위임하고(낙관 반영·복원·오류 표면화는 훅 책임),
 * 이 컴포넌트는 입력 수집·오류 표시만 담당한다.
 *
 * - 생성(Req 3.1): 제목 입력 + "새 문서"(루트) / "하위 문서 추가"(선택 문서의 자식) →
 *   `create({ title, parentId })`. 제목은 trim, 공백이면 미제출(서버도 422로 방어).
 * - 이름변경(Req 4.1): 선택 문서가 있을 때만 활성. `selectedTitle` 프리필 입력 →
 *   `rename(selectedId, newTitle)`.
 * - 삭제(Req 5.1): 이 툴바가 아니라 `DocumentViewer` 헤더(편집 버튼 옆)가 소유한다 — 삭제 버튼과
 *   확인 모달은 뷰어에 있고, 여기서는 다루지 않는다.
 * - 오류(Req 9.4 소비): create/rename/삭제가 공유하는 `mutations.state.error` 는 설정 판넬 개폐와
 *   무관하게 보이도록 상위 페이지가 단일 sink 로 표면화한다(여기서 표시하지 않는다).
 *
 * Requirements: 3.1(생성), 3.6·4.5·9.2(RequireRole 단일 게이트), 4.1(이름변경).
 */

import { useEffect, useState } from "react";
import type { ReactElement } from "react";

import { Role } from "@/shared/auth/roles";
import { RequireRole } from "@/shared/auth/RequireRole";
import { Button } from "@/shared/ui";
import type { useDocumentMutations } from "../hooks/useDocumentMutations";

export interface DocumentToolbarProps {
  /** 변이 오케스트레이션(생성·이름변경·삭제 + 상태). 주입된 의존을 그대로 소비한다. */
  mutations: ReturnType<typeof useDocumentMutations>;
  /** RequireRole 게이팅용 현재 WS role(useDocumentScope().role 주입). 비멤버·미확정이면 null. */
  currentRole: Role | null;
  /** 현재 선택 문서 id(이름변경·삭제 대상, 하위 생성 부모). 없으면 null. */
  selectedId: number | null;
  /** 선택 문서 현재 제목(이름변경 프리필·삭제 확인 문구). 없으면 null. */
  selectedTitle: string | null;
}

/**
 * 생성·이름변경 툴바. 컨트롤 전체를 RequireRole(minimum=MEMBER) 단일 게이트로 감싼다
 * (비멤버 → 빈 툴바). admin override 는 RequireRole 내부가 처리하므로 여기서 role 비교 없음.
 */
export function DocumentToolbar({
  mutations,
  currentRole,
  selectedId,
  selectedTitle,
}: DocumentToolbarProps): ReactElement {
  const [createTitle, setCreateTitle] = useState("");
  const [renameTitle, setRenameTitle] = useState(selectedTitle ?? "");

  // 선택 문서가 바뀌면 이름변경 입력을 새 제목으로 재프리필한다(서버 제목 기준).
  useEffect(() => {
    setRenameTitle(selectedTitle ?? "");
  }, [selectedId, selectedTitle]);

  const pending = mutations.state.pending;
  const hasSelection = selectedId !== null;

  const submitCreate = (parentId: number | null): void => {
    const title = createTitle.trim();
    if (title.length === 0) {
      // 클라이언트 가드: 빈 제목 미제출(서버도 422로 방어).
      return;
    }
    void mutations.create({ title, parentId });
    setCreateTitle("");
  };

  const submitRename = (): void => {
    if (selectedId === null) {
      return;
    }
    const title = renameTitle.trim();
    if (title.length === 0) {
      return;
    }
    void mutations.rename(selectedId, title);
  };

  return (
    <div className="flex flex-col gap-3">
      <RequireRole minimum={Role.MEMBER} currentRole={currentRole}>
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-sm text-slate-700">
              <span className="font-medium">새 문서 제목</span>
              <input
                type="text"
                aria-label="새 문서 제목"
                value={createTitle}
                onChange={(event) => setCreateTitle(event.target.value)}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
              />
            </label>
            <Button
              variant="primary"
              disabled={pending}
              onClick={() => submitCreate(null)}
            >
              새 문서
            </Button>
            <Button
              variant="secondary"
              disabled={pending || !hasSelection}
              onClick={() => submitCreate(selectedId)}
            >
              하위 문서 추가
            </Button>
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-sm text-slate-700">
              <span className="font-medium">문서 이름 변경</span>
              <input
                type="text"
                aria-label="문서 이름 변경"
                value={renameTitle}
                disabled={!hasSelection}
                onChange={(event) => setRenameTitle(event.target.value)}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:bg-slate-100"
              />
            </label>
            <Button
              variant="secondary"
              disabled={pending || !hasSelection}
              onClick={submitRename}
            >
              이름 변경
            </Button>
          </div>
        </div>
      </RequireRole>
    </div>
  );
}
