import math
from datetime import datetime

from fastapi import Depends, HTTPException, status

from app.enum.post_enum import PostCategory, PostStatus, PostWriterType
from app.enum.s3_enum import S3Folder
from app.model.comment_model import Comment
from app.model.post_model import Post, KST
from app.model.post_extra_model import PostExtra, PostPhoto, PostVideo, PostPlaceCoord, PostPollSetting
from app.repository.community_repository import CommunityRepository, get_community_repository
from app.repository.redis_repository import RedisRepository, get_redis_repository
from app.schema.comment_schema import CommentCreateDTO, CommentItemDTO
from app.schema.post_schema import (
    CATEGORY_TO_ENUM, ENUM_TO_CATEGORY,
    PostCreateDTO, PostFeedItemDTO, PostFeedListDTO, PostDetailDTO,
    PostVideoOutDTO, PostPlaceDTO, PostPollOutDTO, PostPollOptionOutDTO, PostLikeDTO,
    PostUpdateDTO, PostEditDTO, PostEditPhotoDTO, PostEditVideoDTO, PostEditPollDTO,
)
from app.service.s3_service import S3Service, get_s3_service

VIEW_DEDUP_SECONDS = 60 * 60 * 24  # 같은 사람의 조회는 24시간에 1번만 센다
VIEW_KEY_PREFIX = "post_view:"
SECRET_COMMENT_TEXT = "비밀 댓글입니다."
LEGACY_VIDEO_ID = 0  # post_extras 에 저장된 예전 글의 동영상


WRITER_TYPE_LABELS = {
    PostWriterType.GUARDIAN.value: "보호자",
    PostWriterType.EXPECTANT_MOM.value: "예비맘",
    PostWriterType.PARENTING_MOM.value: "육아맘",
}


# DB 카테고리(PostCategory 값) 기준 작성자 타입
def _writer_type(db_category: str) -> str:
    if db_category == PostCategory.PARENTING_STORY.value:
        return PostWriterType.PARENTING_MOM.value
    return PostWriterType.EXPECTANT_MOM.value


# 화면에 보여줄 작성자 태그(한글)
def _author_tag(db_category: str) -> str:
    return WRITER_TYPE_LABELS[_writer_type(db_category)]


class CommunityService:
    def __init__(self, repo: CommunityRepository, redis_repo: RedisRepository, s3_service: S3Service):
        self.repo = repo
        self.redis_repo = redis_repo
        self.s3_service = s3_service

    # 첨부 파일의 서명 URL. key 는 클라이언트가 보낸 값이라 게시글 폴더만 서명하고, 그 밖에는 저장된 URL 을 그대로 쓴다.
    async def _view_url(self, key: str | None, url: str | None) -> str | None:
        if not key or not key.startswith(f"{S3Folder.POST.value}/"):
            return url
        return await self.s3_service.get_view_url(key)

    async def create_post(self, user_id: int, dto: PostCreateDTO) -> int:
        db_category = CATEGORY_TO_ENUM[dto.category].value
        post = Post(
            post_category=db_category,
            post_title=dto.title,
            post_content=dto.content,
            post_status=PostStatus.POSTING.value,
            post_writer_type=_writer_type(db_category),  # 카테고리 기준 작성자 타입
            user_id=user_id,
        )
        extra = PostExtra(
            post_prefix=dto.prefix,
            place_name=dto.place.name.strip() if dto.place else None,
            place_address=dto.place.address.strip() if dto.place else None,
            poll_question=dto.poll.question.strip() if dto.poll else None,
            poll_options=dto.poll.options if dto.poll else None,
        )
        attachments: list = [
            PostPhoto(photo_key=p.key, photo_url=p.url, thumb_url=p.thumb_url, photo_order=i)
            for i, p in enumerate(dto.photos)
        ]
        attachments += [
            PostVideo(video_key=v.key, video_url=v.url, video_duration=v.duration, video_order=i)
            for i, v in enumerate(dto.videos)
        ]
        if dto.place and dto.place.latitude is not None:
            attachments.append(PostPlaceCoord(latitude=dto.place.latitude, longitude=dto.place.longitude))
        if dto.poll:
            attachments.append(PostPollSetting(allow_multiple=dto.poll.allow_multiple))
        created = await self.repo.create_post(post, extra, attachments)
        return int(created.id)

    async def get_edit_post(self, post_id: int, user_id: int) -> PostEditDTO:
        await self._require_owner(post_id, user_id)
        post = (await self.repo.get_post(post_id))[0]
        extra = await self.repo.get_extra(post_id)

        photos = [
            PostEditPhotoDTO(id=p.id, url=await self._view_url(p.photo_key, p.photo_url))
            for p in await self.repo.get_photos(post_id)
        ]
        videos = [
            PostEditVideoDTO(id=v.id, url=await self._view_url(v.video_key, v.video_url), duration=v.video_duration)
            for v in await self.repo.get_videos(post_id)
        ]
        if extra and extra.video_url:
            url = await self._view_url(extra.video_key, extra.video_url)
            videos.insert(0, PostEditVideoDTO(id=LEGACY_VIDEO_ID, url=url, duration=extra.video_duration or 0))

        poll = None
        if extra and extra.poll_question and extra.poll_options:
            poll = PostEditPollDTO(
                question=extra.poll_question,
                options=extra.poll_options,
                allow_multiple=await self.repo.is_multiple_poll(post_id),
                locked=await self.repo.get_voter_count(post_id) > 0,
            )

        return PostEditDTO(
            id=post.id,
            category=ENUM_TO_CATEGORY.get(post.post_category, post.post_category),
            prefix=extra.post_prefix if extra else "질문",
            title=post.post_title,
            content=post.post_content,
            photos=photos,
            videos=videos,
            place=await self._get_place(post_id, extra),
            poll=poll,
        )

    # S3 의 파일은 지우지 않는다. key 는 클라이언트가 보낸 값이라, 그대로 삭제하면 다른 곳의 파일이 지워질 수 있다.
    async def update_post(self, post_id: int, user_id: int, dto: PostUpdateDTO) -> None:
        await self._require_owner(post_id, user_id)
        extra = await self.repo.get_extra(post_id)
        photos = await self.repo.get_photos(post_id)
        videos = await self.repo.get_videos(post_id)
        has_legacy_video = bool(extra and extra.video_url)

        keep_photos = set(dto.keep_photo_ids)
        keep_videos = set(dto.keep_video_ids)
        video_ids = {v.id for v in videos} | ({LEGACY_VIDEO_ID} if has_legacy_video else set())
        if not keep_photos <= {p.id for p in photos} or not keep_videos <= video_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="이 게시글의 첨부가 아닙니다.")

        question = dto.poll.question.strip() if dto.poll else None
        options = dto.poll.options if dto.poll else None
        allow_multiple = dto.poll.allow_multiple if dto.poll else False
        # 투표 결과는 항목 순번으로 저장되므로, 참여한 사람이 있으면 투표를 바꾸거나 뺄 수 없다.
        if await self.repo.get_voter_count(post_id) > 0:
            before = (extra.poll_question, extra.poll_options, await self.repo.is_multiple_poll(post_id))
            if (question, options, allow_multiple) != before:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="참여한 사람이 있는 투표는 수정할 수 없습니다.")

        extra_values = {
            "post_prefix": dto.prefix,
            "place_name": dto.place.name.strip() if dto.place else None,
            "place_address": dto.place.address.strip() if dto.place else None,
            "poll_question": question,
            "poll_options": options,
        }
        if has_legacy_video and LEGACY_VIDEO_ID not in keep_videos:
            extra_values.update(video_key=None, video_url=None, video_duration=None)

        # 새 첨부는 남긴 첨부 뒤에 붙인다.
        photo_start = max((p.photo_order for p in photos if p.id in keep_photos), default=-1) + 1
        video_start = max((v.video_order for v in videos if v.id in keep_videos), default=-1) + 1
        attachments: list = [
            PostPhoto(photo_key=p.key, photo_url=p.url, thumb_url=p.thumb_url, photo_order=i)
            for i, p in enumerate(dto.photos, start=photo_start)
        ]
        attachments += [
            PostVideo(video_key=v.key, video_url=v.url, video_duration=v.duration, video_order=i)
            for i, v in enumerate(dto.videos, start=video_start)
        ]
        if dto.place and dto.place.latitude is not None:
            attachments.append(PostPlaceCoord(latitude=dto.place.latitude, longitude=dto.place.longitude))
        if dto.poll:
            attachments.append(PostPollSetting(allow_multiple=allow_multiple))

        db_category = CATEGORY_TO_ENUM[dto.category].value
        post_values = {
            "post_category": db_category,
            "post_writer_type": _writer_type(db_category),
            "post_title": dto.title,
            "post_content": dto.content,
            "post_updated_at": datetime.now(KST),
        }
        await self.repo.update_post(post_id, post_values, extra_values, list(keep_photos), list(keep_videos), attachments)

    # 댓글·좋아요 기록이 남도록 행을 지우지 않고 상태만 바꾼다.
    async def delete_post(self, post_id: int, user_id: int) -> None:
        await self._require_owner(post_id, user_id)
        # 목록·상세는 게시중(POSTING)만 보여 주므로, 상태를 바꾸면 화면에서 사라진다.
        await self.repo.set_post_status(post_id, PostStatus.DELETED.value, datetime.now(KST))

    async def _get_place(self, post_id: int, extra: PostExtra | None) -> PostPlaceDTO | None:
        if not extra or not extra.place_name:
            return None
        coord = await self.repo.get_place_coord(post_id)
        return PostPlaceDTO(
            name=extra.place_name,
            address=extra.place_address or "",
            latitude=coord.latitude if coord else None,
            longitude=coord.longitude if coord else None,
        )

    async def list_posts(self, category: str | None, sort: str, q: str, page: int, size: int) -> PostFeedListDTO:
        db_category = CATEGORY_TO_ENUM[category].value if category in CATEGORY_TO_ENUM else category
        rows, total = await self.repo.list_posts(db_category, sort, q.strip(), page, size)
        items = [
            PostFeedItemDTO(
                id=post.id,
                category=ENUM_TO_CATEGORY.get(post.post_category, post.post_category),
                author_tag=_author_tag(post.post_category),
                # 부가 정보가 없는 예전 글은 상세 화면과 같은 기본값을 씁니다.
                prefix=prefix or "질문",
                title=post.post_title,
                author_name=nickname,
                # 100px 썸네일은 목록에서 흐려 보여 원본을 보낸다. 표시 크기에 맞추는 일은 프론트의 이미지 최적화가 맡는다.
                thumbnail_url=await self._view_url(photo_key, photo_url),
                like_count=post.post_like,
                comment_count=comments,
                view_count=views,
                created_at=post.post_created_at,
            )
            for post, nickname, comments, photo_key, photo_url, _, views, prefix in rows
        ]
        return PostFeedListDTO(
            items=items,
            page=page,
            page_size=size,
            total_count=total,
            total_pages=max(1, math.ceil(total / size)),
        )

    async def get_post(self, post_id: int, viewer_id: int | None) -> PostDetailDTO:
        row = await self.repo.get_post(post_id)
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="게시글을 찾을 수 없습니다.")
        post, nickname, comments, views = row

        extra = await self.repo.get_extra(post_id)
        photos = await self.repo.get_photos(post_id)

        poll = None
        if extra and extra.poll_question and extra.poll_options:
            counts = await self.repo.get_vote_counts(post_id)
            my_votes = await self.repo.get_my_votes(post_id, viewer_id) if viewer_id else []
            poll = PostPollOutDTO(
                question=extra.poll_question,
                options=[PostPollOptionOutDTO(text=text, votes=counts.get(i, 0)) for i, text in enumerate(extra.poll_options)],
                allow_multiple=await self.repo.is_multiple_poll(post_id),
                voter_count=await self.repo.get_voter_count(post_id),
                my_votes=my_votes,
            )

        photo_urls = [await self._view_url(p.photo_key, p.photo_url) for p in photos]
        videos = [
            PostVideoOutDTO(url=await self._view_url(v.video_key, v.video_url), duration=v.video_duration)
            for v in await self.repo.get_videos(post_id)
        ]
        # 동영상 1개만 지원하던 때의 글
        if extra and extra.video_url:
            url = await self._view_url(extra.video_key, extra.video_url)
            videos.insert(0, PostVideoOutDTO(url=url, duration=extra.video_duration or 0))

        return PostDetailDTO(
            id=post.id,
            category=ENUM_TO_CATEGORY.get(post.post_category, post.post_category),
            author_tag=_author_tag(post.post_category),
            title=post.post_title,
            author_name=nickname,
            thumbnail_url=photo_urls[0] if photo_urls else None,
            like_count=post.post_like,
            comment_count=comments,
            view_count=views,
            created_at=post.post_created_at,
            prefix=extra.post_prefix if extra else "질문",
            content=post.post_content,
            photos=photo_urls,
            videos=videos,
            place=await self._get_place(post_id, extra),
            poll=poll,
            is_mine=viewer_id == post.user_id,
        )

    async def _require_post(self, post_id: int) -> int:
        owner_id = await self.repo.get_post_owner_id(post_id)
        if owner_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="게시글을 찾을 수 없습니다.")
        return owner_id

    async def _require_owner(self, post_id: int, user_id: int) -> None:
        if await self._require_post(post_id) != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인이 쓴 게시글만 수정하거나 삭제할 수 있습니다.")

    # viewer: "user:{회원 id}" 또는 "guest:{브라우저 id}". 현재 조회수를 돌려준다.
    async def add_view(self, post_id: int, viewer: str) -> int:
        await self._require_post(post_id)
        key = f"{VIEW_KEY_PREFIX}{post_id}:{viewer}"
        # SET NX 한 번으로 확인과 기록을 함께 해서, 동시에 들어온 요청도 한 번만 센다.
        if await self.redis_repo.set_if_absent(key, "1", ex=VIEW_DEDUP_SECONDS):
            try:
                await self.repo.add_view(post_id)
            except Exception:
                await self.redis_repo.delete(key)
                raise
        return await self.repo.get_view_count(post_id)

    async def get_like(self, post_id: int, viewer_id: int | None) -> PostLikeDTO:
        await self._require_post(post_id)
        return PostLikeDTO(
            liked=await self.repo.is_liked(post_id, viewer_id) if viewer_id else False,
            like_count=await self.repo.get_like_count(post_id),
        )

    async def set_like(self, post_id: int, user_id: int, liked: bool) -> PostLikeDTO:
        await self._require_post(post_id)
        await self.repo.set_like(post_id, user_id, liked)
        return await self.get_like(post_id, user_id)

    # 비밀 댓글의 내용은 댓글 작성자와 게시글 작성자에게만 보여 준다.
    def _to_comment(self, comment: Comment, nickname: str, viewer_id: int | None, owner_id: int) -> CommentItemDTO:
        visible = not comment.comment_is_secret or viewer_id in (comment.user_id, owner_id)
        return CommentItemDTO(
            id=comment.id,
            author_name=nickname,
            content=comment.comment_content if visible else SECRET_COMMENT_TEXT,
            is_secret=comment.comment_is_secret,
            is_mine=viewer_id == comment.user_id,
            created_at=comment.comment_created_at,
        )

    async def list_comments(self, post_id: int, viewer_id: int | None) -> list[CommentItemDTO]:
        owner_id = await self._require_post(post_id)
        rows = await self.repo.list_comments(post_id)
        return [self._to_comment(comment, nickname, viewer_id, owner_id) for comment, nickname in rows]

    async def create_comment(self, post_id: int, user_id: int, dto: CommentCreateDTO) -> CommentItemDTO:
        owner_id = await self._require_post(post_id)
        comment, nickname = await self.repo.create_comment(
            Comment(post_id=post_id, user_id=user_id, comment_content=dto.content)
        )
        return self._to_comment(comment, nickname, user_id, owner_id)

    async def delete_comment(self, post_id: int, comment_id: int, user_id: int) -> None:
        await self._require_post(post_id)
        comment = await self.repo.get_comment(comment_id)
        if not comment or comment.post_id != post_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="댓글을 찾을 수 없습니다.")
        if comment.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인이 쓴 댓글만 삭제할 수 있습니다.")
        await self.repo.delete_comment(comment)

    async def vote(self, post_id: int, user_id: int, option_indexes: list[int]) -> PostDetailDTO:
        await self._require_post(post_id)  # 삭제된 글에는 투표할 수 없다
        extra = await self.repo.get_extra(post_id)
        if not extra or not extra.poll_options:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="투표가 없는 게시글입니다.")
        if max(option_indexes) >= len(extra.poll_options):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="올바르지 않은 투표 항목입니다.")
        if len(option_indexes) > 1 and not await self.repo.is_multiple_poll(post_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="한 항목만 선택할 수 있는 투표입니다.")
        if not await self.repo.add_vote(post_id, user_id, option_indexes):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 투표했습니다.")
        return await self.get_post(post_id, user_id)


def get_community_service(
    repo: CommunityRepository = Depends(get_community_repository),
    redis_repo: RedisRepository = Depends(get_redis_repository),
    s3_service: S3Service = Depends(get_s3_service),
):
    return CommunityService(repo, redis_repo, s3_service)
