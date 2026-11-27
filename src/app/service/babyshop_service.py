from datetime import datetime, timedelta, timezone

from fastapi import Depends

from app.repository.babyshop_repository import BabyshopRepository, get_babyshop_repository
from app.schema.product_schema import PopularProductDTO

KST = timezone(timedelta(hours=9))  # UTC+9
REFRESH_HOUR = 9  # 매일 09:00 KST 갱신
SALES_WINDOW = timedelta(days=1)  # 기준 시각 직전 24시간의 주문을 집계
POPULAR_PRODUCT_LIMIT = 5


# 가장 최근에 지난 09:00 KST
def popular_base_time(now: datetime) -> datetime:
    local = now.astimezone(KST)
    base = local.replace(hour=REFRESH_HOUR, minute=0, second=0, microsecond=0)
    return base if local >= base else base - timedelta(days=1)


class BabyshopService:
    def __init__(self, repo: BabyshopRepository):
        self.repo = repo

    async def get_popular_products(self) -> list[PopularProductDTO]:
        until = popular_base_time(datetime.now(KST))
        products = await self.repo.get_popular_products(until - SALES_WINDOW, until, POPULAR_PRODUCT_LIMIT)
        return [
            PopularProductDTO(
                id=product.id,
                rank=rank,
                name=product.name,
                discount_rate=0,  # products 테이블에 할인 정보가 없습니다.
                price=product.product_price,
                thumbnail_url=product.product_image_url,
            )
            for rank, product in enumerate(products, start=1)
        ]


def get_babyshop_service(repo: BabyshopRepository = Depends(get_babyshop_repository)):
    return BabyshopService(repo)
