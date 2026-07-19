/**
 * AdminUserPanel — admin 사용자 콘솔 내부 패널(계정 목록·생성·상태 갱신·비밀번호 재설정)
 * (design.md "AdminUserPanel", Req 5.1·5.2·5.3·5.4·5.5·5.7·8.4).
 *
 * 마운트 시 `adminApi.listUsers()` 로 계정 목록을 로드해 표시한다. 삭제·비활동 계정도 **필터링하지
 * 않고**(Req 5.1) 각 계정의 상태 flag(`is_admin`·`is_active`·`is_deleted`)를 가시적으로 드러낸다.
 * 목록 상태를 소유하고 뮤테이션(생성·상태 토글) 후 로컬 상태를 갱신한다:
 * - 생성: `AdminUserForm`(생성 모드)의 `onSaved` → 새 계정을 목록 앞에 반영(201).
 * - 상태 토글: 행마다 `AdminUserForm`(상태 편집 모드)로 `is_active`·`is_deleted` 를 **독립** 갱신하고,
 *   성공 시 해당 행을 교체. 단일 admin 409 는 폼이 안내 문구를 표시하며 목록 상태는 변경되지 않는다(롤백).
 * - 비밀번호 재설정: 행의 진입 버튼으로 `PasswordResetDialog` 를 연다.
 *
 * ## 로딩·오류 (s16 프리미티브 소비)
 * 로딩 중에는 s16 `Spinner`, 목록 로드 실패는 s16 `ErrorMessage`(ApiError)로 표시한다. 빈 목록은
 * s16 `EmptyState`. 이 패널은 게이트(`RequireAdmin`)를 감싸지 않는다 — admin 게이팅은 상위
 * `AdminConsolePage`(task 6.3)가 s16 `RequireAdmin` 으로 수행한다(내부 패널로만 구성).
 *
 * 계약 경계: fetch·에러 파싱은 `adminApi`→s16 `apiClient` 위임, UI 프리미티브는 `@/shared/ui` 배럴.
 *
 * Requirements: 5.1(목록·삭제/비활동 포함·상태 flag), 5.2(생성 반영), 5.3(독립 상태 토글),
 * 5.4(비밀번호 재설정 진입), 5.5(단일 admin 409 안내·롤백), 5.7(오류 표시), 8.4(교차 관심사 소비).
 */

import { useEffect, useState } from "react";
import type { ReactElement } from "react";

import { Button, Spinner, EmptyState, ErrorMessage } from "@/shared/ui";
import { ApiError } from "@/shared/api/errors";

import { adminApi } from "../api/adminApi";
import type { UserRead } from "../api/types";
import { AdminUserForm } from "./AdminUserForm";
import { PasswordResetDialog } from "./PasswordResetDialog";

type LoadPhase = "loading" | "ready" | "error";

/** admin 계정 콘솔 패널. 목록 상태를 소유하고 생성·상태 토글·비밀번호 재설정을 결선한다. */
export function AdminUserPanel(): ReactElement {
  const [users, setUsers] = useState<UserRead[]>([]);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [resetTarget, setResetTarget] = useState<UserRead | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setLoadError(null);
    void adminApi
      .listUsers()
      .then((pageResult) => {
        if (cancelled) {
          return;
        }
        // 삭제·비활동 계정을 필터링하지 않고 그대로 표시한다(Req 5.1).
        setUsers(pageResult.items);
        setPhase("ready");
      })
      .catch((caught: unknown) => {
        if (cancelled) {
          return;
        }
        if (caught instanceof ApiError) {
          setLoadError(caught);
        }
        setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 생성 성공 → 새 계정을 목록 앞에 반영(201, Req 5.2).
  const handleCreated = (created: UserRead): void => {
    setUsers((prev) => [created, ...prev]);
  };

  // 상태 토글 성공 → 해당 계정을 갱신된 UserRead 로 교체(Req 5.3). 실패 시 폼이 안내하고 여기선 무변경(롤백).
  const handleUpdated = (updated: UserRead): void => {
    setUsers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
  };

  if (phase === "loading") {
    return (
      <section aria-label="사용자 콘솔" className="flex justify-center py-12">
        <Spinner label="사용자 목록을 불러오는 중" />
      </section>
    );
  }

  if (phase === "error") {
    return (
      <section aria-label="사용자 콘솔" className="flex flex-col gap-3">
        <ErrorMessage error={loadError} />
      </section>
    );
  }

  return (
    <section aria-label="사용자 콘솔" className="flex flex-col gap-6">
      <header>
        <h2 className="text-base font-semibold text-slate-900">사용자 콘솔</h2>
      </header>

      {/* 계정 생성(Req 5.2). is_admin·상태 flag 는 입력받지 않는다. */}
      <AdminUserForm onSaved={handleCreated} />

      {users.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {users.map((item) => (
            <li
              key={item.id}
              className="flex flex-col gap-2 rounded-md border border-slate-200 px-3 py-3"
            >
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-sm font-medium text-slate-900">{item.login_id}</span>
                <span className="text-sm text-slate-600">{item.name}</span>
                <span className="text-sm text-slate-500">{item.email ?? "-"}</span>
                {/* 상태 flag 를 가시적으로 드러낸다(Req 5.1). */}
                <StatusFlags user={item} />
                <Button
                  variant="secondary"
                  aria-label={`${item.login_id} 비밀번호 재설정`}
                  onClick={() => setResetTarget(item)}
                >
                  비밀번호 재설정
                </Button>
              </div>
              {/* is_active·is_deleted 독립 토글(Req 5.3). */}
              <AdminUserForm user={item} onSaved={handleUpdated} />
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState title="사용자가 없습니다" message="아직 등록된 계정이 없습니다." />
      )}

      {resetTarget !== null ? (
        <PasswordResetDialog user={resetTarget} onClose={() => setResetTarget(null)} />
      ) : null}
    </section>
  );
}

/** 계정 상태 flag(is_admin·is_active·is_deleted)를 텍스트 배지로 표시(Req 5.1). */
function StatusFlags({ user }: { user: UserRead }): ReactElement {
  return (
    <span className="flex flex-wrap items-center gap-1.5 text-xs">
      <Badge>{user.is_admin ? "관리자" : "일반 사용자"}</Badge>
      <Badge>{user.is_active ? "활성" : "비활성"}</Badge>
      <Badge>{user.is_deleted ? "삭제됨" : "정상"}</Badge>
    </span>
  );
}

function Badge({ children }: { children: string }): ReactElement {
  return (
    <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-slate-600">
      {children}
    </span>
  );
}
