# Brief: s21-fe-attachment

## Problem
편집 중(s20 에디터 표면)에 이미지·파일을 드롭·붙여넣기로 업로드하고, 업로드 진행 중 플레이스홀더를
표시하며, 저장 시 참조가 사라진 첨부(참조 소멸)는 placeholder로 안전하게 표현해야 한다. 첨부는 WS
격리되며 링크/상태에 따라 서빙이 차단될 수 있다.

## Current State
s16 공통 레이어·s20 에디터 편집 표면 확보 가정. 소비 API:
`POST /attachments`(multipart 업로드, AttachmentRead·201), `GET /attachments/{id}`(StreamingResponse — 이미지 로딩·다운로드).
백엔드 s12-attachment 완료. 완전삭제 시 보관 이동(8.6)·저장 참조 소멸 아카이브(8.7)는 백엔드 소유(관찰).

## Desired Outcome
- 드롭/붙여넣기 업로드: 에디터에 이미지·파일을 드롭하거나 붙여넣으면 `POST /attachments`로 업로드,
  성공 시 문서 콘텐츠에 참조 삽입.
- 업로드 플레이스홀더: 업로드 진행 중 자리표시자 표시, 완료 시 실제 이미지/링크로 교체, 실패 시 에러 표면화.
- 이미지 로딩·다운로드: `GET /attachments/{id}`로 렌더(WS 격리·인증 경유), 첨부 파일 다운로드 링크.
- 참조 소멸 placeholder: 저장 시 참조가 사라졌거나 서빙 불가(보관 이동/차단)한 첨부는 깨진 이미지 대신
  안전한 placeholder로 표현(참조 소멸 상태 관찰 반영).

## Approach
s20 에디터 표면에 업로드 훅을 얹는다(드롭/붙여넣기 이벤트 → 업로드 → 참조 삽입). 낙관적 플레이스홀더로
UX를 매끄럽게 하고, 서빙 실패/참조 소멸은 placeholder로 폴백. 첨부 접근은 s16 API 클라이언트 경유(WS 격리·인증).

## Scope
- **In**: 드롭/붙여넣기 업로드 훅, 업로드 진행 플레이스홀더, 이미지 렌더·다운로드, 참조 소멸/서빙 불가 placeholder.
- **Out**: 첨부 저장/격리/아카이브 로직(s12 백엔드), 에디터 편집 생명주기·저장(s20), 공유 링크 경유 첨부 서빙(s22).

## Boundary Candidates
- 드롭/붙여넣기 업로드 훅
- 업로드 진행 플레이스홀더
- 이미지 렌더·파일 다운로드
- 참조 소멸/서빙 불가 placeholder

## Out of Boundary
- 첨부 저장·격리·보관 이동·아카이브(s12 백엔드)
- 에디터 lock/저장(s20)
- 공유 링크 경유 첨부 접근(s22)

## Upstream / Downstream
- **Upstream**: s16-fe-foundation(API 클라이언트·UI·Toast UI 래퍼 이벤트), s19-fe-document(문서 컨텍스트),
  s01(attachment 계약)
- **Downstream**: s22-fe-sharing(공유 뷰에서 링크 경유 이미지/첨부를 표시 — 서빙 경로만 다름)

## Existing Spec Touchpoints
- **Extends**: 없음(신규)
- **Adjacent (동일 wave, 병렬 생성 — cross-spec 리뷰에서 정합)**: s20-fe-editor(에디터 편집 표면에
  붙여넣기/드롭 훅을 얹음 — 붙여넣기 진입점은 s16 Toast UI 래퍼 이벤트 계약 경유로 정합), s22-fe-sharing(공유 경유 첨부 렌더)

## Constraints
첨부 WS 격리·인증은 s16 클라이언트 경유. 참조 소멸(8.7)·서빙 차단(보관/게이트)은 placeholder 폴백.
검증 기준 s01 계약. 산출물 한국어.
