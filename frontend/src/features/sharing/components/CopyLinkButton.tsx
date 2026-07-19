/**
 * 링크 복사 버튼 (design.md §화면 컴포넌트 `CopyLinkButton`, Req 4.1·4.2·4.3·4.4).
 *
 * 이미 상위(`useShareManager`에서 `buildShareUrl(token)`으로) 조립된 절대 게스트 링크를
 * 프롭(`frontShareUrl`)으로 받아, 클릭 시 `navigator.clipboard`로 복사한다. 이 컴포넌트는
 * 링크를 만들지 않으며(경계: CopyLinkButton), 복사·피드백·폴백 표시만 책임진다.
 *
 * - Req 4.1: 클릭 시 `navigator.clipboard.writeText(frontShareUrl)`로 절대 링크를 복사.
 * - Req 4.2: 복사 성공 시 즉각적인 사용자 피드백("복사됨")을 표면화.
 * - Req 4.3: 클립보드 접근 실패(writeText 거부) 또는 `navigator.clipboard` 부재 시 오류를
 *   사용자에게 던지지 않고, 링크 문자열을 사용자가 직접 선택·복사할 수 있는 읽기전용
 *   입력(폴백)으로 노출.
 * - Req 4.4: 활성 링크가 없으면(`frontShareUrl === null`) 복사 조작을 제공하지 않음(버튼 비활성).
 */

import { useState } from "react";
import type { ReactElement } from "react";

import { Button } from "@/shared/ui";

export interface CopyLinkButtonProps {
  /** 상위에서 조립된 절대 게스트 링크. 활성 링크가 없으면 `null`. */
  frontShareUrl: string | null;
}

/** 절대 게스트 링크를 클립보드로 복사하고, 실패 시 선택 가능한 폴백을 노출한다. */
export function CopyLinkButton({ frontShareUrl }: CopyLinkButtonProps): ReactElement {
  const [copied, setCopied] = useState(false);
  const [fallback, setFallback] = useState(false);

  const disabled = frontShareUrl === null;

  async function handleCopy(): Promise<void> {
    if (frontShareUrl === null) {
      return;
    }
    const clipboard = navigator.clipboard;
    try {
      if (!clipboard || typeof clipboard.writeText !== "function") {
        // 클립보드 API 부재 — 폴백으로 유도(오류를 사용자에게 노출하지 않음, Req 4.3).
        throw new Error("clipboard unavailable");
      }
      await clipboard.writeText(frontShareUrl);
      setCopied(true);
      setFallback(false);
    } catch {
      // writeText 거부 또는 API 부재 — 선택·복사 가능한 폴백을 표시(Req 4.3).
      setFallback(true);
      setCopied(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          onClick={() => {
            void handleCopy();
          }}
          disabled={disabled}
        >
          링크 복사
        </Button>
        {copied ? (
          <span role="status" className="text-sm text-emerald-700">
            복사됨
          </span>
        ) : null}
      </div>
      {fallback && frontShareUrl !== null ? (
        <div className="space-y-1">
          <p className="text-sm text-slate-600">
            자동 복사에 실패했습니다. 아래 링크를 선택해 직접 복사하세요.
          </p>
          <input
            type="text"
            readOnly
            value={frontShareUrl}
            aria-label="공유 링크"
            onFocus={(event) => {
              event.currentTarget.select();
            }}
            className="w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
          />
        </div>
      ) : null}
    </div>
  );
}
