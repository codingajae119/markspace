/**
 * 링크 복사 버튼 (design.md §화면 컴포넌트 `CopyLinkButton`, Req 4.1·4.2·4.3·4.4).
 *
 * 이미 상위(`useShareManager`에서 `buildShareUrl(token)`으로) 조립된 절대 게스트 링크를
 * 프롭(`frontShareUrl`)으로 받아, 클릭 시 `navigator.clipboard`로 복사한다. 이 컴포넌트는
 * 링크를 만들지 않으며(경계: CopyLinkButton), 복사·피드백·폴백 표시만 책임진다.
 *
 * 버튼은 공간 절약을 위해 텍스트 라벨 대신 링크(체인) 아이콘만 노출하며, 접근성 이름은
 * `aria-label`("링크 복사")과 hover 툴팁(`title`)으로 보존한다(스크린리더·테스트 셀렉터 무회귀).
 *
 * - Req 4.1: 클릭 시 `navigator.clipboard.writeText(frontShareUrl)`로 절대 링크를 복사.
 * - Req 4.2: 복사 성공 피드백("복사됨")은 버튼 위에 **절대 배치(absolute)** 되는 일시적 툴팁으로
 *   띄운다. 정상 흐름에서 빠져 있어 레이아웃을 밀지 않으며(레이아웃 시프트 방지), 짧은 지연 후
 *   자동으로 사라진다. 재클릭 시 타이머를 갱신하고 언마운트 시 정리한다(pending setState 방지).
 * - Req 4.3: 클립보드 접근 실패(writeText 거부) 또는 `navigator.clipboard` 부재 시 오류를
 *   사용자에게 던지지 않고, 링크 문자열을 사용자가 직접 선택·복사할 수 있는 읽기전용
 *   입력(폴백)으로 노출.
 * - Req 4.4: 활성 링크가 없으면(`frontShareUrl === null`) 복사 조작을 제공하지 않음(버튼 비활성).
 */

import { useEffect, useRef, useState } from "react";
import type { ReactElement } from "react";

import { Button } from "@/shared/ui";

export interface CopyLinkButtonProps {
  /** 상위에서 조립된 절대 게스트 링크. 활성 링크가 없으면 `null`. */
  frontShareUrl: string | null;
}

/** "복사됨" 툴팁이 떠 있는 시간(ms). */
const COPIED_HINT_MS = 1500;

/** 절대 게스트 링크를 클립보드로 복사하고, 실패 시 선택 가능한 폴백을 노출한다. */
export function CopyLinkButton({ frontShareUrl }: CopyLinkButtonProps): ReactElement {
  const [copied, setCopied] = useState(false);
  const [fallback, setFallback] = useState(false);
  // "복사됨" 툴팁 자동 소멸 타이머. 재클릭 시 갱신하고 언마운트 시 정리한다.
  const hintTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 언마운트 시 잔여 타이머 정리(unmount 후 setState 방지).
  useEffect(() => {
    return () => {
      if (hintTimer.current !== null) {
        clearTimeout(hintTimer.current);
      }
    };
  }, []);

  const disabled = frontShareUrl === null;

  /** "복사됨" 툴팁을 띄우고 이전 타이머를 취소한 뒤 자동 소멸을 예약한다. */
  function flashCopied(): void {
    setCopied(true);
    if (hintTimer.current !== null) {
      clearTimeout(hintTimer.current);
    }
    hintTimer.current = setTimeout(() => {
      setCopied(false);
      hintTimer.current = null;
    }, COPIED_HINT_MS);
  }

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
      flashCopied();
      setFallback(false);
    } catch {
      // writeText 거부 또는 API 부재 — 선택·복사 가능한 폴백을 표시(Req 4.3).
      setFallback(true);
      setCopied(false);
    }
  }

  return (
    <div className="space-y-2">
      {/* relative 앵커 — "복사됨" 툴팁을 absolute 로 이 위에 겹쳐 레이아웃을 밀지 않는다. */}
      <div className="relative inline-flex">
        <Button
          variant="secondary"
          onClick={() => {
            void handleCopy();
          }}
          disabled={disabled}
          aria-label="링크 복사"
          title="링크 복사"
          className="px-2"
        >
          {/* 링크(체인) 아이콘 — 시각 라벨 대체. 접근성 이름은 aria-label 이 담당. */}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            className="h-4 w-4"
          >
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
          </svg>
        </Button>
        {copied ? (
          <span
            role="status"
            className="pointer-events-none absolute bottom-full left-1/2 mb-1 -translate-x-1/2 whitespace-nowrap rounded bg-slate-800 px-2 py-1 text-xs text-white shadow-md"
          >
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
