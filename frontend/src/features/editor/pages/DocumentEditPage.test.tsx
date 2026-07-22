import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { Mock } from "vitest";
import type { ReactElement } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

import { Role } from "@/shared/auth/roles";
import type { EditorScope } from "../hooks/useEditorScope";
import type { UseEditSession } from "../hooks/useEditSession";
import type { EditableDocument, LockState } from "../types";

/**
 * DocumentEditPage 조립 통합 테스트: 세션 생명주기(useEditSession)·스코프(useEditorScope)를
 * 결선해 EditorPane + EditLockBanner 를 조립하는 in-boundary 페이지를 관측한다. 편집창 폭
 * 확보를 위해 버전 이력 사이드 패널은 렌더하지 않는다. 두 자식 컴포넌트와 두 훅을 lightweight
 * stub 으로 모킹해 수신 props 를 기록하고, 라우트 파라미터(:id)에서 documentId 를 파싱해
 * 훅에 전달함을 검증한다.
 *
 * Requirements: 1.1(진입·세션 결선), 1.5/7.2/7.8(viewer 미도달·로컬 role 게이트 없음),
 *   7.1(WS·세션 스코프 주입), 7.3(ApiError 표면화 위임), 7.4(401 전역 위임), 7.5(다른 feature
 *   비의존).
 */

// 두 훅 모킹.
vi.mock("../hooks/useEditSession", () => ({ useEditSession: vi.fn() }));
vi.mock("../hooks/useEditorScope", () => ({ useEditorScope: vi.fn() }));

// 세 자식 컴포넌트를 props 기록 stub 으로 모킹한다.
const editorPaneSpy = vi.fn<(props: unknown) => void>();
vi.mock("../components/EditorPane", () => ({
  EditorPane: (props: unknown): ReactElement => {
    editorPaneSpy(props);
    return <div data-testid="editor-pane" />;
  },
}));

const lockBannerSpy = vi.fn<(props: unknown) => void>();
vi.mock("../components/EditLockBanner", () => ({
  EditLockBanner: (props: unknown): ReactElement => {
    lockBannerSpy(props);
    return <div data-testid="lock-banner" />;
  },
}));

import { useEditSession } from "../hooks/useEditSession";
import { useEditorScope } from "../hooks/useEditorScope";
import { DocumentEditPage } from "./DocumentEditPage";

const useEditSessionMock = useEditSession as unknown as Mock;
const useEditorScopeMock = useEditorScope as unknown as Mock;

const selfLock: LockState = {
  kind: "self",
  lock: {
    document_id: 42,
    lock_user_id: 1,
    lock_acquired_at: "2026-01-01T00:00:00Z",
  },
};

const otherLock: LockState = {
  kind: "other",
  error: new (class {})() as never,
};

const editableDoc: EditableDocument = {
  id: 42,
  workspace_id: 7,
  title: "설계 노트",
  content: "# 본문",
  current_version_id: 99,
};

function makeSession(overrides: Partial<UseEditSession> = {}): UseEditSession {
  return {
    status: "editing",
    lockState: selfLock,
    document: null,
    error: null,
    bindHandle: vi.fn(),
    cancel: vi.fn(),
    retryAcquire: vi.fn(),
    ...overrides,
  };
}

function makeScope(overrides: Partial<EditorScope> = {}): EditorScope {
  return {
    workspaceId: "7",
    role: Role.MEMBER,
    isAdmin: false,
    currentUserId: 1,
    ...overrides,
  };
}

function renderPage(): void {
  render(
    <MemoryRouter initialEntries={["/documents/42/edit"]}>
      <Routes>
        <Route path="/documents/:id/edit" element={<DocumentEditPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useEditSessionMock.mockReset();
  useEditorScopeMock.mockReset();
  editorPaneSpy.mockReset();
  lockBannerSpy.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("DocumentEditPage 조립 (세션 + EditorPane + EditLockBanner)", () => {
  it("라우트 파라미터(:id)에서 documentId 를 파싱해 훅에 전달한다 (Req 1.1)", () => {
    useEditorScopeMock.mockReturnValue(makeScope());
    useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

    renderPage();

    expect(useEditSessionMock).toHaveBeenCalledWith(42);
  });

  it("편집 활성(document 존재) 시 EditorPane·EditLockBanner 를 조립한다 (Req 1.1, 7.1)", () => {
    const scope = makeScope();
    const session = makeSession({ document: editableDoc });
    useEditorScopeMock.mockReturnValue(scope);
    useEditSessionMock.mockReturnValue(session);

    renderPage();

    // EditorPane 은 세션을 그대로 전달받는다.
    expect(screen.getByTestId("editor-pane")).toBeInTheDocument();
    expect(editorPaneSpy).toHaveBeenCalledWith(
      expect.objectContaining({ session }),
    );

    // 버전 이력 사이드 패널은 편집창 폭 확보를 위해 렌더하지 않는다.
    expect(screen.queryByTestId("version-panel")).not.toBeInTheDocument();

    // EditLockBanner 는 lockState + 스코프(role/isAdmin) + onRetry(재획득) 를 받는다.
    expect(screen.getByTestId("lock-banner")).toBeInTheDocument();
    expect(lockBannerSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        lockState: session.lockState,
        documentId: 42,
        currentRole: scope.role,
        isAdmin: scope.isAdmin,
        onRetry: session.retryAcquire,
      }),
    );
  });

  it("잠금 획득 중(acquiring)에는 Spinner 를 표시하고 EditorPane 을 렌더하지 않는다 (Req 1.1)", () => {
    useEditorScopeMock.mockReturnValue(makeScope());
    useEditSessionMock.mockReturnValue(
      makeSession({ status: "acquiring", lockState: { kind: "acquiring" }, document: null }),
    );

    renderPage();

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByTestId("editor-pane")).not.toBeInTheDocument();
  });

  it("타인 잠금(blocked/other)에는 EditLockBanner 를 표시하고 EditorPane 을 렌더하지 않는다 (Req 2.2)", () => {
    const scope = makeScope();
    const session = makeSession({ status: "blocked", lockState: otherLock, document: null });
    useEditorScopeMock.mockReturnValue(scope);
    useEditSessionMock.mockReturnValue(session);

    renderPage();

    expect(screen.getByTestId("lock-banner")).toBeInTheDocument();
    expect(lockBannerSpy).toHaveBeenCalledWith(
      expect.objectContaining({ lockState: otherLock, onRetry: session.retryAcquire }),
    );
    expect(screen.queryByTestId("editor-pane")).not.toBeInTheDocument();
  });

  it("읽기로 돌아가기 back affordance 를 노출한다 (Req 2.2)", () => {
    useEditorScopeMock.mockReturnValue(makeScope());
    useEditSessionMock.mockReturnValue(
      makeSession({ status: "blocked", lockState: otherLock, document: null }),
    );

    renderPage();

    expect(screen.getByRole("button", { name: "읽기로 돌아가기" })).toBeInTheDocument();
  });
});
