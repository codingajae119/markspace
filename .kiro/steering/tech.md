# 기술 스택

## 아키텍처

- **Backend**: FastAPI(Python) REST API + MySQL 8
- **Frontend**: React + Vite + Tailwind CSS 4 (SPA, backend API 소비)
- **구현 방법론**: Claude Code + cc-sdd(Spec-Driven Development) —
  Steering → Requirements → Design → Tasks → Impl 순서로 진행

## 핵심 기술

- **Language**: Python 3.13+ (backend)
- **Framework**: FastAPI, React + Vite, Tailwind CSS 4
- **DB**: MySQL 8
- **Runtime / 패키지 관리**: **uv** — backend의 모든 의존성 관리·실행은 uv를 기준으로 한다
  (아래 "실행 표준" 참조).

## 설정 관리(Configuration) — 단일화 원칙 (필수, 예외 없음)

새 모듈을 추가할 때도 반드시 이 패턴을 따른다. 모듈별로 별도의 설정 파일이나 로더를 새로 만들지 않는다.

### Backend

- **비밀이 아닌 설정** (DB host/port, 기본 `trash_retention_days`, 파일 저장 루트 경로 등):
  프로젝트 전체에서 **단 하나의 `config.yml`**에만 정의한다.
- **비밀(secret) 값** (DB password, API key 등): **`.env`**에만 정의한다. `.env`는 git에 커밋하지 않는다.
- **로더**: 모든 backend 모듈은 **pydantic-settings**로 구현된 단일 공용 `Settings` 객체를 통해서만
  설정에 접근한다. 모듈마다 `os.environ` 직접 접근, 개별 yaml 파서, 자체 설정 클래스를 만들지 않는다.
- 새 설정 항목이 필요하면 `config.yml`(또는 secret이면 `.env`)에 추가하고 공용 `Settings` 스키마를
  확장한다 — 별도 설정 파일을 신설하지 않는다.

### Frontend

- 단일 설정 파일(예: `frontend/src/config.ts`, 혹은 Vite `.env` 파일 1개)로 API base URL 등
  환경별 값을 통일 관리한다. 여러 파일에 흩어진 하드코딩된 상수를 두지 않는다.

## 실행 표준

- 모든 backend 명령은 **`uv run`**을 통해 실행한다.
  예: `uv run main.py`, `uv run uvicorn app.main:app --reload`, `uv run pytest`
- 의존성 추가/제거는 `uv add` / `uv remove`를 사용하고 `pyproject.toml` + `uv.lock`으로 관리한다.
  `pip install`을 직접 사용하지 않는다.

## 개발 표준

### 문서/spec 언어

- `.kiro/specs/`의 모든 산출물(requirements.md, design.md, tasks.md, research.md, validation report 등)은
  **한국어**로 작성한다.
- 코드 식별자(변수/함수/클래스명), 커밋 메시지, 코드 주석은 별도 지시가 없는 한 통상적인 영어 관례를 따른다.

### 타입 안정성

- Backend: Pydantic 모델로 요청/응답 스키마를 검증한다.
- Frontend: TypeScript strict mode를 권장한다.

## 주요 기술적 결정

- **물리 삭제 없음(INV-4)**: user/document/attachment는 flag·status 전환 또는 보관 폴더 이동만 수행한다.
  DB 스키마·쿼리 설계 시 소프트 삭제 필터링을 기본으로 고려해야 한다(dangling FK가 발생하지 않음).
- **편집 잠금(lock) 방식 채택**: 실시간 동시 편집(CRDT 등) 대신 단순 lock 방식을 채택 —
  구현 복잡도를 낮추기 위한 의도적 선택. lock에 자동 타임아웃은 없다.
- **rollback 미제공**: `document_version`은 열람용 스냅샷일 뿐 복원 대상이 아니다.
- **묶음(bundle) 비흡수 모델**: 문서 삭제/복구/완전삭제는 항상 묶음 단위로 원자적이며, 서로 다른
  시점에 생성된 묶음은 병합되지 않는다(§4.2, INV-10~12). 이 규칙은 document-core 서비스 레이어에
  단일 구현으로 캡슐화한다.

---
_모든 의존성이 아닌 표준과 패턴을 문서화한다._
