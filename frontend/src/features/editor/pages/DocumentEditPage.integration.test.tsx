import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, act, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

import { Role } from "@/shared/auth/roles";
import { ApiError } from "@/shared/api/errors";
import {
  buildAttachmentRenderers,
  buildErrorMarker,
  buildPlaceholderToken,
  buildReferenceMarkdown,
} from "@/features/attachment";
import type { AttachmentRead } from "@/features/attachment";
import type {
  CustomRenderers,
  EditorHandle,
  EditorPos,
} from "@/shared/editor/EditorWrapper";
import type { EditorScope } from "../hooks/useEditorScope";
import type { UseEditSession } from "../hooks/useEditSession";
import type { EditableDocument, LockState } from "../types";

/**
 * DocumentEditPage 조립 레벨 통합 테스트 (s27 Task 3.1, R6.4).
 *
 * 이 스펙의 존재 이유인 "소비처 0" 조립 갭을 고정하는 회귀 가드다. 단위테스트가 통과하면서도
 * 결선이 빠져 있던(페이지가 브리지 핸들러·렌더러를 편집 표면 슬롯에 바인딩하지 않던) 결함을
 * 잡기 위해, 실제 `DocumentEditPage` → `EditorPane` → s21 브리지(`useEditorUploadBridge` +
 * `useAttachmentUpload`) 를 **전부 실물로 마운트**하고 아래 두 seam 만 목킹한다:
 *   1. `@/shared/editor/EditorWrapper` — Toast 인스턴스 대신 stub. 수신 props(onReady·
 *      onImagePaste·onFileDrop·renderers)를 기록하고, 테스트가 그 콜백을 직접 발화한다.
 *      (stub 은 onReady 를 자동 호출하지 않는다 — 테스트가 mockHandle 로 발화한다.)
 *   2. `@/shared/api/client` 의 `apiClient` — 업로드 전송(POST) seam. 가장 낮은 안정 seam 을
 *      목킹하므로 `attachmentApi.uploadAttachment`(FormData 조립·URL 구성)와 브리지·업로드
 *      훅은 전부 실물 경로로 실행된다.
 * 세션·스코프(`useEditSession`·`useEditorScope`)는 라우트 결선을 대체해 문서/role 을 주입한다.
 *
 * 조립 갭 포착 속성: stub 이 기록하는 `onImagePaste`/`onFileDrop`/`onReady` 는 EditorPane 이
 * EditorWrapper 로 통과시킨(그리고 EditorPane 이 페이지로부터 받은) 바로 그 핸들러다. 어느
 * 링크(페이지→pane 또는 pane→wrapper)라도 결선이 빠지면 해당 prop 이 undefined 가 되어 발화가
 * no-op 이 되고 아래 붙여넣기/게이팅 시나리오가 실패한다 — 즉 이 테스트가 결선 자체를 관측한다.
 *
 * Requirements: 1.1(붙여넣기 업로드), 1.2(드롭 종류 미지정), 2.1·2.2(렌더러 결선·배선 검증),
 *   3.1(자리표시자 삽입), 3.2(성공 참조 치환), 3.3(실패 오류 마커 치환), 3.5(토큰 재탐색),
 *   4.2(role=null 게이팅 no-op), 6.4(조립 통합 테스트).
 * Design: Testing Strategy → Integration Tests(조립 레벨), System Flows(붙여넣기/드롭 종단), D3.
 */

// ── 목킹 seam 1: EditorWrapper stub (수신 props 기록·콜백 발화 트리거) ──────────────────
const hoisted = vi.hoisted(() => ({
  // 최근 렌더에서 EditorWrapper 가 받은 props 를 담는 홀더.
  wrapper: { props: null as Record<string, unknown> | null },
  // 목킹 seam 2: 업로드 전송(apiClient) — attachmentApi.uploadAttachment 가 실물로 호출한다.
  apiClient: {
    post: vi.fn(),
    get: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  },
}));

vi.mock("@/shared/editor/EditorWrapper", () => ({
  EditorWrapper: (props: Record<string, unknown>) => {
    hoisted.wrapper.props = props;
    return <div data-testid="editor-wrapper" />;
  },
}));

vi.mock("@/shared/api/client", () => ({ apiClient: hoisted.apiClient }));

// 세션·스코프는 라우트 결선 대체(문서/role 주입). EditorPane·EditLockBanner·attachment 배럴은
// 실물로 마운트한다(조립 경로 관측이 이 테스트의 목적).
vi.mock("../hooks/useEditSession", () => ({ useEditSession: vi.fn() }));
vi.mock("../hooks/useEditorScope", () => ({ useEditorScope: vi.fn() }));

import { useEditSession } from "../hooks/useEditSession";
import { useEditorScope } from "../hooks/useEditorScope";
import { DocumentEditPage } from "./DocumentEditPage";

const useEditSessionMock = useEditSession as unknown as Mock;
const useEditorScopeMock = useEditorScope as unknown as Mock;
const postMock = hoisted.apiClient.post as unknown as Mock;

// ── 픽스처 ──────────────────────────────────────────────────────────────────────────
const selfLock: LockState = {
  kind: "self",
  lock: {
    document_id: 42,
    lock_user_id: 1,
    lock_acquired_at: "2026-01-01T00:00:00Z",
  },
};

const editableDoc: EditableDocument = {
  id: 42,
  workspace_id: 7,
  title: "설계 노트",
  content: "# 본문",
  current_version_id: 99,
};

const successAtt: AttachmentRead = {
  id: 100,
  workspace_id: 7,
  document_id: 42,
  kind: "image",
  original_name: "pic.png",
  is_archived: false,
  created_at: "2026-01-01T00:00:00Z",
  url: "/attachments/100", // 서버 산정 파생값 — buildReferenceMarkdown 이 그대로 사용.
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

/**
 * 브리지가 소비하는 `EditorHandle` 을 인메모리 콘텐츠 버퍼로 모델링한다. 브리지의 replaceToken
 * 은 `locateToken(handle.getMarkdown(), token)` 으로 좌표를 재계산하므로(R3.4·3.5), insert 로
 * 삽입된 토큰이 getMarkdown 에 실제로 존재해야 좌표 기반 치환이 관측된다. replaceRange 는
 * `[1-based line, 0-based ch]` 좌표로 실제 치환을 수행해, 성공/실패 치환이 tautology 가 아니라
 * 진짜 좌표 경로를 거쳐 콘텐츠에 반영됨을 검증할 수 있게 한다.
 */
function makeMockHandle(initial = editableDoc.content): {
  getMarkdown: Mock;
  insert: Mock;
  replaceRange: Mock;
  content: () => string;
} {
  let content = initial;
  return {
    getMarkdown: vi.fn(() => content),
    insert: vi.fn((text: string) => {
      // 삽입 지점은 이 테스트에서 중요치 않으므로 말미에 이어 붙인다 — 토큰이 콘텐츠 문자열에
      // 존재하기만 하면 locateToken 이 좌표를 계산한다.
      content = `${content}${text}`;
    }),
    replaceRange: vi.fn((from: EditorPos, to: EditorPos, text: string) => {
      const lines = content.split("\n");
      const fromLine = from[0] - 1;
      const toLine = to[0] - 1;
      const before = lines.slice(0, fromLine);
      const after = lines.slice(toLine + 1);
      const startSeg = (lines[fromLine] ?? "").slice(0, from[1]);
      const endSeg = (lines[toLine] ?? "").slice(to[1]);
      content = [...before, startSeg + text + endSeg, ...after].join("\n");
    }),
    content: () => content,
  };
}

function renderPage(routeId = "42"): void {
  render(
    <MemoryRouter initialEntries={[`/documents/${routeId}/edit`]}>
      <Routes>
        <Route path="/documents/:id/edit" element={<DocumentEditPage />} />
        <Route path="/documents" element={<div data-testid="reading-landing" />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** 최근 EditorWrapper 렌더가 받은 props(테스트가 발화할 콜백 포함)를 타입 안전하게 반환한다. */
function wrapperProps(): {
  onReady?: (h: EditorHandle) => void;
  onImagePaste?: (file: File) => void;
  onFileDrop?: (file: File) => void;
  renderers?: CustomRenderers;
} {
  const props = hoisted.wrapper.props;
  expect(props).not.toBeNull();
  return props as ReturnType<typeof wrapperProps>;
}

/** startUpload 는 fire-and-forget(void) 이므로 발화만 act 로 감싸고 후속 치환은 waitFor 로 기다린다. */
async function fire(cb: (() => void) | undefined): Promise<void> {
  expect(cb).toBeInstanceOf(Function);
  await act(async () => {
    cb!();
  });
}

beforeEach(() => {
  useEditSessionMock.mockReset();
  useEditorScopeMock.mockReset();
  postMock.mockReset();
  hoisted.wrapper.props = null;
});

afterEach(() => {
  cleanup();
});

describe("DocumentEditPage 종단 통합 — 붙여넣기/드롭 → 업로드 → 자리표시자 치환 (조립 갭 가드)", () => {
  it("붙여넣기 종단: onImagePaste 발화 → handle.insert(placeholder) + POST /documents/{id}/attachments (R1.1·3.1)", async () => {
    postMock.mockResolvedValue(successAtt);
    useEditorScopeMock.mockReturnValue(makeScope());
    useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

    renderPage();

    const handle = makeMockHandle();
    // onReady → EditorPane.handleReady → session.bindHandle + bridge.onReady(단일 handle 공유, D1).
    await fire(() => wrapperProps().onReady!(handle as unknown as EditorHandle));

    const imageFile = new File(["bytes"], "pic.png", { type: "image/png" });
    await fire(() => wrapperProps().onImagePaste!(imageFile));

    // 낙관 자리표시자 토큰이 실제 uploadId("upload-1")로 삽입된다(실 buildPlaceholderToken 형식).
    expect(handle.insert).toHaveBeenCalledWith(buildPlaceholderToken("upload-1"));

    // 전송이 실제 발생: attachmentApi.uploadAttachment 실물이 apiClient.post 를 호출한다.
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const [path, body] = postMock.mock.calls[0] as [string, FormData];
    expect(path).toBe(`/documents/${editableDoc.id}/attachments`);
    // 붙여넣기는 이미지로 확정 → FormData 에 kind:"image" 포함(백엔드 위임 전 클라 확정).
    expect((body as FormData).get("kind")).toBe("image");
  });

  it("성공 치환: 201 응답 → handle.replaceRange 가 /attachments/{id} 참조로 치환 (R3.2)", async () => {
    postMock.mockResolvedValue(successAtt);
    useEditorScopeMock.mockReturnValue(makeScope());
    useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

    renderPage();

    const handle = makeMockHandle();
    await fire(() => wrapperProps().onReady!(handle as unknown as EditorHandle));
    await fire(() => wrapperProps().onImagePaste!(new File(["b"], "pic.png", { type: "image/png" })));

    // 실 buildReferenceMarkdown(성공) 형식으로 치환됨: `![pic.png](/attachments/100)`.
    const reference = buildReferenceMarkdown(successAtt);
    await waitFor(() =>
      expect(handle.replaceRange).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        reference,
      ),
    );
    // 좌표 기반 치환이 tautology 가 아님을 확인: 최종 콘텐츠에 참조가 반영된다(placeholder 소거).
    expect(handle.content()).toContain(reference);
    expect(handle.content()).not.toContain(buildPlaceholderToken("upload-1"));
  });

  it("실패 치환: 4xx 거부 → handle.replaceRange 가 오류 마커로 치환 (R3.3)", async () => {
    postMock.mockRejectedValue(
      new ApiError({ status: 422, code: "unprocessable", message: "too large" }),
    );
    useEditorScopeMock.mockReturnValue(makeScope());
    useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

    renderPage();

    const handle = makeMockHandle();
    await fire(() => wrapperProps().onReady!(handle as unknown as EditorHandle));
    await fire(() => wrapperProps().onImagePaste!(new File(["b"], "big.png", { type: "image/png" })));

    // 실 buildErrorMarker 형식으로 치환됨: `⟦attachment-error:upload-1⟧`(깨진 이미지 아님).
    const marker = buildErrorMarker("upload-1");
    await waitFor(() =>
      expect(handle.replaceRange).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        marker,
      ),
    );
    expect(handle.content()).toContain(marker);
  });

  it("드롭 종류 미지정: onFileDrop 발화 → 업로드 FormData 에 kind 미포함(백엔드 추론 위임) (R1.2)", async () => {
    postMock.mockResolvedValue({ ...successAtt, id: 200, kind: "file", original_name: "report.pdf", url: "/attachments/200" });
    useEditorScopeMock.mockReturnValue(makeScope());
    useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

    renderPage();

    const handle = makeMockHandle();
    await fire(() => wrapperProps().onReady!(handle as unknown as EditorHandle));

    const droppedFile = new File(["bin"], "report.pdf", { type: "application/pdf" });
    await fire(() => wrapperProps().onFileDrop!(droppedFile));

    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const [path, body] = postMock.mock.calls[0] as [string, FormData];
    expect(path).toBe(`/documents/${editableDoc.id}/attachments`);
    // 드롭은 kind 를 지정하지 않는다 → FormData 에 kind 필드 자체가 없다(백엔드가 content-type 추론).
    expect((body as FormData).get("kind")).toBeNull();
  });

  it("렌더러 결선(배선 검증): buildAttachmentRenderers() 산출물이 EditorWrapper renderers 에 도달한다 (R2.1·2.2)", () => {
    useEditorScopeMock.mockReturnValue(makeScope());
    useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

    renderPage();

    // 페이지가 useMemo(buildAttachmentRenderers()) 로 주입한 렌더러 객체가 pane 을 거쳐 래퍼
    // slot 까지 도달함을 구조적으로 단언한다(별도 렌더 경로를 만들지 않음, R2.3).
    const received = wrapperProps().renderers;
    const shape = buildAttachmentRenderers();
    expect(received).toBeDefined();
    expect(Object.keys(received as object).sort()).toEqual(Object.keys(shape).sort());
    expect(typeof (received as CustomRenderers).customImageRenderer).toBe("function");
    expect(
      typeof ((received as CustomRenderers).customHTMLRenderer as { link?: unknown }).link,
    ).toBe("function");
    // NOTE(D3): 이 테스트는 렌더러가 편집 표면 slot 까지 "결선"됨(배선)만 단언한다. 과거
    // 유보했던 s16 `.outerHTML` 직렬화 seam 은 해소되었다 — 컨버터가 직렬화 가능한 placeholder
    // 마커만 내보내고 s16 `EditorWrapper.hydrateDom`(afterPreviewRender·read 렌더 직후)이 실 DOM
    // 마커에 인증 컴포넌트를 라이브 마운트한다. 라이브 blob 마운트 자체의 단위 검증은
    // AttachmentRenderBridge.test(hydrateAttachmentsInDom)·EditorWrapper.test(hydrateDom 결선)에서
    // 소유하며, 실제 Toast 렌더 왕복은 jsdom 이 Toast 를 구동하지 못해 여기서 재현하지 않는다.
  });

  it("canUpload 게이팅 종단: role=null(비-admin)이면 onImagePaste 발화가 no-op — POST·insert 미발생 (R4.2)", async () => {
    postMock.mockResolvedValue(successAtt);
    // role=null + 비-admin → 실 hasWorkspaceRole(minimum:MEMBER) 이 false → canUpload false →
    // 브리지 isEnabled() no-op. 이 게이트가 페이지→브리지로 실제 결선됐음을 종단으로 증명한다.
    useEditorScopeMock.mockReturnValue(makeScope({ role: null, isAdmin: false }));
    useEditSessionMock.mockReturnValue(makeSession({ document: editableDoc }));

    renderPage();

    const handle = makeMockHandle();
    await fire(() => wrapperProps().onReady!(handle as unknown as EditorHandle));
    await fire(() => wrapperProps().onImagePaste!(new File(["b"], "pic.png", { type: "image/png" })));

    // 진입점은 열려 있으나(슬롯 결선됨) 게이팅으로 업로드가 시작되지 않는다.
    await act(async () => {
      await Promise.resolve();
    });
    expect(postMock).not.toHaveBeenCalled();
    expect(handle.insert).not.toHaveBeenCalled();
  });
});
