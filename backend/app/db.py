"""SQLite + SQLModel：引擎与会话。"""

from sqlmodel import Session, SQLModel, create_engine

from . import paths

_engine = None


def init_db() -> None:
    """创建数据目录、引擎与表。"""
    global _engine
    # 路径在此处（而非 import 时）解析，安装态与 SHARP_DATA_DIR 覆盖才能生效。
    paths.ensure_data_dirs()
    _engine = create_engine(
        f"sqlite:///{paths.db_path().as_posix()}",
        connect_args={"check_same_thread": False},
    )
    # 确保模型已注册到 metadata 再建表。
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(_engine)


def get_session() -> Session:
    if _engine is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()。")
    return Session(_engine)
