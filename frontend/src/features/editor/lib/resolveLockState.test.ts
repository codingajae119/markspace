import { describe, it, expect } from "vitest";

import { resolveLockState } from "./resolveLockState";
import type { DocumentLockRead } from "../types";
import { ApiError } from "@/shared/api/errors";

/**
 * resolveLockState 는 `/lock` 응답만을 입력으로 삼아 프론트 파생 `LockState` 를 만드는
 * 순수 함수다. 200 성공은 self(현재 사용자 보유·멱등 재획득 포함), 409 는 other(타인 보유),
 * 그 외 오류(403/404/422/500)는 error 로 매핑한다(Requirements 2.1, 2.2, 2.3, 2.4).
 * 계약에 없는 보유자 식별 정보를 발명하지 않고, 폴링/추측 없이 단일 응답만 반영하며,
 * 부수효과 없이 동일 입력에 동일 출력을 낸다.
 */
describe("resolveLockState", () => {
  const lock: DocumentLockRead = {
    document_id: 7,
    lock_user_id: 42,
    lock_acquired_at: "2026-07-19T10:00:00Z",
  };

  it("200 성공(DocumentLockRead)이면 self 로 매핑하고 lock 을 그대로 보존한다 (Req 2.1)", () => {
    const state = resolveLockState({ ok: lock });

    expect(state).toEqual({ kind: "self", lock });
    if (state.kind === "self") {
      expect(state.lock).toBe(lock);
    }
  });

  it("멱등 재획득(200)도 동일하게 self 로 매핑한다 (Req 2.1)", () => {
    // 재획득 응답 역시 DocumentLockRead 이므로 프론트 재판정 없이 self.
    const reacquired: DocumentLockRead = { ...lock, lock_acquired_at: "2026-07-19T10:05:00Z" };
    const state = resolveLockState({ ok: reacquired });

    expect(state).toEqual({ kind: "self", lock: reacquired });
  });

  it("409(conflict) 오류이면 other 로 매핑하고 error 를 그대로 보존한다 (Req 2.2, 2.3)", () => {
    const error = new ApiError({
      status: 409,
      code: "conflict",
      message: "다른 사용자가 편집 중입니다.",
    });

    const state = resolveLockState({ error });

    expect(state).toEqual({ kind: "other", error });
    if (state.kind === "other") {
      // 계약에 없는 보유자 식별 정보를 발명하지 않고 ApiError 만 실어 나른다.
      expect(state.error).toBe(error);
      expect(Object.keys(state)).toEqual(["kind", "error"]);
    }
  });

  it("403(forbidden) 오류이면 error 로 매핑한다 (Req 2.4)", () => {
    const error = new ApiError({ status: 403, code: "forbidden", message: "권한이 없습니다." });

    const state = resolveLockState({ error });

    expect(state).toEqual({ kind: "error", error });
  });

  it("404(not_found) 오류이면 error 로 매핑한다 (Req 2.4)", () => {
    const error = new ApiError({ status: 404, code: "not_found", message: "문서를 찾을 수 없습니다." });

    const state = resolveLockState({ error });

    expect(state).toEqual({ kind: "error", error });
  });

  it("422(unprocessable) 오류이면 error 로 매핑한다 (Req 2.4)", () => {
    const error = new ApiError({ status: 422, code: "unprocessable", message: "잘못된 요청." });

    expect(resolveLockState({ error })).toEqual({ kind: "error", error });
  });

  it("500(internal) 오류이면 error 로 매핑한다 (Req 2.4)", () => {
    const error = new ApiError({ status: 500, code: "internal", message: "예기치 못한 오류." });

    expect(resolveLockState({ error })).toEqual({ kind: "error", error });
  });

  it("순수 함수: 동일 입력에 동일 출력을 내고 입력을 변형하지 않는다", () => {
    const input = { ok: lock } as const;
    const frozenLock = { ...lock };

    const a = resolveLockState(input);
    const b = resolveLockState(input);

    expect(a).toEqual(b);
    // 입력 lock 이 변형되지 않았음을 확인.
    expect(lock).toEqual(frozenLock);
  });
});
