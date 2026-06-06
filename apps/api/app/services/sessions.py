import json
import uuid

import redis.asyncio as aioredis


class SessionStore:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.ttl = 60 * 30

    async def create(self, user_id: str) -> str:
        sid = f"sess_{uuid.uuid4().hex[:12]}"
        await self.redis.setex(f"session:{sid}", self.ttl, user_id)
        return sid

    async def get_user(self, session_id: str) -> str | None:
        raw = await self.redis.get(f"session:{session_id}")
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw

    async def refresh(self, session_id: str, user_id: str) -> None:
        await self.redis.setex(f"session:{session_id}", self.ttl, user_id)

    async def append_message(self, session_id: str, role: str, content: str) -> None:
        key = f"messages:{session_id}"
        await self.redis.rpush(key, json.dumps({"role": role, "content": content}, ensure_ascii=False))
        await self.redis.expire(key, self.ttl)

    async def get_messages(self, session_id: str, limit: int = 20) -> list[dict]:
        key = f"messages:{session_id}"
        raw = await self.redis.lrange(key, -limit, -1)
        messages = []
        for item in raw:
            text = item.decode() if isinstance(item, bytes) else item
            messages.append(json.loads(text))
        return messages

    async def get_agent_context(self, session_id: str) -> dict | None:
        raw = await self.redis.get(f"agent_ctx:{session_id}")
        if not raw:
            return None
        text = raw.decode() if isinstance(raw, bytes) else raw
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    async def set_agent_context(self, session_id: str, ctx: dict) -> None:
        key = f"agent_ctx:{session_id}"
        await self.redis.setex(key, self.ttl, json.dumps(ctx, ensure_ascii=False))
