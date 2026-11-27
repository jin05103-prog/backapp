from app.infrastructure.redis import get_redis_db
from redis.asyncio import Redis
from fastapi import Depends
from sqlalchemy import insert, select, update, delete, func, exists

class RedisRepository:

    # 생성자 주입
    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client

    async def set(self, key: str, value: str, ex: int = 3600) -> None:
        await self.redis_client.set(key, value, ex)

    # 키가 없을 때만 저장한다. 새로 저장했으면 True
    async def set_if_absent(self, key: str, value: str, ex: int = 3600) -> bool:
        return bool(await self.redis_client.set(key, value, ex=ex, nx=True))

    async def get(self, key: str) -> str | None:
        return await self.redis_client.get(key)

    async def getdel(self, key: str) -> str | None:
        return await self.redis_client.getdel(key)

    async def exists(self, key: str) -> bool:
        result = await self.redis_client.exists(key)
        return result > 0

    async def delete(self, key: str) -> None:
        await self.redis_client.delete(key)


# 주입 팩토리 메서드
def get_redis_repository(redis_client: Redis = Depends(get_redis_db)):
    return RedisRepository(redis_client)