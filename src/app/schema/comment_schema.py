from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel
from datetime import datetime

# VO (ERD 테이블: comments / 댓글)
class CommentVO(BaseModel):
    id: int

    comment_content: str
    comment_is_secret: bool
    comment_created_at: datetime
    comment_updated_at: datetime | None = None

    post_id: int
    user_id: int


# ---------------------------------------------------------------------------
# 커뮤니티 댓글 API DTO (프론트와 camelCase 로 주고받는다)
# ---------------------------------------------------------------------------
MAX_COMMENT_LENGTH = 1000


class _CamelDTO(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class CommentCreateDTO(_CamelDTO):
    content: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)

    @field_validator("content")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("댓글 내용을 입력해 주세요.")
        return value


class CommentItemDTO(_CamelDTO):
    id: int
    author_name: str
    content: str
    is_secret: bool
    is_mine: bool  # 조회한 회원이 쓴 댓글 (삭제 가능)
    created_at: datetime
