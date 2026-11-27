from datetime import datetime

from fastapi import Depends
from sqlalchemy import select, update, delete, func, or_, literal, union_all
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.postgresql import get_postgresql_db
from app.enum.post_enum import PostStatus
from app.model.post_model import Post
from app.model.comment_model import Comment
from app.model.user_model import User
from app.model.post_extra_model import (
    PostExtra, PostPhoto, PostVideo, PostPlaceCoord, PostPollSetting, PostLike, PostStat, PostPollVote, PostPollExtraChoice,
)

# 인기 점수 = 좋아요 수 * POPULAR_LIKE_WEIGHT + 조회수
POPULAR_LIKE_WEIGHT = 10


def _view_count():
    views = select(PostStat.view_count).where(PostStat.post_id == Post.id).correlate(Post).scalar_subquery()
    return func.coalesce(views, 0)


def _comment_count():
    return select(func.count(Comment.id)).where(Comment.post_id == Post.id).correlate(Post).scalar_subquery()


class CommunityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # 게시글 + 부가 정보 + 첨부(사진, 동영상, 장소 좌표, 투표 설정)를 한 트랜잭션으로 저장
    async def create_post(self, post: Post, extra: PostExtra, attachments: list) -> Post:
        try:
            self.db.add(post)
            await self.db.flush()  # post.id 확보
            for row in [extra, *attachments]:
                row.post_id = post.id
                self.db.add(row)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return post

    # 게시글 수정을 한 트랜잭션으로 반영한다. 남기지 않는 사진·동영상 행은 지우고, 장소 좌표·투표 설정은 다시 저장한다.
    async def update_post(
        self, post_id: int, post_values: dict, extra_values: dict,
        keep_photo_ids: list[int], keep_video_ids: list[int], attachments: list,
    ) -> None:
        try:
            await self.db.execute(update(Post).where(Post.id == post_id).values(**post_values))
            extra = await self.db.get(PostExtra, post_id)
            if not extra:
                extra = PostExtra(post_id=post_id)
                self.db.add(extra)
            for key, value in extra_values.items():
                setattr(extra, key, value)
            await self.db.execute(delete(PostPhoto).where(PostPhoto.post_id == post_id, PostPhoto.id.not_in(keep_photo_ids)))
            await self.db.execute(delete(PostVideo).where(PostVideo.post_id == post_id, PostVideo.id.not_in(keep_video_ids)))
            await self.db.execute(delete(PostPlaceCoord).where(PostPlaceCoord.post_id == post_id))
            await self.db.execute(delete(PostPollSetting).where(PostPollSetting.post_id == post_id))
            for row in attachments:
                row.post_id = post_id
                self.db.add(row)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def set_post_status(self, post_id: int, post_status: str, updated_at: datetime) -> None:
        try:
            await self.db.execute(
                update(Post).where(Post.id == post_id).values(post_status=post_status, post_updated_at=updated_at)
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def list_posts(self, category: str | None, sort: str, q: str, page: int, size: int):
        def first_photo(column):
            return (
                select(column)
                .where(PostPhoto.post_id == Post.id)
                .order_by(PostPhoto.photo_order, PostPhoto.id)
                .limit(1)
                .correlate(Post)
                .scalar_subquery()
            )

        prefix = select(PostExtra.post_prefix).where(PostExtra.post_id == Post.id).correlate(Post).scalar_subquery()

        conditions = [Post.post_status == PostStatus.POSTING.value]
        if category:
            conditions.append(Post.post_category == category)
        if q:
            like = f"%{q}%"
            conditions.append(or_(Post.post_title.ilike(like), Post.post_content.ilike(like)))

        total = (await self.db.execute(select(func.count()).select_from(Post).where(*conditions))).scalar_one()

        if sort == "popular":
            score = Post.post_like * POPULAR_LIKE_WEIGHT + _view_count()
            order = [score.desc(), Post.post_created_at.desc(), Post.id.desc()]
        else:
            order = [Post.post_created_at.desc(), Post.id.desc()]

        rows = (
            await self.db.execute(
                select(
                    Post, User.user_nickname, _comment_count(),
                    first_photo(PostPhoto.photo_key), first_photo(PostPhoto.photo_url), first_photo(PostPhoto.thumb_url),
                    _view_count(),
                    prefix,
                )
                .join(User, User.id == Post.user_id)
                .where(*conditions)
                .order_by(*order)
                .offset((page - 1) * size)
                .limit(size)
            )
        ).all()
        return rows, total

    async def get_post(self, post_id: int):
        return (
            await self.db.execute(
                select(Post, User.user_nickname, _comment_count(), _view_count())
                .join(User, User.id == Post.user_id)
                .where(Post.id == post_id, Post.post_status == PostStatus.POSTING.value)
            )
        ).first()

    # 조회수 1 증가. 게시중인 글이 없으면 False
    async def add_view(self, post_id: int) -> bool:
        published = select(Post.id, literal(1)).where(Post.id == post_id, Post.post_status == PostStatus.POSTING.value)
        statement = (
            insert(PostStat)
            .from_select(["post_id", "view_count"], published)
            .on_conflict_do_update(index_elements=[PostStat.post_id], set_={"view_count": PostStat.view_count + 1})
            .returning(PostStat.post_id)
        )
        added = (await self.db.execute(statement)).first() is not None
        await self.db.commit()
        return added

    async def get_view_count(self, post_id: int) -> int:
        result = await self.db.execute(select(PostStat.view_count).where(PostStat.post_id == post_id))
        return result.scalar_one_or_none() or 0

    # 게시중인 글의 작성자 id. 글이 없으면 None
    async def get_post_owner_id(self, post_id: int) -> int | None:
        result = await self.db.execute(select(Post.user_id).where(Post.id == post_id, Post.post_status == PostStatus.POSTING.value))
        return result.scalar_one_or_none()

    async def get_like_count(self, post_id: int) -> int:
        result = await self.db.execute(select(Post.post_like).where(Post.id == post_id))
        return result.scalar_one()

    async def is_liked(self, post_id: int, user_id: int) -> bool:
        result = await self.db.execute(select(PostLike.id).where(PostLike.post_id == post_id, PostLike.user_id == user_id))
        return result.first() is not None

    # 좋아요를 원하는 상태로 맞춘다. 같은 요청을 반복해도 개수는 한 번만 바뀐다.
    async def set_like(self, post_id: int, user_id: int, liked: bool) -> None:
        if liked:
            statement = (
                insert(PostLike)
                .values(post_id=post_id, user_id=user_id)
                .on_conflict_do_nothing(index_elements=[PostLike.post_id, PostLike.user_id])
                .returning(PostLike.id)
            )
        else:
            statement = delete(PostLike).where(PostLike.post_id == post_id, PostLike.user_id == user_id).returning(PostLike.id)

        try:
            if (await self.db.execute(statement)).first() is not None:
                # DB 에서 더하고 빼야 동시에 눌러도 개수가 어긋나지 않는다.
                count = Post.post_like + 1 if liked else func.greatest(Post.post_like - 1, 0)
                await self.db.execute(update(Post).where(Post.id == post_id).values(post_like=count))
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def list_comments(self, post_id: int):
        result = await self.db.execute(
            select(Comment, User.user_nickname)
            .join(User, User.id == Comment.user_id)
            .where(Comment.post_id == post_id)
            .order_by(Comment.comment_created_at.desc(), Comment.id.desc())
        )
        return result.all()

    async def create_comment(self, comment: Comment) -> tuple[Comment, str]:
        try:
            self.db.add(comment)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        nickname = (await self.db.execute(select(User.user_nickname).where(User.id == comment.user_id))).scalar_one()
        return comment, nickname

    async def get_comment(self, comment_id: int) -> Comment | None:
        return await self.db.get(Comment, comment_id)

    async def delete_comment(self, comment: Comment) -> None:
        try:
            await self.db.delete(comment)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def get_extra(self, post_id: int) -> PostExtra | None:
        return await self.db.get(PostExtra, post_id)

    async def get_photos(self, post_id: int) -> list[PostPhoto]:
        result = await self.db.execute(
            select(PostPhoto).where(PostPhoto.post_id == post_id).order_by(PostPhoto.photo_order, PostPhoto.id)
        )
        return list(result.scalars().all())

    async def get_videos(self, post_id: int) -> list[PostVideo]:
        result = await self.db.execute(
            select(PostVideo).where(PostVideo.post_id == post_id).order_by(PostVideo.video_order, PostVideo.id)
        )
        return list(result.scalars().all())

    async def get_place_coord(self, post_id: int) -> PostPlaceCoord | None:
        return await self.db.get(PostPlaceCoord, post_id)

    async def is_multiple_poll(self, post_id: int) -> bool:
        setting = await self.db.get(PostPollSetting, post_id)
        return bool(setting and setting.allow_multiple)

    async def get_vote_counts(self, post_id: int) -> dict[int, int]:
        choices = union_all(
            select(PostPollVote.option_index).where(PostPollVote.post_id == post_id),
            select(PostPollExtraChoice.option_index).where(PostPollExtraChoice.post_id == post_id),
        ).subquery()
        result = await self.db.execute(select(choices.c.option_index, func.count()).group_by(choices.c.option_index))
        return {index: count for index, count in result.all()}

    async def get_voter_count(self, post_id: int) -> int:
        result = await self.db.execute(select(func.count()).select_from(PostPollVote).where(PostPollVote.post_id == post_id))
        return result.scalar_one()

    async def get_my_votes(self, post_id: int, user_id: int) -> list[int]:
        result = await self.db.execute(
            union_all(
                select(PostPollVote.option_index).where(PostPollVote.post_id == post_id, PostPollVote.user_id == user_id),
                select(PostPollExtraChoice.option_index).where(PostPollExtraChoice.post_id == post_id, PostPollExtraChoice.user_id == user_id),
            )
        )
        return sorted(result.scalars().all())

    # 회원당 1회 참여. 이미 투표했으면 False
    async def add_vote(self, post_id: int, user_id: int, option_indexes: list[int]) -> bool:
        first, *rest = option_indexes
        try:
            # post_poll_votes 의 (post_id, user_id) 유일 제약이 중복 참여를 막는다.
            self.db.add(PostPollVote(post_id=post_id, user_id=user_id, option_index=first))
            await self.db.flush()
            for index in rest:
                self.db.add(PostPollExtraChoice(post_id=post_id, user_id=user_id, option_index=index))
            await self.db.commit()
            return True
        except IntegrityError:
            await self.db.rollback()
            return False


def get_community_repository(db: AsyncSession = Depends(get_postgresql_db)):
    return CommunityRepository(db)
