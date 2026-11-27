import re
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, Response, HTTPException, status

from app.dependency.auth_dependency import get_current_user
from app.schema.comment_schema import CommentCreateDTO, CommentItemDTO
from app.schema.common_schema import ApiResponseDTO
from app.schema.post_schema import (
    PostCreateDTO, PostUpdateDTO, PostEditDTO, PostVoteDTO, PostFeedListDTO, PostDetailDTO, PostLikeDTO, PostViewDTO,
    POST_CATEGORIES,
)
from app.schema.user_schema import UserClaimDTO
from app.service.community_service import CommunityService, get_community_service

router = APIRouter()

VISITOR_COOKIE = "visitor_id"  # 비로그인 조회수 중복 방지용 브라우저 id
VISITOR_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


# 로그인한 경우에만 사용자 id 를 돌려준다 (조회처럼 비로그인도 허용하는 API 용)
def get_optional_user_id(request: Request) -> int | None:
    try:
        return get_current_user(request).id
    except HTTPException:
        return None


# 게시글 등록
# POST /communities/posts
@router.post("/posts", summary="게시글 등록", response_model=ApiResponseDTO[PostDetailDTO], status_code=status.HTTP_201_CREATED)
async def create_post(
    dto: PostCreateDTO,
    user: UserClaimDTO = Depends(get_current_user),
    service: CommunityService = Depends(get_community_service),
):
    post_id = await service.create_post(user.id, dto)
    return ApiResponseDTO(success=True, message="게시글 등록 성공", data=await service.get_post(post_id, user.id))


# 게시글 목록
# GET /communities/posts?category=all&sort=latest&q=&page=1&size=10
@router.get("/posts", summary="게시글 목록", response_model=ApiResponseDTO[PostFeedListDTO])
async def list_posts(
    category: str = Query("all"),
    sort: Literal["popular", "latest"] = Query("latest"),
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=50),
    service: CommunityService = Depends(get_community_service),
):
    if category != "all" and category not in POST_CATEGORIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="올바르지 않은 게시판입니다.")
    data = await service.list_posts(None if category == "all" else category, sort, q, page, size)
    return ApiResponseDTO(success=True, message="게시글 목록 조회 성공", data=data)


# 게시글 상세
# GET /communities/posts/{post_id}
@router.get("/posts/{post_id}", summary="게시글 상세", response_model=ApiResponseDTO[PostDetailDTO])
async def get_post(
    post_id: int,
    viewer_id: int | None = Depends(get_optional_user_id),
    service: CommunityService = Depends(get_community_service),
):
    return ApiResponseDTO(success=True, message="게시글 조회 성공", data=await service.get_post(post_id, viewer_id))


# 수정 화면에 채울 값 (작성자 본인)
# GET /communities/posts/{post_id}/edit
@router.get("/posts/{post_id}/edit", summary="게시글 수정 정보", response_model=ApiResponseDTO[PostEditDTO])
async def get_edit_post(
    post_id: int,
    user: UserClaimDTO = Depends(get_current_user),
    service: CommunityService = Depends(get_community_service),
):
    return ApiResponseDTO(success=True, message="게시글 수정 정보 조회 성공", data=await service.get_edit_post(post_id, user.id))


# 게시글 수정 (작성자 본인)
# PUT /communities/posts/{post_id}
@router.put("/posts/{post_id}", summary="게시글 수정", response_model=ApiResponseDTO[PostDetailDTO])
async def update_post(
    post_id: int,
    dto: PostUpdateDTO,
    user: UserClaimDTO = Depends(get_current_user),
    service: CommunityService = Depends(get_community_service),
):
    await service.update_post(post_id, user.id, dto)
    return ApiResponseDTO(success=True, message="게시글 수정 성공", data=await service.get_post(post_id, user.id))


# 게시글 삭제 (작성자 본인)
# DELETE /communities/posts/{post_id}
@router.delete("/posts/{post_id}", summary="게시글 삭제", response_model=ApiResponseDTO)
async def delete_post(
    post_id: int,
    user: UserClaimDTO = Depends(get_current_user),
    service: CommunityService = Depends(get_community_service),
):
    await service.delete_post(post_id, user.id)
    return ApiResponseDTO(success=True, message="게시글 삭제 성공")


# 조회수 증가 (상세 화면을 열 때 호출). 같은 회원·브라우저는 24시간에 1번만 센다.
# POST /communities/posts/{post_id}/view
@router.post("/posts/{post_id}/view", summary="조회수 증가", response_model=ApiResponseDTO[PostViewDTO])
async def add_view(
    post_id: int,
    request: Request,
    response: Response,
    viewer_id: int | None = Depends(get_optional_user_id),
    service: CommunityService = Depends(get_community_service),
):
    guest_id = None
    if viewer_id:
        viewer = f"user:{viewer_id}"
    else:
        saved = request.cookies.get(VISITOR_COOKIE, "")
        guest_id = saved if VISITOR_ID_PATTERN.fullmatch(saved) else uuid4().hex
        viewer = f"guest:{guest_id}"

    view_count = await service.add_view(post_id, viewer)
    if guest_id:
        # secure=False 는 로그인 쿠키(auth_api)와 같은 설정. HTTPS 배포에서는 함께 바꾼다.
        response.set_cookie(key=VISITOR_COOKIE, value=guest_id, httponly=True, secure=False, samesite="lax", max_age=60 * 60 * 24 * 365)
    return ApiResponseDTO(success=True, message="조회수 반영 성공", data=PostViewDTO(view_count=view_count))


# 좋아요 상태
# GET /communities/posts/{post_id}/like
@router.get("/posts/{post_id}/like", summary="좋아요 상태", response_model=ApiResponseDTO[PostLikeDTO])
async def get_like(
    post_id: int,
    viewer_id: int | None = Depends(get_optional_user_id),
    service: CommunityService = Depends(get_community_service),
):
    return ApiResponseDTO(success=True, message="좋아요 상태 조회 성공", data=await service.get_like(post_id, viewer_id))


# 좋아요 등록
# PUT /communities/posts/{post_id}/like
@router.put("/posts/{post_id}/like", summary="좋아요 등록", response_model=ApiResponseDTO[PostLikeDTO])
async def like_post(
    post_id: int,
    user: UserClaimDTO = Depends(get_current_user),
    service: CommunityService = Depends(get_community_service),
):
    return ApiResponseDTO(success=True, message="좋아요 등록 성공", data=await service.set_like(post_id, user.id, True))


# 좋아요 취소
# DELETE /communities/posts/{post_id}/like
@router.delete("/posts/{post_id}/like", summary="좋아요 취소", response_model=ApiResponseDTO[PostLikeDTO])
async def unlike_post(
    post_id: int,
    user: UserClaimDTO = Depends(get_current_user),
    service: CommunityService = Depends(get_community_service),
):
    return ApiResponseDTO(success=True, message="좋아요 취소 성공", data=await service.set_like(post_id, user.id, False))


# 댓글 목록
# GET /communities/posts/{post_id}/comments
@router.get("/posts/{post_id}/comments", summary="댓글 목록", response_model=ApiResponseDTO[list[CommentItemDTO]])
async def list_comments(
    post_id: int,
    viewer_id: int | None = Depends(get_optional_user_id),
    service: CommunityService = Depends(get_community_service),
):
    return ApiResponseDTO(success=True, message="댓글 목록 조회 성공", data=await service.list_comments(post_id, viewer_id))


# 댓글 작성
# POST /communities/posts/{post_id}/comments
@router.post("/posts/{post_id}/comments", summary="댓글 작성", response_model=ApiResponseDTO[CommentItemDTO], status_code=status.HTTP_201_CREATED)
async def create_comment(
    post_id: int,
    dto: CommentCreateDTO,
    user: UserClaimDTO = Depends(get_current_user),
    service: CommunityService = Depends(get_community_service),
):
    return ApiResponseDTO(success=True, message="댓글 작성 성공", data=await service.create_comment(post_id, user.id, dto))


# 댓글 삭제 (본인 댓글)
# DELETE /communities/posts/{post_id}/comments/{comment_id}
@router.delete("/posts/{post_id}/comments/{comment_id}", summary="댓글 삭제", response_model=ApiResponseDTO)
async def delete_comment(
    post_id: int,
    comment_id: int,
    user: UserClaimDTO = Depends(get_current_user),
    service: CommunityService = Depends(get_community_service),
):
    await service.delete_comment(post_id, comment_id, user.id)
    return ApiResponseDTO(success=True, message="댓글 삭제 성공")


# 투표 (회원당 1회)
# POST /communities/posts/{post_id}/vote
@router.post("/posts/{post_id}/vote", summary="투표하기", response_model=ApiResponseDTO[PostDetailDTO])
async def vote(
    post_id: int,
    dto: PostVoteDTO,
    user: UserClaimDTO = Depends(get_current_user),
    service: CommunityService = Depends(get_community_service),
):
    return ApiResponseDTO(success=True, message="투표 성공", data=await service.vote(post_id, user.id, dto.option_indexes))
