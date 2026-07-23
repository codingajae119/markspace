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

// s27 첨부 결선 관측용 배럴 모킹. `useEditorUploadBridge` 는 수신 입력({documentId, canUpload})을
// 기록하고 식별 가능한 sentinel 핸들러를 반환한다 — 이로써 (a) 조립부가 도출해 브리지에 주입한
// canUpload/documentId 와 (b) EditorPane 이 정확히 그 sentinel 핸들러·렌더러를 받았는지 각각
// 단언할 수 있다. `hasWorkspaceRole`(도출)·`buildAttachmentRenderers` 결선은 진짜로 실행된다:
// canUpload 도출은 실제 hasWorkspaceRole 을 거치므로(R4.5) role→bool 파생이 실증된다.
const attachmentMocks = vi.hoisted(() => {
  const onReady = vi.fn();
  const onImagePaste = vi.fn();
  const onFileDrop = vi.fn();
  const bridgeReturn = { onReady, onImagePaste, onFileDrop };
  const renderers = { sentinel: "renderers" } as unknown;
  return {
    onReady,
    onImagePaste,
    onFileDrop,
    bridgeReturn,
    renderers,
    useEditorUploadBridge: vi.fn(() => bridgeReturn),
    buildAttachmentRenderers: vi.fn(() => renderers),
  };
});

vi.mock("@/features/attachment", () => ({
  useEditorUploadBridge: attachmentMocks.useEditorUploadBridge,
  buildAttachmentRenderers: attachmentMocks.buildAttachmentRenderers,
}));

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

function renderPage(routeId = "42"): void {
  render(
    <MemoryRouter initialEntries={[`/documents/${routeId}/edit`]}>
      <Routes>
        <Route path="/documents/:id/edit" element={<DocumentEditPage />} />
        {/* 취소 자동 복귀·읽기 복귀 버튼의 목적지(문서 메인) 관측용 랜딩 라우트. */}
        <Route path="/documents" element={<div data-testid="reading-landing" />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** 마지막 `useEditorUploadBridge` 호출이 수신한 입력({documentId, canUpload})을 반환한다. */
function lastBridgeInput(): { documentId: number | null; canUpload: boolean } {
  const calls = attachmentMocks.useEditorUploadBridge.mock.calls as unknown as Array<
    [{ documentId: number | null; canUpload: boolean }]
  >;
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1]![0];
}

beforeEach(() => {
  useEditSessionMock.mockReset();
  useEditorScopeMock.mockReset();
  editorPaneSpy.mockReset();
  lockBannerSpy.mockReset();
  // 구현(sentinel 반환)은 보존하고 호출 기록만 비운다 — mockReset 은 반환값 구현을 지운다.
  attachmentMocks.useEditorUploadBridge.mockClear();
  attachmentMocks.buildAttachmentRenderers.mockClear();
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

  it("취소 성공(released)이면 읽기 화면으로 자동 전이한다 (Req 4.2)", () => {
    useEditorScopeMock.mockReturnValue(makeScope());
    // 취소 성공 후 세션은 released 로 확정되지만 초기 콘텐츠(document)는 남아 있다 —
    // 조립부가 released 신호를 소비해 읽기 화면으로 전이해야 편집 표면에 머무르지 않는다.
    useEditSessionMock.mockReturnValue(
      makeSession({ status: "released", document: editableDoc }),
    );

    renderPage();

    expect(screen.getByTestId("reading-landing")).toBeInTheDocument();
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

describe("DocumentEditPage 첨부 브리지 결선 (canUpload 도출·id 정규화·prop 결선)", () => {
  // canUpload 도출은 조립부가 자체 role 비교를 흩뿌리지 않고 s16 hasWorkspaceRole(minimum:MEMBER)
  // 단일 경로만 거침을 실증한다(R4.5): 아래 케이스는 hasWorkspaceRole 을 모킹하지 않으므로 진짜
  // role→bool 파생(admin override·role null→false·위계 비교)이 브리지 입력에 반영되는지 관측한다.
  it.each([
    { label: "MEMBER + non-admin → true (R4.1)", role: Role.MEMBER, isAdmin: false, expected: true },
    { label: "OWNER + non-admin → true (R4.1)", role: Role.OWNER, isAdmin: false, expected: true },
    { label: "role=null + non-admin → false (R4.2)", role: null, isAdmin: false, expected: false },
    { label: "role=null + admin → true (admin override, R4.2)", role: null, isAdmin: true, expected: true },
  ])(
    "scope.role/isAdmin 조합에서 실제 hasWorkspaceRole 로 canUpload 를 도출해 브리지에 주입한다 — $label",
    ({ role, isAdmin, expected }) => {
      useEditorScopeMock.mockReturnValue(makeScope({ role, isAdmin }));
      useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

      renderPage();

      expect(lastBridgeInput().canUpload).toBe(expected);
    },
  );

  it("수치 라우트 :id 에서 브리지 documentId 가 number 로 전달된다 (R4.3)", () => {
    useEditorScopeMock.mockReturnValue(makeScope());
    useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

    renderPage("42");

    expect(lastBridgeInput().documentId).toBe(42);
  });

  it("비수치 라우트 :id 에서 브리지 documentId 가 null 로 정규화된다 (R4.3)", () => {
    useEditorScopeMock.mockReturnValue(makeScope());
    // document 는 브리지 호출과 무관(브리지는 렌더 트리에서 무조건 호출)하지만, 비수치 id 정규화가
    // 실제 uploadDocumentId 파생(NaN→null)을 거치는지만 관측한다 — 이 단언은 정규화 제거 시 실패한다.
    useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

    renderPage("abc");

    expect(lastBridgeInput().documentId).toBeNull();
  });

  it("EditorPane 이 브리지 핸들러·렌더러 sentinel 을 네 prop 으로 결선받는다", () => {
    useEditorScopeMock.mockReturnValue(makeScope());
    useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

    renderPage();

    // 브리지가 반환한 정확한 sentinel 핸들러 + 안정화된 렌더러가 EditorPane 에 그대로 전달된다.
    expect(editorPaneSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        onImagePaste: attachmentMocks.onImagePaste,
        onFileDrop: attachmentMocks.onFileDrop,
        onEditorReady: attachmentMocks.onReady,
        renderers: attachmentMocks.renderers,
      }),
    );
    const props = editorPaneSpy.mock.calls[editorPaneSpy.mock.calls.length - 1]![0] as {
      onImagePaste: unknown;
      onFileDrop: unknown;
      onEditorReady: unknown;
      renderers: unknown;
    };
    expect(props.onImagePaste).toBe(attachmentMocks.onImagePaste);
    expect(props.onFileDrop).toBe(attachmentMocks.onFileDrop);
    expect(props.onEditorReady).toBe(attachmentMocks.onReady);
    expect(props.renderers).toBe(attachmentMocks.renderers);
  });
});
