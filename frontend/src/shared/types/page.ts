/**
 * 목록 응답 공통 엔벨로프 — 백엔드 `app/schemas/base.py` 의 `Page[T]` 정확 미러.
 *
 * `items` 는 페이지 항목 리스트, `total` 은 전체 개수다. 요청측 관심사인
 * limit/offset 은 응답 엔벨로프에 포함하지 않는다(Req 11.2).
 */
export interface Page<T> {
  items: T[];
  total: number;
}
