import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";

import { Role } from "@/shared/auth/roles";
import { ApiError } from "@/shared/api/errors";
import { useSession } from "@/app/session/useSession";
import type { useDocumentMutations } from "../hooks/useDocumentMutations";
import { DocumentToolbar } from "./DocumentToolbar";

// DocumentToolbar 은 트리 토글 · 생성/이름변경 · 편집/삭제를 한 컨트롤 행으로 소유한다.
// 생성·이름변경은 RequireRole(minimum=MEMBER) 단일 게이트로 비멤버(null)에게 미노출한다
// (Req 3.6·4.5·9.2). RequireRole 은 isAdmin 을 useSession() 에서만 취득하므로(admin override)
// 세션 훅을 모킹한다. mutations 는 주입된 의존을 그대로 소비하는 목으로 대체해 호출 인자를 관찰한다.
// 세 조작(이름 바꾸기·새문서·하위문서 추가)은 단일 입력("문서 이름")을 공유하며, 편집·삭제는
// canEdit + 선택 존재 시에만 오른쪽 정렬로 노출한다.
// Requirements: 3.1, 3.6, 4.1, 4.5, 5.1, 7.4, 7.5, 9.2

vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));

// 공유 클러스터(우측) 는 sharing 배럴(@/features/sharing)에서 교차-feature import 로 결선된다
// (DocumentViewer → @/features/attachment 와 동일 선례). 게이팅 단언을 도메인 로직과 분리하기
// 위해 배럴을 목으로 대체해, 마운트 여부와 전달 prop(documentId·documentStatus)만 관측한다.
vi.mock("@/features/sharing", () => ({
  DocumentShareControl: (props: { documentId: number; documentStatus: string }) => (
    <div
      data-testid="share-control"
      data-doc-id={props.documentId}
      data-status={props.documentStatus}
    />
  ),
}));

const useSessionMock = useSession as unknown as Mock;

/** useSession 이 non-admin authenticated 를 반환하도록 설정(admin override 미적용). */
function mockNonAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useSession 이 admin authenticated 를 반환하도록 설정(INV-3 admin override). */
function mockAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 2, login_id: "root", name: "Root", email: null, is_admin: true },
    settings: null,
    refresh: vi.fn(),
  });
}

/** create/rename/remove/move·state 를 갖춘 타입 안전 mutations 목(any 미사용). */
function makeMutations(
  state: { pending: boolean; error: ApiError | null } = { pending: false, error: null },
): ReturnType<typeof useDocumentMutations> {
  return {
    create: vi.fn(),
    rename: vi.fn(),
    remove: vi.fn(),
    move: vi.fn(),
    state,
  };
}

beforeEach(() => {
  useSessionMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("DocumentToolbar — RequireRole 단일 게이트 생성·이름변경", () => {
  it("비멤버(null, 비-admin) → 생성·이름변경 컨트롤(입력·버튼) 미노출 (Req 3.6·4.5·9.2)", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={null}
        selectedId={5}
        selectedTitle="문서"
      />,
    );

    expect(screen.queryByLabelText("문서 이름")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "새문서" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "이름 바꾸기" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "하위문서 추가" })).not.toBeInTheDocument();
  });

  it("member → 단일 입력값으로 create({ title, parentId: null }) 호출 (Req 3.1)", () => {
    mockNonAdmin();
    const mutations = makeMutations();
    render(
      <DocumentToolbar
        mutations={mutations}
        currentRole={Role.MEMBER}
        selectedId={null}
        selectedTitle={null}
      />,
    );

    fireEvent.change(screen.getByLabelText("문서 이름"), {
      target: { value: "  새 노트  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "새문서" }));

    expect(vi.mocked(mutations.create)).toHaveBeenCalledWith({
      title: "새 노트",
      parentId: null,
    });
  });

  it("member → 빈 제목이면 새문서 버튼이 비활성화되어 create 되지 않는다(클라이언트 가드, Req 3.1)", () => {
    mockNonAdmin();
    const mutations = makeMutations();
    render(
      <DocumentToolbar
        mutations={mutations}
        currentRole={Role.MEMBER}
        selectedId={null}
        selectedTitle={null}
      />,
    );

    fireEvent.change(screen.getByLabelText("문서 이름"), {
      target: { value: "   " },
    });
    const createButton = screen.getByRole("button", { name: "새문서" });
    expect(createButton).toBeDisabled();
    fireEvent.click(createButton);

    expect(vi.mocked(mutations.create)).not.toHaveBeenCalled();
  });

  it("member + 선택 문서 → 하위문서 추가가 create({ title, parentId: selectedId }) 호출 (Req 3.1)", () => {
    mockNonAdmin();
    const mutations = makeMutations();
    render(
      <DocumentToolbar
        mutations={mutations}
        currentRole={Role.MEMBER}
        selectedId={7}
        selectedTitle="부모"
      />,
    );

    fireEvent.change(screen.getByLabelText("문서 이름"), {
      target: { value: "자식 노트" },
    });
    fireEvent.click(screen.getByRole("button", { name: "하위문서 추가" }));

    expect(vi.mocked(mutations.create)).toHaveBeenCalledWith({
      title: "자식 노트",
      parentId: 7,
    });
  });

  it("선택이 없으면 이름 바꾸기·하위문서 추가는 비활성화된다 (Req 4.1)", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.MEMBER}
        selectedId={null}
        selectedTitle={null}
      />,
    );

    // 입력에 값이 있어도 선택이 없으면 이름 바꾸기/하위문서 추가는 대상이 없어 비활성화.
    fireEvent.change(screen.getByLabelText("문서 이름"), {
      target: { value: "무언가" },
    });
    expect(screen.getByRole("button", { name: "이름 바꾸기" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "하위문서 추가" })).toBeDisabled();
    // 루트 새문서는 선택과 무관하게 활성.
    expect(screen.getByRole("button", { name: "새문서" })).toBeEnabled();
  });

  it("owner → 이름 바꾸기 컨트롤이 rename(selectedId, title) 호출 (Req 4.1)", () => {
    mockNonAdmin();
    const mutations = makeMutations();
    render(
      <DocumentToolbar
        mutations={mutations}
        currentRole={Role.OWNER}
        selectedId={42}
        selectedTitle="원래 제목"
      />,
    );

    // 입력은 선택 문서 제목으로 프리필된다.
    expect(screen.getByLabelText("문서 이름")).toHaveValue("원래 제목");

    fireEvent.change(screen.getByLabelText("문서 이름"), {
      target: { value: "새 제목" },
    });
    fireEvent.click(screen.getByRole("button", { name: "이름 바꾸기" }));

    expect(vi.mocked(mutations.rename)).toHaveBeenCalledWith(42, "새 제목");
  });

  it("admin 세션 + currentRole null → 생성·이름변경 노출(RequireRole admin override, Req 9.2)", () => {
    mockAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={null}
        selectedId={5}
        selectedTitle="문서"
      />,
    );

    expect(screen.getByLabelText("문서 이름")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "새문서" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "이름 바꾸기" })).toBeInTheDocument();
  });
});

describe("DocumentToolbar — 트리 토글 seam", () => {
  it("onToggleTree 주입 시 토글 버튼을 노출하고 클릭 시 호출한다(권한 무관)", () => {
    mockNonAdmin();
    const onToggleTree = vi.fn();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={null}
        selectedId={null}
        selectedTitle={null}
        treeVisible={true}
        onToggleTree={onToggleTree}
      />,
    );

    // 비멤버라도(생성 컨트롤은 숨김) 트리 토글은 노출된다.
    const toggle = screen.getByRole("button", { name: "문서 목록 숨기기" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", "document-tree-panel");
    fireEvent.click(toggle);
    expect(onToggleTree).toHaveBeenCalledTimes(1);
  });

  it("onToggleTree 미주입 시 토글 버튼을 렌더하지 않는다", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.MEMBER}
        selectedId={null}
        selectedTitle={null}
      />,
    );

    expect(screen.queryByRole("button", { name: "문서 목록 숨기기" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "문서 목록 보기" })).not.toBeInTheDocument();
  });
});

describe("DocumentToolbar — 편집·삭제 seam(canEdit + 선택 존재)", () => {
  it("canEdit=false → 편집·삭제 미노출", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.MEMBER}
        selectedId={7}
        selectedTitle="문서"
        canEdit={false}
      />,
    );

    expect(screen.queryByRole("button", { name: "편집" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "삭제" })).not.toBeInTheDocument();
  });

  it("canEdit=true 지만 선택 없음 → 편집·삭제 미노출", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.MEMBER}
        selectedId={null}
        selectedTitle={null}
        canEdit={true}
      />,
    );

    expect(screen.queryByRole("button", { name: "편집" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "삭제" })).not.toBeInTheDocument();
  });

  it("canEdit=true + 선택 → 편집 클릭 시 onEnterEdit(selectedId) 호출 (Req 7.4, 7.5)", () => {
    mockNonAdmin();
    const onEnterEdit = vi.fn<(documentId: number) => void>();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.MEMBER}
        selectedId={9}
        selectedTitle="편집 대상"
        canEdit={true}
        onEnterEdit={onEnterEdit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "편집" }));
    expect(onEnterEdit).toHaveBeenCalledWith(9);
  });

  it("삭제 → ConfirmDialog 확인 시 onDelete(selectedId) 호출 후 닫힘 (Req 5.1)", () => {
    mockNonAdmin();
    const onDelete = vi.fn<(documentId: number) => void>();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.MEMBER}
        selectedId={9}
        selectedTitle="지울 문서"
        canEdit={true}
        onDelete={onDelete}
      />,
    );

    // 초기엔 확인 모달이 없다.
    expect(screen.queryByRole("dialog")).toBeNull();

    // 삭제 클릭 → 확인 모달이 뜨고, 아직 seam 은 호출되지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "삭제" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();

    // 확인 → onDelete(selectedId) 호출 후 모달이 닫힌다(변이는 상위 페이지가 소유).
    fireEvent.click(screen.getByRole("button", { name: "휴지통으로 이동" }));
    expect(onDelete).toHaveBeenCalledWith(9);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("삭제 확인 모달에서 취소하면 onDelete 를 호출하지 않고 닫힌다 (Req 5.1)", () => {
    mockNonAdmin();
    const onDelete = vi.fn<(documentId: number) => void>();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.MEMBER}
        selectedId={4}
        selectedTitle="문서"
        canEdit={true}
        onDelete={onDelete}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "삭제" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("DocumentToolbar — 공유 클러스터 노출 게이트(canShare && shareable && active && 선택)", () => {
  it("canShare + shareable + active(비휴지통) + 선택 → 공유 컨트롤 노출(documentId=선택, status=active) (Req 3.1)", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.OWNER}
        selectedId={13}
        selectedTitle="공유 대상"
        canEdit={true}
        canShare={true}
        shareable={true}
      />,
    );

    const control = screen.getByTestId("share-control");
    expect(control).toBeInTheDocument();
    // 선택 문서 id 를 그대로 넘기고, active 문맥에서만 마운트되므로 status 는 상수 "active".
    expect(control).toHaveAttribute("data-doc-id", "13");
    expect(control).toHaveAttribute("data-status", "active");
  });

  it("canShare=false(owner 미만·비admin) → 공유 컨트롤 미노출 (Req 3.2)", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.MEMBER}
        selectedId={13}
        selectedTitle="문서"
        canEdit={true}
        canShare={false}
        shareable={true}
      />,
    );

    expect(screen.queryByTestId("share-control")).not.toBeInTheDocument();
  });

  it("shareable=false(공유 불가 워크스페이스) → 공유 컨트롤 미노출 (Req 3.3)", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.OWNER}
        selectedId={13}
        selectedTitle="문서"
        canEdit={true}
        canShare={true}
        shareable={false}
      />,
    );

    expect(screen.queryByTestId("share-control")).not.toBeInTheDocument();
  });

  it("trashMode=true(휴지통 = 비active) → 공유 컨트롤 미노출 (Req 3.4)", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.OWNER}
        selectedId={13}
        selectedTitle="문서"
        canEdit={true}
        canShare={true}
        shareable={true}
        trashMode={true}
        trashSelection={{ rootTitle: "폐기", memberCount: 1 }}
      />,
    );

    expect(screen.queryByTestId("share-control")).not.toBeInTheDocument();
  });

  it("선택 없음(hasSelection=false) → 공유 컨트롤 미노출 (Req 3.1 선택 축)", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.OWNER}
        selectedId={null}
        selectedTitle={null}
        canEdit={true}
        canShare={true}
        shareable={true}
      />,
    );

    expect(screen.queryByTestId("share-control")).not.toBeInTheDocument();
  });

  it("share 관련 prop 미주입(기본 false) → 공유 컨트롤 미노출", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.OWNER}
        selectedId={13}
        selectedTitle="문서"
        canEdit={true}
      />,
    );

    expect(screen.queryByTestId("share-control")).not.toBeInTheDocument();
  });
});
