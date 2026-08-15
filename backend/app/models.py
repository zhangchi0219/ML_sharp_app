"""数据库模型：一次生成记录。"""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Generation(SQLModel, table=True):
    """一次「照片→高斯泼溅」生成的记录。"""

    id: str = Field(primary_key=True)
    original_filename: str
    image_path: str  # data/uploads/ 下的文件名
    ply_path: str  # data/gaussians/ 下的文件名（全精度，供下载）
    thumb_path: str  # data/thumbs/ 下的文件名
    num_points: int | None = None
    elapsed_ms: int | None = None
    status: str = "done"
    created_at: datetime = Field(default_factory=_utcnow)
    # 本次生成用的参数（GenParams 的 JSON）。老记录为 None，前端回填时用默认值兜住。
    params: str | None = None
    # 图片 EXIF 推出的 35mm 等效焦距；UI 的「自动」档显示它。
    detected_focal35: float | None = None
    # 网页轻量版 .splat（data/gaussians/ 下的文件名）与它的高斯数。
    # 查看器默认加载它；早于本功能的记录为 None，前端退回 ply_path。
    web_path: str | None = None
    web_points: int | None = None
