import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useMemberActions } from "./useMemberActions";
import { memberApi } from "../api/memberApi";
import { useSession } from "@/app/session/useSession";
import { useMembershipRoleSource } from "../context/membershipRoleSource";
import type { MembershipRoleSource } from "../context/membershipRoleSource";
import type { SessionContextValue } from "@/app/session/SessionProvider";
import type { MemberRead } from "../api/types";
import { Role } from "@/shared/auth/roles";
import { ApiError } from "@/shared/api/errors";

// useMemberActions 는 memberApi(뮤테이션)·useSession(자기 판정)·MembershipRoleSource(self role
// 에코)를 조합하고, 멤버 목록 GET 부재(S1)로 뮤테이션 응답만 로컬 상태에 축적한다. 협력자를 모킹해
// 성공 시 로컬 상태 반영·실패 시 롤백(상태 불변)·self 대상 시 recordSelfRole 호출을 관찰한다.
const addMock = vi.fn<(id: number, body: unknown) => Promise<MemberRead>>();
const changeRoleMock = vi.fn<(id: number, uid: number, body: unknown) => Promise<MemberRead>>();
const removeMock = vi.fn<(id: number, uid: number) => Promise<void>>();
const recordSelfRoleMock = vi.fn<(workspaceId: number, role: Role) => void>();
const recordOwnerMock = vi.fn<(workspaceId: number) => void>();
const roleForMock = vi.fn<(workspaceId: number) => Role | null>();

vi.mock("../api/memberApi", () => ({
  memberApi: { add: vi.fn(), changeRole: vi.fn(), remove: vi.fn() },
}));
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));
vi.mock("../context/membershipRoleSource", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../context/membershipRoleSource")>();
  return { ...actual, useMembershipRoleSource: vi.fn() };
});

const apiAdd = memberApi.add as unknown as Mock;
const apiChangeRole = memberApi.changeRole as unknown as Mock;
const apiRemove = memberApi.remove as unknown as Mock;

const WS = 7;
const SELF_UID = 100;
const OTHER_UID = 200;

function member(overrides: Partial<MemberRead> = {}): MemberRead {
  return { id: 1, workspace_id: WS, user_id: OTHER_UID, role: "viewer", ...overrides };
}

function authenticated(userId: number): SessionContextValue {
  return {
    status: "authenticated",
    user: {
      id: userId,
      login_id: "self",
      name: "Self",
      email: null,
      is_admin: false,
    },
    settings: null,
    refresh: vi.fn(),
  };
}

function roleSource(): MembershipRoleSource {
  return {
    roleFor: roleForMock,
    recordOwner: recordOwnerMock,
    recordSelfRole: recordSelfRoleMock,
  };
}

function conflict(): ApiError {
  return new ApiError({ status: 409, code: "conflict", message: "이미 멤버입니다" });
}

beforeEach(() => {
  addMock.mockReset();
  changeRoleMock.mockReset();
  removeMock.mockReset();
  recordSelfRoleMock.mockReset();
  recordOwnerMock.mockReset();
  roleForMock.mockReset();
  apiAdd.mockReset();
  apiChangeRole.mockReset();
  apiRemove.mockReset();
  apiAdd.mockImplementation(addMock);
  apiChangeRole.mockImplementation(changeRoleMock);
  apiRemove.mockImplementation(removeMock);
  vi.mocked(useSession).mockReturnValue(authenticated(SELF_UID));
  vi.mocked(useMembershipRoleSource).mockReturnValue(roleSource());
});

describe("useMemberActions", () => {
  it("add 성공 시 반환된 MemberRead 를 로컬 members 에 추가한다 (Req 3.1)", async () => {
    const created = member({ id: 5, user_id: OTHER_UID, role: "editor" });
    addMock.mockResolvedValueOnce(created);

    const { result } = renderHook(() => useMemberActions());
    expect(result.current.members).toEqual([]);

    await act(async () => {
      await result.current.add(WS, { user_id: OTHER_UID, role: "editor" });
    });

    expect(apiAdd).toHaveBeenCalledWith(WS, { user_id: OTHER_UID, role: "editor" });
    expect(result.current.members).toEqual([created]);
    expect(result.current.error).toBeNull();
  });

  it("changeRole 성공 시 매칭 멤버의 role 을 갱신한다 (Req 3.2)", async () => {
    const before = member({ id: 5, user_id: OTHER_UID, role: "viewer" });
    addMock.mockResolvedValueOnce(before);
    const updated = member({ id: 5, user_id: OTHER_UID, role: "editor" });
    changeRoleMock.mockResolvedValueOnce(updated);

    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: OTHER_UID, role: "viewer" });
    });
    await act(async () => {
      await result.current.changeRole(WS, OTHER_UID, { role: "editor" });
    });

    expect(apiChangeRole).toHaveBeenCalledWith(WS, OTHER_UID, { role: "editor" });
    expect(result.current.members).toEqual([updated]);
  });

  it("remove 성공 시 해당 멤버를 로컬 상태에서 제거한다 (Req 3.3)", async () => {
    const m = member({ id: 5, user_id: OTHER_UID });
    addMock.mockResolvedValueOnce(m);
    removeMock.mockResolvedValueOnce(undefined);

    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: OTHER_UID, role: "viewer" });
    });
    expect(result.current.members).toHaveLength(1);

    await act(async () => {
      await result.current.remove(WS, OTHER_UID);
    });
    expect(apiRemove).toHaveBeenCalledWith(WS, OTHER_UID);
    expect(result.current.members).toEqual([]);
  });

  it("add 실패(ApiError) 시 members 를 변경하지 않고 error 를 세팅한다 (Req 3.6, 롤백)", async () => {
    const seed = member({ id: 5, user_id: OTHER_UID });
    addMock.mockResolvedValueOnce(seed);
    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: OTHER_UID, role: "viewer" });
    });
    const before = result.current.members;

    const err = conflict();
    addMock.mockRejectedValueOnce(err);
    await act(async () => {
      await result.current.add(WS, { user_id: 999, role: "editor" });
    });

    expect(result.current.error).toBe(err);
    expect(result.current.members).toBe(before); // 참조까지 불변(반영 잔여 없음)
    expect(result.current.members).toEqual([seed]);
  });

  it("changeRole 실패 시 members 를 변경하지 않는다 (Req 3.6, 롤백)", async () => {
    const seed = member({ id: 5, user_id: OTHER_UID, role: "viewer" });
    addMock.mockResolvedValueOnce(seed);
    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: OTHER_UID, role: "viewer" });
    });
    const before = result.current.members;

    changeRoleMock.mockRejectedValueOnce(conflict());
    await act(async () => {
      await result.current.changeRole(WS, OTHER_UID, { role: "owner" });
    });

    expect(result.current.members).toBe(before);
    expect(result.current.error).not.toBeNull();
  });

  it("remove 실패 시 members 를 변경하지 않는다 (Req 3.6, 롤백)", async () => {
    const seed = member({ id: 5, user_id: OTHER_UID });
    addMock.mockResolvedValueOnce(seed);
    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: OTHER_UID, role: "viewer" });
    });
    const before = result.current.members;

    removeMock.mockRejectedValueOnce(conflict());
    await act(async () => {
      await result.current.remove(WS, OTHER_UID);
    });

    expect(result.current.members).toBe(before);
    expect(result.current.error).not.toBeNull();
  });

  it("self 대상 add 성공 시 recordSelfRole(wsId, memberRoleToRole(role)) 를 호출한다 (Req 3.7)", async () => {
    addMock.mockResolvedValueOnce(member({ id: 9, user_id: SELF_UID, role: "owner" }));
    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: SELF_UID, role: "owner" });
    });
    expect(recordSelfRoleMock).toHaveBeenCalledWith(WS, Role.OWNER);
  });

  it("self 대상 changeRole 성공 시 recordSelfRole 로 자기 role 을 에코한다 (Req 3.7)", async () => {
    addMock.mockResolvedValueOnce(member({ id: 9, user_id: SELF_UID, role: "editor" }));
    changeRoleMock.mockResolvedValueOnce(member({ id: 9, user_id: SELF_UID, role: "viewer" }));
    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: SELF_UID, role: "editor" });
    });
    recordSelfRoleMock.mockClear();
    await act(async () => {
      await result.current.changeRole(WS, SELF_UID, { role: "viewer" });
    });
    expect(recordSelfRoleMock).toHaveBeenCalledWith(WS, Role.VIEWER);
  });

  it("비-self 대상 성공 시 recordSelfRole 을 호출하지 않는다 (Req 3.7)", async () => {
    addMock.mockResolvedValueOnce(member({ id: 9, user_id: OTHER_UID, role: "editor" }));
    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: OTHER_UID, role: "editor" });
    });
    expect(recordSelfRoleMock).not.toHaveBeenCalled();
  });

  it("뮤테이션 실패 시 self 대상이라도 recordSelfRole 을 호출하지 않는다", async () => {
    addMock.mockRejectedValueOnce(conflict());
    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: SELF_UID, role: "owner" });
    });
    expect(recordSelfRoleMock).not.toHaveBeenCalled();
  });

  it("미인증 세션에서 self 판정을 하지 않는다(recordSelfRole 미호출)", async () => {
    vi.mocked(useSession).mockReturnValue({ status: "unauthenticated", refresh: vi.fn() });
    addMock.mockResolvedValueOnce(member({ id: 9, user_id: SELF_UID, role: "owner" }));
    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: SELF_UID, role: "owner" });
    });
    expect(recordSelfRoleMock).not.toHaveBeenCalled();
  });

  it("재시도 시 직전 error 를 해제한다", async () => {
    addMock.mockRejectedValueOnce(conflict());
    const { result } = renderHook(() => useMemberActions());
    await act(async () => {
      await result.current.add(WS, { user_id: OTHER_UID, role: "viewer" });
    });
    expect(result.current.error).not.toBeNull();

    addMock.mockResolvedValueOnce(member({ id: 2, user_id: OTHER_UID }));
    await act(async () => {
      await result.current.add(WS, { user_id: OTHER_UID, role: "viewer" });
    });
    expect(result.current.error).toBeNull();
  });
});
