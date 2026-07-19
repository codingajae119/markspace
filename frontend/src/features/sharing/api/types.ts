/**
 * s22 공유(sharing)·공개(public) feature 도메인 계약 미러 타입.
 *
 * 백엔드 `app/sharing/schemas.py` 의 스키마(`ShareLinkRead`·`ShareLinkUpdate`·
 * `PublicDocumentNode`·`PublicDocumentRead`)를 정확히 미러링한다(s01/s14 계약 소비).
 * 새 필드를 발명하지 않으며 필드 이름·형태는 실제 스키마와 1:1 로 대응한다. 공통 에러
 * 계약(`ApiError`)·라우팅 가드·fetch 는 s16 소유이므로 여기서 재정의하지 않는다.
 * (Req 2.1·3.1·6.3·8.4)
 *
 * `share_url` 규약: `ShareLinkRead.share_url`(`/public/{token}`)은 ORM `share_link`
 * 컬럼이 아니라 서버가 응답 시 산정하는 **파생 공개 API 경로**이며, 게스트가 브라우저에서
 * 여는 프론트 링크(`/share/:token`)와는 구분되는 값이다(재구성·재계산 금지, 서버가 준
 * 문자열을 그대로 취급).
 */

/**
 * 공유 링크 발급/토글 응답 — 백엔드 `ShareLinkRead`(TimestampedRead 상속) 미러 (Req 2.1).
 *
 * `created_at` 은 백엔드 `datetime` 의 ISO 8601 문자열 직렬화 형태이므로 string 으로
 * 취급한다. `share_link` 테이블에는 `updated_at` 컬럼이 없어 `updated_at` 은 항상 null 이다
 * (TimestampedRead 기본값). `share_url` 은 서버 산정 파생 공개 API 경로(`/public/{token}`)다.
 */
export interface ShareLinkRead {
  id: number;
  created_at: string; // 백엔드 datetime → ISO 8601 문자열
  updated_at: string | null; // share_link 테이블에 컬럼 없음 → 항상 null
  document_id: number;
  token: string;
  is_enabled: boolean;
  share_url: string; // = "/public/{token}" (서버 산정 파생 공개 API 경로·프론트 링크와 구분)
}

/**
 * 공유 링크 토글 요청 본문 — 백엔드 `ShareLinkUpdate` 미러 (Req 3.1).
 *
 * 재발급 통일 원칙(INV-8)의 유일한 상태 기반 예외인 on/off 토글 요청. `is_enabled` 상태만
 * 전환하며 토큰은 유지된다(서비스 소관).
 */
export interface ShareLinkUpdate {
  is_enabled: boolean;
}

/**
 * 공개 읽기 전용 트리 노드 — 백엔드 `PublicDocumentNode` 미러 (Req 6.3, 최소 노출).
 *
 * 공유 문서 및 그 현재 active 하위 계층의 노드. `content_html` 은 서버가 산정한 안전 HTML
 * (nh3 새니타이즈 + 첨부 참조 재작성)이며 프론트에서 재가공하지 않는다. 내부 필드
 * (workspace_id·status·parent_id 등)는 노출하지 않으며, `children` 은 접근 시점의 현재
 * active 하위를 재귀로 담는다.
 */
export interface PublicDocumentNode {
  id: number;
  title: string;
  content_html: string; // 서버 산정 안전 HTML(새니타이즈 + 첨부 참조 재작성)
  children: PublicDocumentNode[];
}

/**
 * 공개 렌더 응답(`GET /public/{token}`) — 백엔드 `PublicDocumentRead` 미러 (Req 6.3).
 *
 * 공유 문서를 루트로 하고 하위 계층을 `root.children` 으로 중첩 표현한다.
 */
export interface PublicDocumentRead {
  root: PublicDocumentNode;
}
