/**
 * 공유 관리 패널 (design.md §화면 컴포넌트 `ShareLinkPanel`, Req 1.1·1.2·1.3·1.5·2.2·3.3·5.1).
 *
 * 이미 구축된 조각들(도메인 훅 `useShareManager`, 표시 컴포넌트 `InvalidationNotice`·
 * `CopyLinkButton`)을 배선·게이팅만 하는 조립 컴포넌트다. 발급/토글 로직·무효화 판정·복사
 * 폴백은 이 파일이 재구현하지 않는다.
 *
 * 게이팅(Req 1.1·1.2): 관리 UI 전체를 `<RequireRole minimum={EDITOR}
 * currentRole={useCurrentWorkspace().role}>` 로 감싼다. viewer·비멤버는 미노출, admin 은 세션
 * `is_admin` override 로 통과한다(RequireRole 이 override 를 내부 소유). role 문자열을 직접
 * 비교하지 않는다.
 *
 * **role=null 상위갭(seam)**: `useCurrentWorkspace().role` 은 현재 항상 null 이다(s16 이 필드·
 * 형태·기본값만 소유하고, 실제 멤버십 role 주입은 s18 데이터 경로 이연 — Req 8.5 로 s22 는 그
 * 경로를 import 하지 않는다). 따라서 오늘 이 패널은 admin 세션의 is_admin override 로만 노출된다.
 * 이는 설계된 동작이며, `currentRole={useCurrentWorkspace().role}` 을 설계대로 그대로 주입한다.
 *
 * 게이트 반영(Req 1.3): `useCurrentWorkspace().isShareable` 이 false 면 발급·활성화 조작을
 * 비활성화하고 게이트 off 안내를 표시한다(동일 신호는 `useShareManager` 가 `invalidated` 파생에
 * 도 사용). 문서 비활성(status != active)로 인한 활성화 실패는 서버가 409 로 응답하며, 이는
 * `error`(ApiError) 로 표면화된다(Req 3.3·2.2).
 *
 * 오류 표면화(Req 1.5·2.2·3.3): `error` 를 `ErrorMessage` 로 있는 그대로 표시한다(에러 형태 발명
 * 금지). 사용자에게 제시하는 링크는 게스트 프론트 링크(`frontShareUrl`)이며 백엔드 `share_url`
 * (공개 API 경로)이 아니다(Req 2.2).
 *
 * **S4 자기완결 마운트 seam(task 5.1)**: 이 컴포넌트는 오직 `{ documentId, documentStatus }`
 * prop + 세션/워크스페이스 컨텍스트 신호만으로 문서 표면에 마운트되는 자기완결 유닛이다.
 * s19 문서 뷰어 컴포넌트를 import 하거나 그 렌더 경로를 fork/수정하지 않는다(경계: sharing 전용).
 * 실제 마운트 지점(s19 표면의 어느 위치에 이 패널을 배치할지)은 교차-spec 검토 항목이며 s22
 * 코드 변경이 아니다. 이 자기완결 계약은 `ShareLinkPanel.integration.test.tsx` 가 REAL
 * useShareManager + REAL InvalidationNotice 로 잠근다(관측 신호→무효화 안내 종단 경로 포함).
 */

import type { ReactElement, ReactNode } from "react";

import { RequireRole } from "@/shared/auth/RequireRole";
import { Role } from "@/shared/auth/roles";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { Button, ErrorMessage } from "@/shared/ui";

import { useShareManager } from "../hooks/useShareManager";
import { InvalidationNotice } from "./InvalidationNotice";
import { CopyLinkButton } from "./CopyLinkButton";

/** ShareLinkPanel props — design.md §화면 컴포넌트 계약. `documentStatus` 는 s19 관찰 신호. */
export interface ShareLinkPanelProps {
  documentId: number;
  /** s19 관찰 신호(문서 active-ness). useShareManager 의 무효화 파생에 전달된다. */
  documentStatus: string;
}

/**
 * 관리 UI 를 RequireRole(minimum=EDITOR) 로 감싸는 게이팅 진입점. 게이트를 통과할 때만 내부
 * 콘텐츠가 마운트되므로 도메인 훅(`useShareManager`)은 권한이 있을 때만 실행된다.
 */
export function ShareLinkPanel({
  documentId,
  documentStatus,
}: ShareLinkPanelProps): ReactNode {
  const { role } = useCurrentWorkspace();

  return (
    <RequireRole minimum={Role.EDITOR} currentRole={role}>
      <ShareLinkPanelContent documentId={documentId} documentStatus={documentStatus} />
    </RequireRole>
  );
}

/** 게이트 통과 후 렌더되는 관리 콘텐츠. 발급/토글/복사/안내를 이미 구축된 조각에 배선한다. */
function ShareLinkPanelContent({
  documentId,
  documentStatus,
}: ShareLinkPanelProps): ReactElement {
  const { isShareable } = useCurrentWorkspace();
  const { link, frontShareUrl, reissued, invalidated, pending, error, issue, toggle } =
    useShareManager({ documentId, documentStatus });

  // 발급·활성화는 게이트 off(isShareable=false)면 비활성(Req 1.3), 진행 중이면 비활성.
  const issueDisabled = !isShareable || pending;
  // 토글: 끄기는 항상 허용, 켜기는 게이트 off 면 비활성(문서 비활성으로 인한 실패는 서버 409→error).
  const enabling = link !== null && !link.is_enabled;
  const toggleDisabled = pending || (enabling && !isShareable);

  return (
    <section aria-label="공유 관리" className="space-y-4">
      <h2 className="text-base font-semibold text-slate-800">공유 링크 관리</h2>

      {!isShareable ? (
        <p className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          이 워크스페이스는 공유가 꺼져 있어 링크를 발급하거나 활성화할 수 없습니다.
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          onClick={() => {
            void issue();
          }}
          disabled={issueDisabled}
        >
          {link ? "링크 재발급" : "링크 발급"}
        </Button>

        {link ? (
          <>
            <span className="text-sm text-slate-600">
              {link.is_enabled ? "공유 켜짐" : "공유 꺼짐"}
            </span>
            <Button
              variant="secondary"
              onClick={() => {
                void toggle(!link.is_enabled);
              }}
              disabled={toggleDisabled}
            >
              {link.is_enabled ? "공유 끄기" : "공유 켜기"}
            </Button>
          </>
        ) : null}
      </div>

      <CopyLinkButton frontShareUrl={frontShareUrl} />

      <InvalidationNotice invalidated={invalidated} reissued={reissued} />

      <ErrorMessage error={error} />
    </section>
  );
}
