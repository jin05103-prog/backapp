from sqlalchemy import BigInteger, String, Integer, Boolean, Double, Identity, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

# PostgreSQL의 Base를 상속받아서 서버가 켜질 때 동기화시킨다.
# 기존 posts 테이블은 create_all 로 컬럼이 추가되지 않으므로, 게시글 부가 정보는 새 테이블로 분리한다.
from app.infrastructure.postgresql import Base


class PostExtra(Base):
    __tablename__ = "post_extras"  # 게시글 부가 정보 (말머리, 동영상, 장소, 투표)

    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)  # PK 겸 FK
    post_prefix: Mapped[str] = mapped_column(String(40), nullable=False, default="질문")  # 말머리
    video_key: Mapped[str | None] = mapped_column(String(500))  # 동영상 S3 key
    video_url: Mapped[str | None] = mapped_column(String(1000))  # 동영상 URL
    video_duration: Mapped[int | None] = mapped_column(Integer)  # 동영상 길이(초)
    place_name: Mapped[str | None] = mapped_column(String(200))  # 장소 이름
    place_address: Mapped[str | None] = mapped_column(String(300))  # 장소 주소
    poll_question: Mapped[str | None] = mapped_column(String(300))  # 투표 질문
    poll_options: Mapped[list | None] = mapped_column(JSON)  # 투표 항목 ["항목1", "항목2", ...]


class PostPhoto(Base):
    __tablename__ = "post_photos"  # 게시글 사진

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    photo_key: Mapped[str] = mapped_column(String(500), nullable=False)  # 원본 S3 key
    photo_url: Mapped[str] = mapped_column(String(1000), nullable=False)  # 원본 URL
    thumb_url: Mapped[str | None] = mapped_column(String(1000))  # 썸네일 URL
    photo_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 표시 순서


class PostVideo(Base):
    __tablename__ = "post_videos"  # 게시글 동영상 (여러 개). 예전 글의 동영상은 post_extras 에 남아 있다.

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    video_key: Mapped[str] = mapped_column(String(500), nullable=False)  # 동영상 S3 key
    video_url: Mapped[str] = mapped_column(String(1000), nullable=False)  # 동영상 URL
    video_duration: Mapped[int] = mapped_column(Integer, nullable=False)  # 동영상 길이(초)
    video_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 표시 순서


class PostPlaceCoord(Base):
    __tablename__ = "post_place_coords"  # 장소 좌표 (이름·주소는 post_extras)

    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)  # PK 겸 FK
    latitude: Mapped[float] = mapped_column(Double, nullable=False)  # 위도
    longitude: Mapped[float] = mapped_column(Double, nullable=False)  # 경도


class PostPollSetting(Base):
    __tablename__ = "post_poll_settings"  # 투표 설정. 행이 없으면 단일 선택

    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)  # PK 겸 FK
    allow_multiple: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 복수 선택 허용


class PostLike(Base):
    __tablename__ = "post_likes"  # 좋아요 (회원당 게시글 1개). 개수는 posts.post_like 에도 반영한다.
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_like"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


class PostStat(Base):
    __tablename__ = "post_stats"  # 게시글 통계 (조회수)

    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)  # PK 겸 FK
    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # 조회수


class PostPollVote(Base):
    __tablename__ = "post_poll_votes"  # 투표 참여 (회원당 게시글 1회)
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_poll_vote"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    option_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 선택 항목 (복수 선택이면 첫 번째)


class PostPollExtraChoice(Base):
    __tablename__ = "post_poll_extra_choices"  # 복수 선택의 두 번째 이후 항목. 참여 여부는 post_poll_votes 가 기준
    __table_args__ = (UniqueConstraint("post_id", "user_id", "option_index", name="uq_post_poll_extra_choice"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    option_index: Mapped[int] = mapped_column(Integer, nullable=False)
