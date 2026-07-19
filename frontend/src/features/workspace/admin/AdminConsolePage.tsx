/**
 * AdminConsolePage — admin 화면군 라우트 셸(s16 `RequireAdmin` 하위)
 * (design.md "AdminConsolePage / AdminUserPanel / PasswordResetDialog / AdminOwnerChangePanel",
 *  System Flow "admin 콘솔 게이팅", Req 5.6·6.2·7.2).
 *
 * admin 세션 전용 콘솔의 라우트 셸이다. 화면군 전체(`AdminUserPanel`·`AdminOwnerChangePanel`)를
 * **s16 `<RequireAdmin>`** 하위에 배치한다. 게이팅 판정은 s16 `RequireAdmin` 이 세션 `is_admin`
 * (INV-3) 단일 출처로 수행하며, 이 spec 은 게이트를 재구현하지 않는다(요구 5.6·6.2·7.2).
 *
 * ## 게이팅 축 구분 (Req 7.2)
 * admin 콘솔은 **admin 세션**(session `is_admin`)으로 게이팅되며, 이는 워크스페이스 role 위계
 * (`RequireRole`/`hasWorkspaceRole`)와 **다른 축**이다. 따라서 여기서는 WS role 게이트를 쓰지 않고
 * `RequireAdmin` 만 사용한다. authenticated 이고 `is_admin=true` 인 세션만 콘솔이 렌더되고, 비-admin
 * authenticated·loading·unauthenticated 는 게이트가 차단한다(미인증의 로그인 리다이렉트는 s16 보호
 * 프레임이 담당). 게이트 하위 패널들은 게이트를 스스로 감싸지 않는 내부 패널로만 구성된다.
 *
 * 라우트 등록(s16 보호 슬롯 합성)은 task 7.1(`routes.tsx`)이 담당하며 이 셸은 라우트 대상 element 만
 * 제공한다. 클라이언트 게이팅은 UI 노출 편의일 뿐 서버측 403 강제를 대체하지 않는다(AC 6.6·13.3).
 *
 * Requirements: 5.6(admin 게이팅 s16 RequireAdmin 경유), 6.2(admin 전용 경로),
 * 7.2(admin 세션 축 — WS role 과 독립).
 */

import type { ReactElement } from "react";

import { RequireAdmin } from "@/shared/auth/RequireAdmin";

import { AdminUserPanel } from "./AdminUserPanel";
import { AdminOwnerChangePanel } from "./AdminOwnerChangePanel";

/**
 * admin 콘솔 라우트 셸. s16 `RequireAdmin`(세션 `is_admin`) 하위에 사용자 콘솔·소유권 변경 패널을
 * 배치한다. 비-admin·미인증은 게이트가 차단하므로 콘솔 컨텐츠 전체가 렌더되지 않는다.
 */
export function AdminConsolePage(): ReactElement {
  return (
    <RequireAdmin>
      <section aria-labelledby="admin-console-heading" className="flex flex-col gap-8">
        <header>
          <h1 id="admin-console-heading" className="text-lg font-semibold text-slate-900">
            관리자 콘솔
          </h1>
          <p className="text-sm text-slate-600">계정 생명주기와 워크스페이스 소유권을 관리합니다.</p>
        </header>

        <AdminUserPanel />
        <AdminOwnerChangePanel />
      </section>
    </RequireAdmin>
  );
}
