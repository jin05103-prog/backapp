from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel
from datetime import datetime
from app.enum.post_enum import PostStatus, PostWriterType, PostCategory

# VO (ERD 테이블: posts / 게시글)
class PostVO(BaseModel):
    id: int

    post_category: PostCategory
    post_title: str
    post_content: str
    post_status: PostStatus
    post_created_at: datetime
    post_updated_at: datetime | None = None
    post_like: int
    post_writer_type: PostWriterType

    user_id: int


# ---------------------------------------------------------------------------
# 커뮤니티 게시글 API DTO (프론트와 camelCase 로 주고받는다)
# ---------------------------------------------------------------------------
# 프론트가 쓰는 게시판 값 -> DB(PostCategory enum) 값
CATEGORY_TO_ENUM = {
    "pregnancy": PostCategory.PREGNANCY_STORY,
    "parenting": PostCategory.PARENTING_STORY,
    "neighborhood": PostCategory.NEIGHBORHOOD,
    "health": PostCategory.HEALTH,
    "living": PostCategory.LIVELIHOOD,
}
ENUM_TO_CATEGORY = {enum.value: key for key, enum in CATEGORY_TO_ENUM.items()}
POST_CATEGORIES = tuple(CATEGORY_TO_ENUM.keys())
# 게시판별 말머리 (프론트 _constants/write.ts 의 BOARD_PREFIXES 와 같아야 한다)
POST_PREFIXES_BY_CATEGORY = {
    "pregnancy": ("질문", "후기", "정보 공유", "일상"),
    "parenting": ("질문", "후기", "정보 공유", "일상"),
    "neighborhood": ("질문", "정보 공유", "모임", "일상"),
    "health": ("질문", "후기", "정보 공유"),
    "living": ("질문", "추천", "후기", "정보 공유"),
}
MAX_PHOTOS = 10
MAX_VIDEOS = 3
MAX_VIDEO_SECONDS = 60


class _CamelDTO(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class PostPhotoInDTO(_CamelDTO):
    key: str
    url: str
    thumb_url: str | None = None


class PostVideoInDTO(_CamelDTO):
    key: str
    url: str
    duration: int = Field(ge=0, le=MAX_VIDEO_SECONDS)  # 최대 1분


class PostPlaceDTO(_CamelDTO):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(default="", max_length=300)
    # 좌표는 함께 보내야 한다. 좌표 없이 저장된 예전 글은 둘 다 None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _check_coordinates(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("위도와 경도는 함께 보내야 합니다.")
        return self


class PostPollInDTO(_CamelDTO):
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=5)
    allow_multiple: bool = False

    @field_validator("options")
    @classmethod
    def _clean_options(cls, options: list[str]) -> list[str]:
        cleaned = [option.strip() for option in options if option.strip()]
        if len(cleaned) < 2:
            raise ValueError("투표 항목은 2개 이상이어야 합니다.")
        return cleaned


class PostCreateDTO(_CamelDTO):
    category: str
    prefix: str = "질문"
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    is_public: bool = True
    photos: list[PostPhotoInDTO] = Field(default_factory=list, max_length=MAX_PHOTOS)
    videos: list[PostVideoInDTO] = Field(default_factory=list, max_length=MAX_VIDEOS)
    place: PostPlaceDTO | None = None
    poll: PostPollInDTO | None = None

    @field_validator("category")
    @classmethod
    def _check_category(cls, value: str) -> str:
        if value not in POST_CATEGORIES:
            raise ValueError("올바르지 않은 게시판입니다.")
        return value

    @model_validator(mode="after")
    def _check_prefix(self):
        if self.prefix not in POST_PREFIXES_BY_CATEGORY[self.category]:
            raise ValueError("게시판에 맞지 않는 말머리입니다.")
        return self

    @field_validator("title", "content")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("비어 있을 수 없습니다.")
        return value


# 수정 요청. photos·videos 에는 새로 올린 파일만 담고, 남길 기존 파일은 id 로 보낸다.
class PostUpdateDTO(PostCreateDTO):
    keep_photo_ids: list[int] = Field(default_factory=list)
    keep_video_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_attachment_count(self):
        if len(set(self.keep_photo_ids)) + len(self.photos) > MAX_PHOTOS:
            raise ValueError(f"사진은 최대 {MAX_PHOTOS}장까지 첨부할 수 있습니다.")
        if len(set(self.keep_video_ids)) + len(self.videos) > MAX_VIDEOS:
            raise ValueError(f"동영상은 최대 {MAX_VIDEOS}개까지 첨부할 수 있습니다.")
        return self


class PostVoteDTO(_CamelDTO):
    option_indexes: list[int] = Field(min_length=1, max_length=5)  # 단일 선택이면 1개

    @field_validator("option_indexes")
    @classmethod
    def _check_indexes(cls, values: list[int]) -> list[int]:
        if any(value < 0 for value in values) or len(set(values)) != len(values):
            raise ValueError("올바르지 않은 투표 항목입니다.")
        return sorted(values)


class PostLikeDTO(_CamelDTO):
    liked: bool
    like_count: int


class PostViewDTO(_CamelDTO):
    view_count: int


# 목록 한 건 (프론트 FeedPost)
class PostFeedItemDTO(_CamelDTO):
    id: int
    category: str
    author_tag: str
    prefix: str  # 말머리
    title: str
    author_name: str
    thumbnail_url: str | None = None
    like_count: int
    comment_count: int
    view_count: int
    created_at: datetime


class PostFeedListDTO(_CamelDTO):
    items: list[PostFeedItemDTO]
    page: int
    page_size: int
    total_count: int
    total_pages: int


class PostVideoOutDTO(_CamelDTO):
    url: str
    duration: int


class PostPollOptionOutDTO(_CamelDTO):
    text: str
    votes: int


class PostPollOutDTO(_CamelDTO):
    question: str
    options: list[PostPollOptionOutDTO]
    allow_multiple: bool
    voter_count: int  # 참여 인원 (복수 선택이면 득표 합계보다 적다)
    my_votes: list[int]


class PostDetailDTO(PostFeedItemDTO):
    content: str
    photos: list[str]
    videos: list[PostVideoOutDTO]
    place: PostPlaceDTO | None = None
    poll: PostPollOutDTO | None = None
    is_mine: bool = False  # 조회한 사람이 작성자인지


class PostEditPhotoDTO(_CamelDTO):
    id: int
    url: str


class PostEditVideoDTO(_CamelDTO):
    id: int  # 0 은 post_extras 에 저장된 예전 글의 동영상
    url: str
    duration: int


class PostEditPollDTO(_CamelDTO):
    question: str
    options: list[str]
    allow_multiple: bool
    locked: bool  # 참여한 사람이 있어 바꿀 수 없음


# 수정 화면에 채울 값
class PostEditDTO(_CamelDTO):
    id: int
    category: str
    prefix: str
    title: str
    content: str
    photos: list[PostEditPhotoDTO]
    videos: list[PostEditVideoDTO]
    place: PostPlaceDTO | None = None
    poll: PostEditPollDTO | None = None
