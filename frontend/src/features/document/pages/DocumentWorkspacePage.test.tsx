import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";

import { Role } from "@/shared/auth/roles";
import { ApiError } from "@/shared/api/errors";
import type { DocumentRead } from "../types";

/**
 * DocumentWorkspacePage 조립 통합 테스트: 트리·브레드크럼·뷰어·툴바를 현재 워크스페이스 스코프에
 * 결선하는 in-boundary 페이지가 s16 앰비언트(useCurrentWorkspace/useSession)와 문서 훅을 통해
 * 조립됨을 관측한다. Toast UI Editor(뷰어 내부)와 documentApi(트리 로드·상세 조회)를 모킹해
 * jsdom 네트워크·에디터 인스턴스화를 회피하고, 조립 결과(트리 노드 렌더·선택→뷰어·editor 툴바
 * 노출)를 검증한다.
 */

// 뷰어가 EditorWrapper(read)로 Toast UI Editor 를 인스턴스화하므로 EditorWrapper.test 와 동일한
// 형태로 @toast-ui/editor 를 모킹한다(jsdom 비호환 회피).
const factorySpy = vi.fn<(options: Record<string, unknown>) => void>();
vi.mock("@toast-ui/editor", () => {
  class MockEditor {
    constructor(_options: Record<string, unknown>) {}
    getMarkdown(): string {
      return "";
    }
    insertText(_text: string): void {}
    replaceSelection(_text: string, _start?: unknown, _end?: unknown): void {}
    destroy(): void {}
    static factory(options: Record<string, unknown>): MockEditor {
      factorySpy(options);
      return new MockEditor(options);
    }
  }
  return { default: MockEditor };
});

// 트리 로드(loadAllActiveDocuments)와 상세 조회(getDocument)를 모킹한다.
const loadAllActiveDocumentsMock = vi.fn<(workspaceId: string) => Promise<DocumentRead[]>>();
const getDocumentMock = vi.fn<(id: number) => Promise<DocumentRead>>();
vi.mock("../api/documentApi", () => ({
  documentApi: {
    loadAllActiveDocuments: (workspaceId: string): Promise<DocumentRead[]> =>
      loadAllActiveDocumentsMock(workspaceId),
    getDocument: (id: number): Promise<DocumentRead> => getDocumentMock(id),
  },
}));

// s16 앰비언트 훅 모킹 — 현재 WS(id "7", ready, role MEMBER) + 인증 세션(is_admin false).
vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({
  useCurrentWorkspace: vi.fn(),
}));
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));

import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useSession } from "@/app/session/useSession";
import { DocumentWorkspacePage } from "./DocumentWorkspacePage";

const useCurrentWorkspaceMock = useCurrentWorkspace as unknown as Mock;
const useSessionMock = useSession as unknown as Mock;

/** 모든 DocumentRead 필드를 채운 fixture. */
function sampleDoc(partial: Partial<DocumentRead> = {}): DocumentRead {
  return {
    id: 11,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    workspace_id: 7,
    parent_id: null,
    title: "설계 노트",
    status: "active",
    sort_order: "1",
    current_version_id: null,
    created_by: 1,
    content: "# 본문",
    content_html: "<h1>본문</h1>",
    ...partial,
  };
}

/** 현재 WS 컨텍스트를 ready·role MEMBER 로 고정한다(canEdit=true). */
function setReadyWorkspace(): void {
  useCurrentWorkspaceMock.mockReturnValue({
    status: "ready",
    workspaces: [],
    currentWorkspace: null,
    workspaceId: "7",
    role: Role.MEMBER,
    isShareable: false,
    selectWorkspace: vi.fn(),
    refresh: vi.fn(),
  });
}

/** 현재 WS 없음(workspaceId null)으로 고정한다(Req 9.1 안내 분기). */
function setNoWorkspace(): void {
  useCurrentWorkspaceMock.mockReturnValue({
    status: "empty",
    workspaces: [],
    currentWorkspace: null,
    workspaceId: null,
    role: null,
    isShareable: false,
    selectWorkspace: vi.fn(),
    refresh: vi.fn(),
  });
}

function setAuthenticated(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
}

/** admin 세션(is_admin true) — RequireRole 우회(role 없이도 편집 컨트롤 노출 가능). */
function setAuthenticatedAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 9, login_id: "root", name: "Root", email: null, is_admin: true },
    settings: null,
    refresh: vi.fn(),
  });
}

/** 현재 라우트 경로를 노출해 네비게이션(편집 진입)을 관측하기 위한 프로브. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

/** 페이지를 라우터 컨텍스트(useNavigate 필요) 안에서 렌더한다. */
function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/documents"]}>
      <Routes>
        <Route path="/documents" element={<DocumentWorkspacePage />} />
        <Route path="/documents/:id/edit" element={<div>편집 화면</div>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  factorySpy.mockClear();
  loadAllActiveDocumentsMock.mockReset();
  getDocumentMock.mockReset();
  useCurrentWorkspaceMock.mockReset();
  useSessionMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("DocumentWorkspacePage 조립 (트리 + 브레드크럼 + 뷰어 + 툴바)", () => {
  it("현재 WS 의 활성 문서를 로드해 트리 노드를 렌더한다 (Req 7.1, 9.1)", async () => {
    setReadyWorkspace();
    setAuthenticated();
    loadAllActiveDocumentsMock.mockResolvedValue([sampleDoc()]);

    renderPage();

    // 트리는 useDocumentScope().workspaceId("7")로 로드한다.
    await waitFor(() =>
      expect(loadAllActiveDocumentsMock).toHaveBeenCalledWith("7"),
    );
    expect(await screen.findByText("설계 노트")).toBeInTheDocument();
    // 선택 전에는 상세 안내(EmptyState)를 보여준다.
    expect(screen.getByText("문서를 선택하세요")).toBeInTheDocument();
  });

  it("editor role 이면 툴바(생성 컨트롤)를 노출한다 (Req 9.6)", async () => {
    setReadyWorkspace();
    setAuthenticated();
    loadAllActiveDocumentsMock.mockResolvedValue([sampleDoc()]);

    renderPage();

    // RequireRole(MEMBER) 게이트 통과 → 생성 컨트롤(새 문서 제목 입력)이 보인다.
    expect(await screen.findByLabelText("새 문서 제목")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "새 문서" })).toBeInTheDocument();
  });

  it("트리 노드를 선택하면 상세 뷰어가 렌더된다 (Req 7.1)", async () => {
    setReadyWorkspace();
    setAuthenticated();
    loadAllActiveDocumentsMock.mockResolvedValue([sampleDoc()]);
    getDocumentMock.mockResolvedValue(sampleDoc());

    renderPage();

    const label = await screen.findByText("설계 노트");
    fireEvent.click(label);

    // 선택 → DocumentViewer 가 상세를 조회하고 read 뷰어(Viewer factory)로 렌더한다.
    await waitFor(() => expect(getDocumentMock).toHaveBeenCalledWith(11));
    await waitFor(() => expect(factorySpy).toHaveBeenCalled());
    // 안내 EmptyState 는 더 이상 표시되지 않는다.
    expect(screen.queryByText("문서를 선택하세요")).not.toBeInTheDocument();
  });

  it("editor+ 가 뷰어의 편집 버튼을 누르면 편집 화면(/documents/:id/edit)으로 이동한다 (Req 7.4, 7.5)", async () => {
    setReadyWorkspace();
    setAuthenticated();
    loadAllActiveDocumentsMock.mockResolvedValue([sampleDoc()]);
    getDocumentMock.mockResolvedValue(sampleDoc());

    renderPage();

    fireEvent.click(await screen.findByText("설계 노트"));
    // 뷰어 상세 로드 완료 후 편집 버튼이 노출된다(canEdit=true, onEnterEdit 배선).
    const editButton = await screen.findByRole("button", { name: "편집" });
    fireEvent.click(editButton);

    // onEnterEdit 배선이 navigate(/documents/11/edit)를 수행해 편집 라우트로 전이한다.
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/documents/11/edit"),
    );
    expect(screen.getByText("편집 화면")).toBeInTheDocument();
  });

  it("현재 WS 가 없으면 트리 대신 워크스페이스 선택 안내를 표시한다 (Req 9.1)", () => {
    setNoWorkspace();
    setAuthenticated();

    renderPage();

    // workspaceId null → API 미호출, 안내 문구 표시.
    expect(loadAllActiveDocumentsMock).not.toHaveBeenCalled();
    expect(screen.getByText("워크스페이스를 선택하세요")).toBeInTheDocument();
  });

  it("트리 로드 실패 시 오류를 사용자에게 표면화한다 (Req 1.5)", async () => {
    setReadyWorkspace();
    setAuthenticated();
    loadAllActiveDocumentsMock.mockRejectedValue(
      new ApiError({ status: 500, code: "internal", message: "문서를 불러오지 못했습니다." }),
    );

    renderPage();

    // status:"error" → 트리 페인이 ErrorMessage(role="alert")로 오류를 노출한다.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("문서를 불러오지 못했습니다.");
  });

  it("트리 로드 진행 중에는 로딩 인디케이터를 표시한다 (Req 1.5)", () => {
    setReadyWorkspace();
    setAuthenticated();
    // 해소되지 않는 로드로 status:"loading" 을 유지한다.
    loadAllActiveDocumentsMock.mockReturnValue(new Promise<DocumentRead[]>(() => {}));

    renderPage();

    // 트리 페인이 Spinner(role="status")를 렌더한다.
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("문서가 없는 워크스페이스는 빈 상태 안내를 표시하되 생성 툴바는 유지한다 (Req 1.6)", async () => {
    setReadyWorkspace();
    setAuthenticated();
    loadAllActiveDocumentsMock.mockResolvedValue([]);

    renderPage();

    // status:"ready" + roots [] → 빈 상태 안내.
    expect(await screen.findByText("이 워크스페이스에 문서가 없습니다")).toBeInTheDocument();
    // 빈 상태는 트리 목록만 대체하고, editor 는 첫 문서를 만들 수 있어야 한다(툴바 유지).
    expect(screen.getByLabelText("새 문서 제목")).toBeInTheDocument();
  });

  it("현재 WS 가 없으면 admin 이어도 생성 툴바를 렌더하지 않는다 (Req 9.1)", () => {
    setNoWorkspace();
    setAuthenticatedAdmin();

    renderPage();

    // workspaceId null → 본문 전체 단락, 안내만 표시.
    expect(screen.getByText("워크스페이스를 선택하세요")).toBeInTheDocument();
    // admin(RequireRole 우회)이라도 워크스페이스 없이는 생성 컨트롤이 없어야 한다.
    expect(screen.queryByLabelText("새 문서 제목")).not.toBeInTheDocument();
    expect(loadAllActiveDocumentsMock).not.toHaveBeenCalled();
  });
});
