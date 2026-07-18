/**
 * 전역 렌더 에러 경계 (design.md "shared / ui & app / layout → ErrorBoundary", AC 7.3).
 *
 * 렌더 중 처리되지 않은 예외가 발생하면 앱 전체 크래시 대신 복구 가능한 오류 화면을 표시한다.
 * React 에서 에러 경계는 반드시 클래스 컴포넌트여야 한다(`getDerivedStateFromError` /
 * `componentDidCatch` 라이프사이클은 함수 컴포넌트에 없다).
 *
 * - `getDerivedStateFromError` → 예외를 상태로 흡수하여 다음 렌더에서 fallback 을 그린다.
 * - `componentDidCatch` → 개발 관측을 위해 브라우저 콘솔에 로깅한다(design "Monitoring").
 * - 복구 어포던스("다시 시도")는 경계 상태를 리셋해 자식 재렌더를 시도한다. 원인이 사라진
 *   일시적 예외라면 정상 화면으로 회복되고, 그대로면 다시 fallback 이 표시된다.
 *
 * 이 컴포넌트는 앱 조립부(task 7.1 `main.tsx`)에서 Provider/Router 를 감싸는 최외곽 경계로
 * 사용된다. 여기서는 컴포넌트만 제공하며, 조립 배선은 이 task 범위 밖이다.
 *
 * Requirements: 7.3(렌더 예외 포착 → 복구 화면, 앱 크래시 방지).
 */

import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

/** 에러 경계 props — 감쌀 자식 트리. */
export interface ErrorBoundaryProps {
  children: ReactNode;
}

/** 에러 경계 상태 — 포착 여부와 표시용 에러(선택). */
export interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

const INITIAL_STATE: ErrorBoundaryState = { hasError: false, error: null };

/**
 * 렌더 예외를 포착해 복구 화면을 표시하는 전역 에러 경계.
 *
 * 계약(design.md): `class ErrorBoundary extends React.Component<{ children: ReactNode },
 * { hasError: boolean }>`. 표시를 위해 `error` 필드를 추가로 보관한다.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = INITIAL_STATE;

  /** 자식 렌더 예외를 상태로 흡수한다(다음 렌더에서 fallback). */
  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  /** 개발 관측: 포착한 예외를 콘솔에 로깅한다(design "Monitoring"). */
  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[ErrorBoundary] 렌더 예외 포착:", error, info.componentStack);
  }

  /** 경계 상태를 초기화해 자식 재렌더를 시도한다(복구 어포던스). */
  private readonly handleReset = (): void => {
    this.setState(INITIAL_STATE);
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center"
        >
          <div className="flex flex-col items-center gap-2">
            <p className="text-base font-medium text-slate-800">
              문제가 발생했습니다
            </p>
            <p className="text-sm text-slate-500">
              화면을 표시하는 중 예기치 못한 오류가 발생했습니다. 다시 시도해 주세요.
            </p>
          </div>
          <button
            type="button"
            onClick={this.handleReset}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 focus-visible:ring-offset-2"
          >
            다시 시도
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
