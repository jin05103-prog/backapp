from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# VO (ERD 테이블: products / 상품)
class ProductVO(BaseModel):
    id: int

    name: str
    product_category: str
    product_description: str | None = None
    product_image_url: str | None = None
    product_seller: str
    product_external_url: str | None = None
    product_is_visible: bool
    product_price: int


# 오늘의 인기상품 한 건 (프론트 PopularProduct)
class PopularProductDTO(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: int
    rank: int
    name: str
    discount_rate: int
    price: int
    thumbnail_url: str | None = None
