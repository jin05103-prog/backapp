from datetime import datetime

from fastapi import Depends
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.postgresql import get_postgresql_db
from app.model.order_model import Order
from app.model.product_model import Product


class BabyshopRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # 기간 [since, until) 의 주문 수량이 많은 노출 상품. 주문이 없는 상품은 최신 등록순으로 뒤에 채웁니다.
    async def get_popular_products(self, since: datetime, until: datetime, limit: int) -> list[Product]:
        sales = (
            select(Order.product_id, func.sum(Order.order_quantity).label("quantity"))
            .where(
                Order.order_created_at >= since,
                Order.order_created_at < until,
                # 기준 시각 이후의 취소는 다음 갱신 때 반영해, 하루 동안 순위가 바뀌지 않게 합니다.
                or_(Order.order_cancelled_at.is_(None), Order.order_cancelled_at >= until),
            )
            .group_by(Order.product_id)
            .subquery()
        )
        result = await self.db.execute(
            select(Product)
            .outerjoin(sales, sales.c.product_id == Product.id)
            .where(Product.product_is_visible.is_(True))
            .order_by(func.coalesce(sales.c.quantity, 0).desc(), Product.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


def get_babyshop_repository(db: AsyncSession = Depends(get_postgresql_db)):
    return BabyshopRepository(db)
