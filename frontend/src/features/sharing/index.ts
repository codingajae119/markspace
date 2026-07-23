/**
 * sharing feature 공개 배럴.
 *
 * 다른 feature(예: document)가 개별 파일이 아닌 이 배럴에서 공유 컨트롤을 마운트한다
 * (교차-feature import 선례 — DocumentViewer → @/features/attachment 와 동일 패턴, 비순환).
 * sharing 내부 조각(useShareManager·CopyLinkButton·ShareLinkPanel 등)은 공개하지 않고,
 * 문서 표면에 결선될 자기완결 컨트롤만 노출한다.
 */

export { DocumentShareControl } from "./components/DocumentShareControl";
export type { DocumentShareControlProps } from "./components/DocumentShareControl";
