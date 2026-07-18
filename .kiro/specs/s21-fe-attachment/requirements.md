# Requirements Document

## Introduction

`s21-fe-attachment`는 문서 편집 표면(s20 에디터) 위에서 이미지·파일을 **드롭·붙여넣기로 업로드**하고,
업로드 진행 중 자리표시자를 보이며, 문서 콘텐츠에 삽입된 첨부 참조를 **인증·워크스페이스(WS) 격리 경유로
렌더/다운로드**하고, 참조가 사라졌거나(참조 소멸) 서빙이 불가(보관 이동·차단)한 첨부는 **깨진 이미지 대신
안전한 placeholder**로 표현하는 프론트엔드 feature다. 이 spec은 백엔드 `s12-attachment`가 이미 구현한 첨부
엔드포인트를 소비하는 얇은 소비 계층이며, `s16-fe-foundation` 공통 레이어(공용 API 클라이언트·전역 401
인터셉터·Toast UI Editor 래퍼·공용 UI)와 `s19-fe-document` 문서 컨텍스트(어느 문서에 업로드하는지) 위에 얹힌다.

첨부 저장·격리·아카이브 로직(`s12` 백엔드)과 편집 진입/이탈 생명주기·저장(`s20`), 공유 링크 경유 첨부 서빙
(`s22`, `/public/{token}/attachments/...`)은 이 spec의 범위 밖이다. 특히 **완전삭제 시 보관 이동(8.6)**·**저장
참조 소멸 아카이브(8.7)**·**보관 첨부 조회 불가(8.10)**는 백엔드가 단독으로 소유·수행하며, 이 spec은 그
**결과(서빙이 404/403으로 차단됨)를 관측**하여 placeholder로 폴백만 한다. 첨부 상태를 프론트에서 재판정하지
않는다.

검증 기준은 백엔드와 동일하게 `s01-contract-foundation`의 계약 단일 소스다. 소비 엔드포인트와 응답 스키마는
실제 백엔드 라우터(`backend/app/attachment/router.py`)·스키마(`backend/app/attachment/schemas.py`)를 ground-truth로
미러링한다: 업로드는 `POST /documents/{id}/attachments`(multipart, `AttachmentRead`, 201), 조회 서빙은
`GET /attachments/{id}`(바이너리 StreamingResponse). 응답 `AttachmentRead`는 `id·workspace_id·document_id·
kind(image|file)·original_name·is_archived·created_at·url(="/attachments/{id}")`를 가지며, 문서 본문에서의
안정 참조는 `url`이다. 새 API 형태를 발명하지 않는다.

산출물 언어는 한국어이며, 상위 근거로 `s01-contract-foundation`·`s16-fe-foundation`·`s19-fe-document`의
requirements.md·design.md와 steering(`tech.md`·`structure.md`·`roadmap.md`)을 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 드롭/붙여넣기 업로드 훅: 에디터 표면에 이미지·파일을 드롭하거나 붙여넣으면 `POST /documents/{id}/attachments`로
    업로드하고, 성공 시 문서 콘텐츠에 첨부 참조(`url`)를 삽입한다. 붙여넣기/드롭 진입점은 `s16` Toast UI Editor
    래퍼의 이벤트 계약 경유로 얹는다(에디터 표면은 `s20` 소유, 이 spec은 업로드 동작만 얹음).
  - 업로드 진행 플레이스홀더: 업로드 진행 중 자리표시자를 표시하고, 완료 시 실제 이미지/링크 참조로 교체하며,
    실패 시 에러를 표면화(안전한 오류 표시)한다. 여러 업로드를 독립적으로 추적한다.
  - 이미지 렌더·파일 다운로드: 문서 콘텐츠의 첨부 참조(`/attachments/{id}`)를 `s16` API 클라이언트 경유로
    `GET /attachments/{id}`(인증·WS 격리) 로드하여 이미지를 렌더하고, 파일 첨부는 원본 파일명 보존 다운로드를 제공한다.
  - 참조 소멸/서빙 불가 placeholder: 서빙이 404/403(참조 소멸·보관 이동·차단)로 응답하면 깨진 이미지/링크 대신
    안전한 placeholder로 표현한다(백엔드 8.6·8.7·8.10 결과 관측 반영, admin 포함).
- **Out of scope (다른 spec/백엔드가 소유)**:
  - 첨부 파일 저장·WS 격리 저장·완전삭제 반응 보관 이동(8.6)·저장 참조 소멸 아카이브(8.7)·보관 비노출(8.10):
    `s12-attachment` 백엔드 소유. 이 spec은 결과만 관측한다.
  - 에디터 편집 진입/이탈 생명주기·lock·이탈 시 1회 자동저장·버전 스냅샷 생성(`s20-fe-editor`). 이 spec은
    업로드로 콘텐츠에 참조를 삽입만 하며, 그 콘텐츠의 저장 시점·정책은 다루지 않는다.
  - 공유 링크 경유 첨부 서빙(`s22-fe-sharing`, `GET /public/{token}/attachments/{aid}`, 카탈로그 행 37).
    이 spec은 인증 경로(`/attachments/{id}`)만 소비하며 공개 토큰 경로는 다루지 않는다.
  - 공통 레이어(API 클라이언트·전역 401·Toast UI 래퍼·공용 UI)의 **구현**(`s16`). 소비만 한다.
  - 현재 WS 선택·WS 컨텍스트, 문서 트리·뷰어 화면의 **구현**(`s18`·`s19`). 문서 컨텍스트는 소비만 한다.
- **Adjacent expectations (인접 seam)**:
  - 드롭/붙여넣기 진입점과 콘텐츠 참조 삽입·렌더 커스터마이즈는 `s16` `EditorWrapper`가 노출하는 이벤트/렌더
    계약을 경유한다: 붙여넣기/드롭은 `onImagePaste(file)`·`onFileDrop(file)` 슬롯, 자리표시자 삽입/치환은
    `onReady`가 제공하는 `EditorHandle.insert`/`replaceRange`, 첨부 참조 렌더는 `renderers`의
    `customImageRenderer`/`customHTMLRenderer`(edit·read 양 모드 공통)로 결선한다. 이 계약은 **`s16`이 소유·노출**하며
    이 spec은 그 계약을 **소비**한다(래퍼 내부·인스턴스 비소유). `s20` 편집 표면은 래퍼를 마운트하고 이 spec의 브리지
    핸들러·렌더러를 그 래퍼에 바인딩한다(계약 미정합 seam 아님).
  - 업로드 대상 문서 식별자(`documentId`)는 `s19` 문서 컨텍스트(현재 열람/편집 문서)·`s20` 편집 표면에서 오며,
    이 spec은 그 값을 브리지 입력으로 **소비만** 한다.
  - 모든 첨부 백엔드 호출은 `s16` 공용 API 클라이언트를 통해서만 수행하며 401 처리·에러 정규화를 재구현하지
    않는다. feature는 다른 feature를 직접 import 하지 않는다.

## Requirements

### Requirement 1: 드롭/붙여넣기 업로드 (이미지·파일 → 참조 삽입)

**Objective:** As a editor 이상 권한 사용자, I want 편집 중 이미지·파일을 드롭하거나 붙여넣어 업로드하기를,
so that 문서 본문에 이미지·첨부를 자연스럽게 삽입할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 에디터 표면에 이미지를 붙여넣거나 이미지/파일을 드롭하면, the 업로드 기능 shall
   그 바이너리를 `POST /documents/{id}/attachments`에 multipart(파일 + 선택 `kind`)로 전송한다.
2. The 업로드 기능 shall 업로드 대상 문서 식별자(`documentId`)를 `s19` 문서 컨텍스트·`s20` 편집 표면에서
   소비하여 요청 경로(`/documents/{id}/attachments`)에 사용하며, 스스로 문서 컨텍스트를 구현하지 않는다.
3. When 업로드가 성공(201, `AttachmentRead`)하면, the 업로드 기능 shall 응답 `url`(`/attachments/{id}`)을
   문서 콘텐츠의 삽입 위치에 첨부 참조(이미지는 이미지 참조, 파일은 다운로드 링크)로 삽입한다.
4. The 업로드 기능 shall 붙여넣기/드롭 진입점을 `s16` `EditorWrapper`의 `onImagePaste(file)`·`onFileDrop(file)`
   이벤트 슬롯 경유로 얹으며, 자체 에디터 인스턴스나 별도 렌더 경로를 구성하지 않는다(계약 소유는 `s16`).
5. The 업로드 기능 shall 첨부 종류(image/file)를 콘텐츠 참조 형태 결정에만 사용하고, 종류 확정·크기 한도·
   WS 격리 저장 등 저장 판정은 백엔드에 위임한다(프론트 재판정 없음).
6. While 사용자가 viewer 권한만 가지면, the 업로드 기능 shall 드롭/붙여넣기 업로드를 비활성화하고 업로드
   진입점을 노출하지 않는다(INV-2, `s16` 권한 게이팅 경유; 서버측 403이 최종 강제).

### Requirement 2: 업로드 진행 플레이스홀더 (낙관적 UX · 교체 · 실패 표면화)

**Objective:** As a 문서 편집 사용자, I want 업로드가 진행되는 동안 자리표시자를 보고 완료/실패 결과를 명확히
확인하기를, so that 업로드가 매끄럽게 느껴지고 실패가 깨진 콘텐츠로 남지 않는다.

#### Acceptance Criteria

1. When 업로드가 시작되면, the 플레이스홀더 기능 shall 콘텐츠의 삽입 위치에 업로드 진행 중 자리표시자를 먼저
   표시한다.
2. When 업로드가 성공하면, the 플레이스홀더 기능 shall 해당 자리표시자를 실제 첨부 참조(이미지 렌더 또는
   파일 다운로드 링크)로 교체한다.
3. If 업로드가 실패(4xx/5xx)하면, the 플레이스홀더 기능 shall 자리표시자를 깨진 이미지/링크가 아니라 안전한
   오류 표시로 대체하고 `s16` 공용 API 클라이언트가 정규화한 `ApiError`를 사용자에게 표면화한다.
4. When 여러 업로드가 동시에 진행되면, the 플레이스홀더 기능 shall 각 업로드를 고유 식별자로 독립 추적하여
   서로의 자리표시자를 혼동 없이 교체·오류 처리한다.
5. If 업로드가 크기 한도 초과(422)·대상 문서 부재(404)·권한 미달(403)로 거부되면, the 플레이스홀더 기능 shall
   해당 백엔드 오류를 그대로 표면화하며 자체 에러 형태를 발명하지 않는다.

### Requirement 3: 이미지 렌더 (인증·WS 격리 경유)

**Objective:** As a 워크스페이스 멤버(viewer 이상), I want 문서에 삽입된 이미지 첨부가 인증·WS 격리 경로로
안전하게 표시되기를, so that 권한 있는 첨부만 렌더되고 다른 WS로 노출되지 않는다.

#### Acceptance Criteria

1. When 문서 콘텐츠에 첨부 이미지 참조(`/attachments/{id}`)가 포함되면, the 이미지 렌더 기능 shall `s16` 공용
   API 클라이언트로 `GET /attachments/{id}`(자격증명 포함) 바이너리를 로드하여 이미지를 표시한다.
2. The 이미지 렌더 기능 shall 첨부 바이너리를 원시 `src` URL 삽입이 아니라 `s16` API 클라이언트 경유(인증·WS
   격리·오류 정규화)로만 취득하며, 인증되지 않은 직접 접근 경로를 만들지 않는다.
3. While 이미지 바이너리 로딩이 진행 중인 동안, the 이미지 렌더 기능 shall 로딩 상태 표시를 노출한다.
4. When 이미지 바이너리 취득에 사용한 임시 리소스(오브젝트 URL 등)가 더 이상 필요 없어지면, the 이미지 렌더
   기능 shall 그 리소스를 해제하여 누수를 방지한다.
5. The 이미지 렌더 기능 shall `s16` `EditorWrapper`의 `renderers`(`customImageRenderer`/`customHTMLRenderer`,
   edit·read 양 모드 공통) 계약을 경유하여 콘텐츠 내 첨부 참조를 인증 렌더로 연결하며, 편집·읽기 뷰의 렌더
   경로를 이원화하지 않는다.

### Requirement 4: 파일 첨부 다운로드

**Objective:** As a 워크스페이스 멤버(viewer 이상), I want 문서에 첨부된 파일을 원본 파일명으로 내려받기를,
so that 이미지가 아닌 자료 파일도 안전하게 열람·저장할 수 있다.

#### Acceptance Criteria

1. When 사용자가 파일 첨부 참조를 활성화(다운로드 실행)하면, the 다운로드 기능 shall `s16` 공용 API 클라이언트로
   `GET /attachments/{id}` 바이너리를 로드하여 다운로드를 트리거한다.
2. The 다운로드 기능 shall 다운로드 파일명을 첨부의 `original_name`으로 보존한다.
3. The 다운로드 기능 shall 파일 첨부 참조를 이미지가 아닌 다운로드 가능한 링크 형태로 표시하여 이미지 렌더와
   구분한다.
4. If 파일 바이너리 취득이 실패하면, the 다운로드 기능 shall 오류를 표면화하고 깨진 링크로 남기지 않는다
   (참조 소멸/서빙 불가는 Requirement 5의 placeholder로 처리).

### Requirement 5: 참조 소멸 · 서빙 불가 placeholder (8.6·8.7·8.10 관측)

**Objective:** As a 워크스페이스 멤버, I want 사라졌거나 접근할 수 없는 첨부가 깨진 이미지 대신 안전한
placeholder로 보이기를, so that 문서가 깨져 보이지 않고 상태를 명확히 이해할 수 있다.

#### Acceptance Criteria

1. If 첨부 서빙(`GET /attachments/{id}`)이 404(존재하지 않음·보관 이동으로 참조 소멸)로 응답하면, the 렌더
   기능 shall 깨진 이미지/링크가 아니라 안전한 placeholder를 표시한다.
2. If 첨부 서빙이 403(권한 미달·차단)으로 응답하면, the 렌더 기능 shall 안전한 placeholder를 표시하고 원인을
   과도한 내부 정보 노출 없이 안내한다.
3. The 렌더 기능 shall 참조 소멸·보관 이동(8.6)·저장 참조 소멸 아카이브(8.7)·보관 비노출(8.10, admin 포함
   조회 불가)을 프론트에서 판정하지 않고, 서빙 응답(404/403)이라는 관측 가능한 결과만 근거로 placeholder로
   폴백한다.
4. The 렌더 기능 shall 서빙 불가(404/403)로 인한 placeholder 상태와 일시적 네트워크/서버 오류(재시도 여지)를
   구분하여, 전자는 placeholder로 안정적으로 표현한다.
5. While admin 사용자가 보관(아카이브)된 첨부 참조를 열람하는 동안, the 렌더 기능 shall 백엔드가 role 무관
   404로 차단하므로 동일하게 placeholder를 표시한다(보관은 어떤 경로로도 노출되지 않음).

### Requirement 6: 첨부 접근 단일 경로 (s16 API 클라이언트 · WS 격리 · 인증 · 오류 정규화)

**Objective:** As a 프론트엔드 사용자·구현자, I want 모든 첨부 접근이 `s16` 공용 API 클라이언트 단일 경로로
이뤄지기를, so that 인증·WS 격리·401 처리·에러 정규화가 일관되게 적용되고 개별 호출부에 흩어지지 않는다.

#### Acceptance Criteria

1. The 첨부 기능 shall 업로드·조회·다운로드를 포함한 모든 백엔드 호출을 `s16` 공용 API 클라이언트로만 수행하고,
   자체 fetch·에러 파싱·base URL 하드코딩을 두지 않는다.
2. When 첨부 요청이 전송되면, the 첨부 기능 shall `s16` 클라이언트의 자격증명 포함(credentials) 설정으로 서명
   쿠키 세션을 전송하여 WS 격리·인증 판정이 백엔드에서 강제되게 한다.
3. If 첨부 요청이 401(인증 만료)로 응답하면, the 첨부 기능 shall 개별 처리를 하지 않고 `s16` 전역 401
   인터셉터의 로그인 리다이렉트(returnTo 보존)에 위임한다.
4. When 백엔드가 오류를 반환하면, the 첨부 기능 shall `s16` 공용 API 클라이언트가 정규화한 `ApiError`
   (code·message·field_errors)를 그대로 표면화하며 자체 에러 형태를 발명하지 않는다.
5. The 클라이언트 측 업로드 게이팅(viewer 미노출)은 UI 노출 편의일 뿐이며 서버측 권한 강제(백엔드 403·404)를
   대체하지 않음을 the 첨부 기능 shall 전제한다.
6. The 첨부 기능 shall 다른 feature 폴더를 직접 import 하지 않고, 공통 레이어(`s16`)와 인접 seam(`s19`/`s20`)
   경유로만 연동한다.

### Requirement 7: 계약 미러링 · 참조 URL 규약 · 경계

**Objective:** As a 프론트엔드 구현자, I want 첨부 타입·참조 규약이 백엔드 계약을 정확히 미러링하고 인접 spec과의
경계가 명확하기를, so that 계약 드리프트 없이 소비하고 s12/s20/s22 소유 영역을 침범하지 않는다.

#### Acceptance Criteria

1. The 첨부 기능 shall `AttachmentRead`(id·workspace_id·document_id·kind·original_name·is_archived·created_at·url)와
   `AttachmentKind`(image|file)를 백엔드 스키마(`backend/app/attachment/schemas.py`)와 필드 1:1로 미러링하며 새
   필드를 발명하지 않는다.
2. The 첨부 기능 shall 문서 본문에서의 안정 참조를 응답 `url`(`/attachments/{id}`) 규약으로만 사용하고, 참조
   URL을 프론트에서 임의로 재구성하지 않는다.
3. The 첨부 기능 shall 첨부 저장·WS 격리 저장·완전삭제 반응 보관 이동(8.6)·저장 참조 소멸 아카이브(8.7)를
   구현하지 않으며(백엔드 `s12` 소유), 오직 서빙 결과를 관측한다.
4. The 첨부 기능 shall 편집 진입/이탈·lock·자동저장·버전 스냅샷(`s20`)과 공유 링크 경유 첨부 서빙
   (`/public/{token}/attachments/{aid}`, `s22`)을 소유하지 않는다.
5. The 첨부 기능 shall 붙여넣기/드롭 이벤트(`onImagePaste`/`onFileDrop`)·콘텐츠 삽입/치환(`EditorHandle.insert`/
   `replaceRange`)·첨부 참조 렌더(`renderers.customImageRenderer`/`customHTMLRenderer`)를 `s16` `EditorWrapper`가
   소유·노출하는 계약으로 소비하며, 자체 에디터 인스턴스나 별도 렌더 경로를 만들지 않는다(계약 소유는 `s16`).
