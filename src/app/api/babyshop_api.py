from fastapi import APIRouter, Depends
from app.schema.common_schema import ApiResponseDTO
from app.schema.product_schema import PopularProductDTO
from app.service.babyshop_service import BabyshopService, get_babyshop_service

router = APIRouter()


# 오늘의 인기상품 (매일 09:00 KST 기준)
# GET /babyshop/popular-products
@router.get("/popular-products", summary="오늘의 인기상품", response_model=ApiResponseDTO[list[PopularProductDTO]])
async def get_popular_products(service: BabyshopService = Depends(get_babyshop_service)):
    return ApiResponseDTO(success=True, message="오늘의 인기상품 조회 성공", data=await service.get_popular_products())
