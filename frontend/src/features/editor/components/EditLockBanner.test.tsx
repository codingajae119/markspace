import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, fireEvent, waitFor } from "@testing-library/react";

import { Role } from "@/shared/auth/roles";
import { ApiError } from "@/shared/api/errors";
import { useSession } from "@/app/session/useSession";
import { lockVersionApi } from "../api/lockVersionApi";
import type { LockState } from "../types";
import { EditLockBanner } from "./EditLockBanner";

/**
 * EditLockBanner 는 잠금 상태(self/other/error)를 표시하고, `other` 일 때 강제 해제 조작을
 * owner/admin 에게만 `<RequireRole minimum={OWNER}>` 게이팅으로 노출한다(Req 2.1·2.2·2.3·5.1·
 * 5.4·5.5). 노출 판정은 s16 게이팅 유틸(RequireRole + useForceUnlock.canForceUnlock)로만
 * 수행하며 컴포넌트에서 role 을 직접 비교하지 않는다.
 *
 * 협력자만 모킹한다: (a) `../api/lockVersionApi`(useForceUnlock 의 forceUnlock 을 제어),
 * (b) `@/app/session/useSession`(RequireRole 이 admin bypass 판정을 위해 읽는다). 실
 * RequireRole·hasWorkspaceRole·useForceUnlock·ErrorMessage·Button 을 사용해 게이팅·동작만
 * 관찰한다.
 */

vi.mock("../api/lockVersionApi", () => ({
  lockVersionApi: {
    lockDocument: vi.fn(),
    getDocument: vi.fn(),
    saveDocument: vi.fn(),
    cancelEdit: vi.fn(),
    forceUnlock: vi.fn(),
    listVersions: vi.fn(),
  },
}));

vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));

const forceUnlockMock = lockVersionApi.forceUnlock as unknown as Mock;
const useSessionMock = useSession as unknown as Mock;

const DOC_ID = 42;
const ACQUIRED_AT = "2026-01-02T03:04:05Z";

/** useSession → non-admin authenticated(admin override 미적용). */
function mockNonAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useSession → admin authenticated(INV-3 admin override). */
function mockAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 2, login_id: "root", name: "Root", email: null, is_admin: true },
    settings: null,
    refresh: vi.fn(),
  });
}

function apiError(status: number, code = "conflict", message = `err-${status}`): ApiError {
  return new ApiError({ status, code, message });
}

function selfState(): LockState {
  return {
    kind: "self",
    lock: {
      document_id: DOC_ID,
      lock_user_id: 1,
      lock_acquired_at: ACQUIRED_AT,
    },
  };
}

function otherState(message = "이미 편집 세션이 존재합니다."): LockState {
  return { kind: "other", error: apiError(409, "conflict", message) };
}

function errorState(): LockState {
  return { kind: "error", error: apiError(404, "not_found", "문서를 찾을 수 없습니다.") };
}

beforeEach(() => {
  vi.clearAllMocks();
  forceUnlockMock.mockResolvedValue(undefined);
  mockNonAdmin();
});

afterEach(() => {
  cleanup();
});

describe("EditLockBanner — self 상태 (Req 2.1)", () => {
  it("'내가 편집 중' 과 획득 시각을 표시하고 강제 해제 조작을 노출하지 않는다", () => {
    render(
      <EditLockBanner
        lockState={selfState()}
        documentId={DOC_ID}
        currentRole={Role.OWNER}
        isAdmin={false}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText(/내가 편집 중/)).toBeInTheDocument();
    // 획득 시각은 안정적으로 검증하기 위해 <time dateTime> 로 노출된다.
    const time = screen.getByTestId("lock-acquired-at");
    expect(time).toHaveAttribute("dateTime", ACQUIRED_AT);
    // self 에는 강제 해제 조작이 없다(자기 잠금 해제는 EditorPane cancel 경로, Req 5.3).
    expect(screen.queryByRole("button", { name: /강제 해제/ })).toBeNull();
  });
});

describe("EditLockBanner — other 상태 게이팅 (Req 2.2, 5.1, 5.5)", () => {
  it("MEMBER(non-admin) → '다른 사용자가 편집 중' 안내, 강제 해제 숨김", () => {
    render(
      <EditLockBanner
        lockState={otherState()}
        documentId={DOC_ID}
        currentRole={Role.MEMBER}
        isAdmin={false}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText(/다른 사용자가 편집 중/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /강제 해제/ })).toBeNull();
  });

  it("비멤버(null, non-admin) → 강제 해제 숨김", () => {
    render(
      <EditLockBanner
        lockState={otherState()}
        documentId={DOC_ID}
        currentRole={null}
        isAdmin={false}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /강제 해제/ })).toBeNull();
  });

  it("OWNER(non-admin) → 강제 해제 노출; 클릭 성공(true) 시 onRetry 호출 (Req 5.1, 5.2)", async () => {
    const onRetry = vi.fn();
    render(
      <EditLockBanner
        lockState={otherState()}
        documentId={DOC_ID}
        currentRole={Role.OWNER}
        isAdmin={false}
        onRetry={onRetry}
      />,
    );

    const button = screen.getByRole("button", { name: /강제 해제/ });
    fireEvent.click(button);

    await waitFor(() => expect(onRetry).toHaveBeenCalledTimes(1));
    expect(forceUnlockMock).toHaveBeenCalledTimes(1);
    expect(forceUnlockMock).toHaveBeenCalledWith(DOC_ID);
  });

  it("MEMBER 이지만 session.is_admin=true(prop isAdmin=true) → admin bypass 로 강제 해제 노출 (Req 5.1)", () => {
    mockAdmin();
    render(
      <EditLockBanner
        lockState={otherState()}
        documentId={DOC_ID}
        currentRole={Role.MEMBER}
        isAdmin={true}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /강제 해제/ })).toBeInTheDocument();
  });

  it("강제 해제 403 → ErrorMessage 표면화, onRetry 미호출 (Req 5.4)", async () => {
    forceUnlockMock.mockRejectedValue(apiError(403, "forbidden", "권한이 없습니다."));
    const onRetry = vi.fn();
    render(
      <EditLockBanner
        lockState={otherState()}
        documentId={DOC_ID}
        currentRole={Role.OWNER}
        isAdmin={false}
        onRetry={onRetry}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /강제 해제/ }));

    // other 상태는 409 안내 + 강제 해제 실패 두 개의 alert 를 표면화하므로(Req 2.3·5.4)
    // 강제 해제 오류 메시지를 직접 조회한다.
    await waitFor(() =>
      expect(screen.getByText("권한이 없습니다.")).toBeInTheDocument(),
    );
    expect(onRetry).not.toHaveBeenCalled();
  });
});

describe("EditLockBanner — error 상태 (Req 2.x)", () => {
  it("error 상태의 ApiError 를 ErrorMessage 로 표시한다", () => {
    render(
      <EditLockBanner
        lockState={errorState()}
        documentId={DOC_ID}
        currentRole={Role.OWNER}
        isAdmin={false}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("문서를 찾을 수 없습니다.");
  });
});
