/**
 * DocumentToolbar — 생성·이름변경·삭제 조작 툴바 (design.md §화면 컴포넌트 DocumentToolbar).
 *
 * 생성·이름변경·삭제 컨트롤을 `<RequireRole minimum={MEMBER} currentRole=...>` 단일 게이트로
 * 감싸 비멤버(읽기 전용)에게 미노출한다. **게이팅은 RequireRole 단일 경로**이며(Req 9.2), 여기서
 * 별도 role 비교를 하지 않는다 — admin override(세션 is_admin)는 RequireRole 내부가 소유한다.
 * 조작 자체는 주입된 `useDocumentMutations` 결과에 위임하고(낙관 반영·복원·오류 표면화는 훅 책임),
 * 이 컴포넌트는 입력 수집·확인 UX·오류 표시만 담당한다.
 *
 * - 생성(Req 3.1): 제목 입력 + "새 문서"(루트) / "하위 문서 추가"(선택 문서의 자식) →
 *   `create({ title, parentId })`. 제목은 trim, 공백이면 미제출(서버도 422로 방어).
 * - 이름변경(Req 4.1): 선택 문서가 있을 때만 활성. `selectedTitle` 프리필 입력 →
 *   `rename(selectedId, newTitle)`.
 * - 삭제(Req 5.1): 선택 문서가 있을 때만 활성. `ConfirmDialog`(irreversible=false, 휴지통행이라
 *   복구 가능) 확인 시 `remove(selectedId)`. 문서·하위 묶음이 함께 휴지통으로 이동함을 안내만 하고
 *   묶음 계산은 하지 않는다(서버 소유).
 * - 오류(Req 9.4 소비): `mutations.state.error`(raw ApiError)를 `ErrorMessage` 로 표면화.
 *
 * Requirements: 3.1(생성), 3.6·4.5·5.6·9.2(RequireRole 단일 게이트), 4.1(이름변경), 5.1(삭제).
 */

import { useEffect, useState } from "react";
import type { ReactElement } from "react";

import { Role } from "@/shared/auth/roles";
import { RequireRole } from "@/shared/auth/RequireRole";
import { Button, ErrorMessage } from "@/shared/ui";
import type { useDocumentMutations } from "../hooks/useDocumentMutations";
import { ConfirmDialog } from "./ConfirmDialog";

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
 * 생성·이름변경·삭제 툴바. 컨트롤 전체를 RequireRole(minimum=MEMBER) 단일 게이트로 감싼다
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
  const [confirmOpen, setConfirmOpen] = useState(false);

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

  const confirmDelete = (): void => {
    if (selectedId !== null) {
      void mutations.remove(selectedId);
    }
    setConfirmOpen(false);
  };

  const deleteMessage = hasSelection
    ? `"${selectedTitle ?? "이 문서"}" 문서와 하위 문서 묶음이 함께 휴지통으로 이동합니다. 휴지통에서 복구할 수 있습니다.`
    : "선택한 문서와 하위 문서 묶음이 함께 휴지통으로 이동합니다.";

  return (
    <div className="flex flex-col gap-3">
      <RequireRole minimum={Role.MEMBER} currentRole={currentRole}>
        <div className="flex flex-col gap-3">
          <ErrorMessage error={mutations.state.error} />

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
            <Button
              variant="secondary"
              disabled={pending || !hasSelection}
              onClick={() => setConfirmOpen(true)}
              className="border-red-300 text-red-700 hover:bg-red-50 focus-visible:ring-red-400"
            >
              삭제
            </Button>
          </div>
        </div>
      </RequireRole>

      <ConfirmDialog
        open={confirmOpen}
        irreversible={false}
        title="문서 삭제"
        message={deleteMessage}
        confirmLabel="휴지통으로 이동"
        cancelLabel="취소"
        onConfirm={confirmDelete}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
