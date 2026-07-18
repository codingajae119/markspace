# 프로젝트 구조

## 구성 철학

- Backend(FastAPI)와 Frontend(React+Vite)를 분리된 최상위 디렉터리로 구성하는 모노레포 구조를 지향한다.
- Backend는 레이어드 구조(API 라우터 / 서비스 / 도메인 모델 / 저장소)를 따르며, cc-sdd 스펙 분해와
  정렬한다: `auth` / `workspace` / `document-core` / `trash` / `lock-version` / `sharing` / `attachment`.
- `document-core`(문서 상태·잠금)가 나머지 스펙(trash, version, sharing, attachment)의 선행 의존성이므로,
  이 순서로 먼저 안정화한 뒤 나머지를 얹는다.

## 디렉터리 패턴

### Backend 루트

**위치**: `backend/` (`pyproject.toml`, `main.py`, `.python-version` — uv 프로젝트 스캐폴드)
**목적**: FastAPI 앱, 도메인 로직, uv로 관리되는 Python 의존성
**설정**: `backend/`에 단일 `config.yml`(비밀 아닌 설정) + `.env`(secret)를 두고, pydantic-settings 기반
공용 `Settings` 로더를 거쳐서만 접근한다. 모듈별 개별 설정 파일 금지.

### Frontend

**위치**: `frontend/`
**목적**: React + Vite + Tailwind CSS 4 SPA
**설정**: 단일 설정 파일(예: `frontend/src/config.ts`)로 API base URL 등 환경별 값을 통일 관리한다.
**구조**: feature 단위 폴더(`src/features/{auth,workspace,document,sharing,...}`)로 백엔드 spec 분해와
정렬하고, feature는 자기 화면·훅·API 호출을 자기 폴더 안에 둔다. 교차 관심사(라우팅·공용 API 클라이언트·
전역 401 인터셉터·권한 게이팅·공용 UI)는 공통 레이어(`src/app`·`src/shared`)에 캡슐화한다 — feature는
공통 레이어를 소비하되 다른 feature를 직접 import 하지 않는다.
**라우팅**:
- **보호 라우트**: 세션이 없으면 로그인으로 리다이렉트하되, 진입하려던 경로를 `returnTo`로 보존하고
  로그인 성공 후 그 경로로 복귀한다.
- **게스트 라우트**: `/share/:token` — 세션·워크스페이스 권한과 독립된 읽기 전용 공유 뷰(viewer mode).
  인증 가드를 적용하지 않는다.
- **전역 401 인터셉터**: API 401 응답은 공통 API 클라이언트가 가로채 `returnTo` 보존 후 로그인으로
  리다이렉트한다(각 호출부에서 개별 처리 금지).

### Kiro 스펙/스티어링

**위치**: `.kiro/steering/`(프로젝트 메모리), `.kiro/specs/{feature}/`(기능별 requirements·design·tasks)
**목적**: cc-sdd 워크플로 산출물. 권장 분해(위 "구성 철학" 참조)에 따라 기능 단위 스펙을 생성한다.

## 네이밍 규칙

- **Python**: 모듈/함수/변수는 snake_case, 클래스는 PascalCase (PEP8).
- **Frontend**: 컴포넌트 파일은 PascalCase, 훅/유틸은 camelCase.
- **API 스키마(Pydantic)**: `{Resource}Create` / `{Resource}Read` / `{Resource}Update` 형태로 통일한다.

## Import 구성

```python
# backend 예시 — 절대 import 권장
from app.domain.document import DocumentService
from app.config import get_settings
```

```typescript
// frontend 예시
import { apiConfig } from '@/config'      // 절대 (path alias)
import { useDocument } from './hooks'     // 상대 (같은 feature 내부)
```

## 코드 조직 원칙

- 권한 검사(워크스페이스 단위 한정, INV-1·INV-3)는 공통 레이어에 두고, 각 라우터/서비스에서
  중복 구현하지 않는다.
- 문서 상태 전이와 묶음(bundle) 규칙은 `document-core` 서비스 레이어에 단일 구현으로 캡슐화하고,
  `trash`/`sharing` 등 다른 스펙은 이를 재사용한다.
- 설정 접근은 항상 pydantic-settings `Settings` 객체를 주입받아 사용한다
  (모듈별 파일 직접 읽기·`os.environ` 직접 접근 금지).
- **Frontend 교차 관심사는 공통 레이어가 단일 소유**: 라우팅 정의·전역 401 인터셉터·권한 게이팅은
  공통 레이어에 한 번만 구현하고, 각 feature/화면에서 중복하지 않는다. 권한에 따른 UI 노출
  (편집 가능 여부·잠금 강제 해제 노출 등)은 공통 권한 게이팅 유틸을 거쳐 결정하며, 컴포넌트마다
  역할 비교 로직을 흩뿌리지 않는다.

---
_패턴을 문서화하며, 패턴을 따르는 새 파일은 이 문서 업데이트 없이 추가 가능해야 한다._
