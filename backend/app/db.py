"""SQLite + SQLModel：引擎与会话。"""

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DB_PATH = DATA_DIR / "sharp.db"

_engine = None


def init_db() -> None:
    """创建数据目录、引擎与表。"""
    global _engine
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(
        f"sqlite:///{DB_PATH.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    # 确保模型已注册到 metadata 再建表。
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(_engine)


def get_session() -> Session:
    if _engine is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()。")
    return Session(_engine)
