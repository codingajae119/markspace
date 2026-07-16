"""실행 래퍼.

애플리케이션 조립은 ``app.main.create_app()`` 이 소유한다. 개발용 기동은
아래 명령을 권장한다::

    uv run uvicorn app.main:app

이 스크립트는 ``python main.py`` 로도 동일한 앱을 기동할 수 있게 하는 얇은
러너일 뿐이며, 별도의 앱 인스턴스를 만들지 않는다.
"""

from app.main import app


def main() -> None:
    import uvicorn

    uvicorn.run(app)


if __name__ == "__main__":
    main()
