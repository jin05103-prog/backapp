from datetime import datetime, timedelta, timezone
from sqlalchemy import BigInteger, String, Text, DateTime, Identity, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

# PostgreSQL의 Base를 상속받아서 서버가 켜질 때 동기화시킨다.
from app.infrastructure.postgresql import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.model.user_model import User
    from app.model.comment_model import Comment

KST = timezone(timedelta(hours=9))  # UTC+9

class Post(Base):
    __tablename__ = "posts"  # 게시글

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)  # 기본키 (PK)
    post_category: Mapped[str] = mapped_column(String(40), nullable=False)  # 카테고리
    post_title: Mapped[str] = mapped_column(String(200), nullable=False)  # 제목
    post_content: Mapped[str] = mapped_column(Text, nullable=False)  # 내용
    post_status: Mapped[str] = mapped_column(String(40), nullable=False)  # 게시 상태 (게시중, 게시 완료, 게시 불가, 삭제)
    post_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(KST))  # 작성 일시
    post_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 수정 일시
    post_like: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # 좋아요 수
    post_writer_type: Mapped[str] = mapped_column(Text, nullable=False)  # 작성자 타입 (보호자, 예비맘, 육아맘)

    # 관계
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)  # 외래키 (FK)
    user: Mapped["User"] = relationship("User", back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship("Comment", back_populates="post", cascade="all, delete-orphan")
