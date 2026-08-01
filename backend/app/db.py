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
    _add_missing_columns()


# create_all 只建**不存在**的表，不会给已有的表补列——已在用的 sharp.db 需要手动迁移。
# 这个应用的 schema 演进只有"加可空列"这一种，够不上引入 alembic，直接守卫式 ALTER。
_ADDED_COLUMNS = {
    "params": "TEXT",
    "detected_focal35": "FLOAT",
}


def _add_missing_columns() -> None:
    """幂等地补齐 generation 表缺失的列。"""
    assert _engine is not None
    with _engine.connect() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(generation)")}
        for name, sql_type in _ADDED_COLUMNS.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE generation ADD COLUMN {name} {sql_type}")
        conn.commit()


def get_session() -> Session:
    if _engine is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()。")
    return Session(_engine)
