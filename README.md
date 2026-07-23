# MarkSpace

**한국어** · [English](README.en.md)

> 소규모 폐쇄형(closed) 협업 문서 서비스 — Notion과 유사하지만 필수 기능만 제공합니다.

MarkSpace는 회원 가입(self sign-up)이 없고, 모든 계정을 단일 **admin이 수동으로 발급·관리**하는 통제된 환경을 위한 계층형 markdown 문서 협업 도구입니다. 워크스페이스 단위 권한, 무한 버전 스냅샷, 예측 가능한 휴지통(묶음 비흡수) 모델, 편집 잠금, 읽기 전용 공유 링크를 제공합니다.

이 프로젝트는 Claude Code + **cc-sdd(Spec-Driven Development)** 방법론으로 구현되었습니다. 요구사항·설계·태스크 산출물은 [`.kiro/specs/`](.kiro/specs/)에, 프로젝트 전역 규칙은 [`.kiro/steering/`](.kiro/steering/)에 있습니다.

---

## 핵심 기능

- **워크스페이스 기반 협업** — 사용자는 하나 이상의 워크스페이스에 owner/member 권한으로 소속됩니다. 편집·관리 권한은 워크스페이스 단위로만 존재하고(문서별 개별 권한 없음), 문서·첨부·버전 읽기는 인증된 활성 사용자에게 전역 개방됩니다(멤버십 무관).
- **버전 관리** — 문서 저장 시마다 스냅샷(버전)이 무한 보관됩니다. rollback(과거 버전 복원)은 제공하지 않습니다.
- **3단계 문서 생명주기** — `active → trashed → deleted`. 삭제는 그 시점의 서브트리를 "묶음(bundle)"으로 포착하는 **비흡수(no-absorption)** 모델을 따릅니다 — 서로 다른 시점의 삭제는 병합되지 않으며, 각 묶음은 독립 보관 타이머를 가집니다.
- **편집 잠금(lock)** — 동시 편집 충돌을 lock으로 방지합니다(실시간 동시편집/CRDT는 범위 밖). lock 자동 타임아웃은 없고, 대신 강제 해제 UI를 lock 보유자·워크스페이스 owner·admin에게만 노출합니다.
- **읽기 전용 공유 링크** — 문서 단위로 외부에 공개하며, 워크스페이스의 `is_shareable` 플래그가 게이트 역할을 합니다.
- **첨부/이미지** — 파일로 저장하고(base64 인라인 아님) 워크스페이스별로 격리 보관합니다.

## 기술 스택

| 영역 | 스택 |
|------|------|
| Backend | FastAPI · Python 3.13+ · SQLAlchemy 2 · Alembic · MySQL 8 |
| Frontend | React 19 · Vite 6 · Tailwind CSS 4 · React Router 6 · TypeScript |
| 에디터 | Toast UI Editor (편집=WYSIWYG+markdown 토글 / 읽기=viewer mode 단일 경로) · KaTeX(수식) |
| 인증 | 세션 쿠키 (itsdangerous 서명) · Argon2id 비밀번호 해싱(pwdlib) |
| 런타임/패키지 | Backend는 **uv**, Frontend는 **npm** |

## 프로젝트 구조

```
notion_lite/
├─ backend/            FastAPI 앱 (uv 프로젝트)
│  ├─ app/             도메인별 패키지: auth · workspace · document · trash ·
│  │                   lock_version · attachment · sharing · admin_account · user_settings
│  ├─ migrations/      Alembic 마이그레이션 (versions/0001~0004)
│  ├─ tests/           pytest 스위트 (단위 + 통합 L1~L6)
│  ├─ admin_cli.py     admin 계정 발급 CLI (out-of-band 운영 도구)
│  ├─ config.yml       비밀 아닌 설정 (단일 소스)
│  └─ .env             비밀 값 (DB 비밀번호·세션 시크릿, git 미커밋)
├─ frontend/           React + Vite SPA
│  └─ src/
│     ├─ app/          라우팅·전역 401 인터셉터 등 교차 관심사 (공통 레이어)
│     ├─ shared/       공용 API 클라이언트·UI·권한 게이팅
│     └─ features/     auth · workspace · document · editor · attachment · sharing
├─ scripts/            start.ps1 / stop.ps1 (개발 서버 일괄 기동/종료)
└─ .kiro/              cc-sdd 산출물 (steering + specs)
```

> 아키텍처 원칙: 권한 검사·문서 상태 전이·설정 접근은 각 도메인의 **단일 소유 레이어**에 캡슐화하고 소비처에서 중복 구현하지 않습니다. 자세한 규칙은 [`.kiro/steering/structure.md`](.kiro/steering/structure.md) 참고.

## 사전 요구 사항

- **Python 3.13+** 및 [`uv`](https://docs.astral.sh/uv/)
- **Node.js 18+** (npm)
- **MySQL 8** (로컬 인스턴스, 기본 `127.0.0.1:3306`)

## 설치 및 실행

### 1. 데이터베이스 준비

`config.yml`의 기본값 기준으로 데이터베이스를 생성합니다.

```sql
CREATE DATABASE markspace CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE markspace_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;  -- 테스트용
```

### 2. Backend

```bash
cd backend

# 비밀 값 설정 (.env.example 복사 후 값 채우기)
cp .env.example .env
#   db_password=...            (MySQL 비밀번호)
#   session_secret=...         (긴 랜덤 문자열)

# 의존성 설치 + DB 스키마 마이그레이션
uv sync
uv run alembic upgrade head

# admin 계정 발급 (self sign-up이 없으므로 최초 계정은 CLI로 생성)
uv run admin_cli.py create --login-id admin --name "관리자"
uv run admin_cli.py set-password --login-id admin

# 개발 서버 실행
uv run uvicorn app.main:app --reload   # http://127.0.0.1:8000
```

> **비밀 아닌 설정**(DB host/port, 파일 저장 경로, 보관 일수 등)은 `config.yml`에, **비밀 값**은 `.env`에만 둡니다. 모든 모듈은 pydantic-settings 기반 공용 `Settings` 객체로만 설정에 접근합니다.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev            # http://127.0.0.1:5173 (/api → backend 프록시)
```

### 4. 한 번에 기동 (Windows)

두 서버를 백그라운드로 일괄 기동/종료하는 PowerShell 스크립트를 제공합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1   # backend :8000 + frontend :5173
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
```

## 테스트

```bash
# Backend
cd backend && uv run pytest

# Frontend
cd frontend && npm test          # vitest
npm run typecheck                # tsc --noEmit
```

Backend 통합 테스트는 누적 체크포인트(`tests/integration_L1`~`L6`) 구조로, 스펙 계층이 쌓일 때마다 하위 계약의 회귀를 검증합니다.

## 개발 방법론 (cc-sdd)

이 저장소는 Kiro-style **Spec-Driven Development**를 따릅니다: `Steering → Requirements → Design → Tasks → Implementation` 순서로 각 단계에 사람 리뷰를 두고 진행합니다.

- **Steering** (`.kiro/steering/`) — 프로젝트 전역 규칙·컨텍스트(제품·기술·구조)
- **Specs** (`.kiro/specs/{feature}/`) — 기능 단위 requirements·design·tasks·validation

진행 상황은 `/kiro-spec-status {feature}`로 확인할 수 있습니다. 워크플로 전반은 [`CLAUDE.md`](CLAUDE.md)를 참고하세요.

## 주요 설계 결정

- **물리 삭제 없음** — user/document/attachment는 flag·status 전환 또는 보관 폴더 이동만 수행합니다(dangling FK 미발생).
- **묶음 비흡수** — 삭제/복구/완전삭제는 항상 묶음 단위로 원자적이며, 서로 다른 시점의 묶음은 병합되지 않습니다. `document` 서비스 레이어에 단일 구현으로 캡슐화됩니다.
- **저장 = 버전 생성** — 프론트 자동저장은 주기 타이머가 아니라 **문서 이탈 시 1회**만 수행해 불필요한 버전 폭증을 막습니다.
- **렌더 경로 단일화** — 편집 뷰와 읽기 뷰(읽기 뷰어·공유 링크)를 이원화하지 않고 Toast UI Editor viewer mode로 통일합니다.
