/**
 * 게스트 공개 문서 페이지 (design.md §화면 컴포넌트 `SharePage`, Req 6.1·8.3).
 *
 * `/share/:token` 게스트 라우트의 페이지 진입점이다. 라우트 `token` 파라미터를 추출해
 * {@link PublicDocumentView} 로 전달하는 얇은 어댑터이며, 상태별 표면(loading·unavailable·
 * error·ready)은 뷰어가 소유한다.
 *
 * 공개(no-auth): 세션·게이팅에 의존하지 않는다(Req 8.3). 프레임·가드 부재는 s16 게스트
 * 슬롯이 소유하며 여기서 재구현하지 않는다. `useParams` 는 `token: string | undefined` 를
 * 반환하지만(`/share/:token` 이므로 실제로는 항상 존재) TS strict 상 부재를 처리한다 —
 * 빈 토큰은 뷰어에서 404 → `unavailable` 단일 표면으로 수렴하므로 별도 분기 없이
 * `token ?? ""` 로 위임한다(존재 추정 차단, Req 6.5 규약 유지).
 */

import type { ReactElement } from "react";
import { useParams } from "react-router-dom";

import { PublicDocumentView } from "../components/PublicDocumentView";

/** `/share/:token` 게스트 라우트의 페이지 — 토큰을 공개 뷰어로 위임한다. */
export function SharePage(): ReactElement {
  const { token } = useParams<{ token: string }>();
  return <PublicDocumentView token={token ?? ""} />;
}
