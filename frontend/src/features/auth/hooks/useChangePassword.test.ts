import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useChangePassword } from "./useChangePassword";
import { authApi } from "../api/authApi";
import { ApiError } from "@/shared/api/errors";

// useChangePassword 는 authApi.changePassword 만 조합한다(세션·라우팅 미접촉).
// 협력자를 모킹해 204 성공/두 갈래 422 실패의 상태 전이와 재제출 시 stale 신호 해제를 관찰한다.
vi.mock("../api/authApi", () => ({ authApi: { changePassword: vi.fn() } }));

const changePasswordMock = authApi.changePassword as unknown as Mock;

/** 422 현재 비밀번호 불일치(unprocessable). */
function unprocessable(): ApiError {
  return new ApiError({
    status: 422,
    code: "unprocessable",
    message: "Current password does not match",
  });
}

/** 422 새 비밀번호 정책 위반(validation_error, field_errors 포함). */
function validationError(): ApiError {
  return new ApiError({
    status: 422,
    code: "validation_error",
    message: "Validation failed",
    fieldErrors: [{ field: "new_password", message: "최소 8자 이상이어야 합니다." }],
  });
}

const VALID_INPUT = { current_password: "old-password", new_password: "new-password-1" };

beforeEach(() => {
  changePasswordMock.mockReset();
});

describe("useChangePassword", () => {
  it("초기 상태는 submitting=false·succeeded=false·error=null", () => {
    const { result } = renderHook(() => useChangePassword());
    expect(result.current.submitting).toBe(false);
    expect(result.current.succeeded).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("204 성공 시 succeeded=true·error=null", async () => {
    changePasswordMock.mockResolvedValueOnce(undefined);

    const { result } = renderHook(() => useChangePassword());

    await act(async () => {
      await result.current.submit(VALID_INPUT);
    });

    expect(changePasswordMock).toHaveBeenCalledTimes(1);
    expect(changePasswordMock).toHaveBeenCalledWith(VALID_INPUT);
    expect(result.current.succeeded).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("422 unprocessable(현재 비밀번호 불일치) 시 error 에 ApiError 보관·succeeded=false", async () => {
    const err = unprocessable();
    changePasswordMock.mockRejectedValueOnce(err);

    const { result } = renderHook(() => useChangePassword());

    await act(async () => {
      await result.current.submit(VALID_INPUT);
    });

    expect(result.current.error).toBe(err);
    expect(result.current.error?.code).toBe("unprocessable");
    expect(result.current.succeeded).toBe(false);
  });

  it("422 validation_error(새 비밀번호 정책 위반) 시 error 에 ApiError(field_errors 포함) 보관·succeeded=false", async () => {
    const err = validationError();
    changePasswordMock.mockRejectedValueOnce(err);

    const { result } = renderHook(() => useChangePassword());

    await act(async () => {
      await result.current.submit(VALID_INPUT);
    });

    expect(result.current.error).toBe(err);
    expect(result.current.error?.code).toBe("validation_error");
    expect(result.current.error?.fieldErrors).toEqual([
      { field: "new_password", message: "최소 8자 이상이어야 합니다." },
    ]);
    expect(result.current.succeeded).toBe(false);
  });

  it("실패 후 성공 재제출 시 직전 error 를 해제한다(stale error 제거)", async () => {
    const err = unprocessable();
    changePasswordMock.mockRejectedValueOnce(err);

    const { result } = renderHook(() => useChangePassword());

    await act(async () => {
      await result.current.submit(VALID_INPUT);
    });
    expect(result.current.error).toBe(err);
    expect(result.current.succeeded).toBe(false);

    // 두 번째 제출은 성공: 시작 시 직전 오류가 해제되고 succeeded 로 남는다.
    changePasswordMock.mockResolvedValueOnce(undefined);
    await act(async () => {
      await result.current.submit(VALID_INPUT);
    });
    expect(result.current.error).toBeNull();
    expect(result.current.succeeded).toBe(true);
  });

  it("성공 후 실패 재제출 시 직전 succeeded 를 해제한다(stale succeeded 제거)", async () => {
    changePasswordMock.mockResolvedValueOnce(undefined);

    const { result } = renderHook(() => useChangePassword());

    await act(async () => {
      await result.current.submit(VALID_INPUT);
    });
    expect(result.current.succeeded).toBe(true);

    // 두 번째 제출은 실패: 시작 시 직전 성공이 해제되고 error 로 남는다.
    const err = validationError();
    changePasswordMock.mockRejectedValueOnce(err);
    await act(async () => {
      await result.current.submit(VALID_INPUT);
    });
    expect(result.current.succeeded).toBe(false);
    expect(result.current.error).toBe(err);
  });

  it("in-flight 동안 submitting=true, 완료 후 false 로 돌아온다", async () => {
    let releaseChange: (v: unknown) => void = () => {};
    changePasswordMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseChange = resolve;
        }),
    );

    const { result } = renderHook(() => useChangePassword());
    expect(result.current.submitting).toBe(false);

    let submitPromise: Promise<void>;
    act(() => {
      submitPromise = result.current.submit(VALID_INPUT);
    });

    await waitFor(() => expect(result.current.submitting).toBe(true));

    await act(async () => {
      releaseChange(undefined);
      await submitPromise;
    });
    expect(result.current.submitting).toBe(false);
  });
});
