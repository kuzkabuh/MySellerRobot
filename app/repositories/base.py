"""version: 1.0.1
description: Base repository with common CRUD operations.
updated: 2026-05-15
"""

from typing import Any, cast

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base


class BaseRepository[ModelType: Base]:
    """Base repository with common database operations."""

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, id: int) -> ModelType | None:
        """Get entity by ID."""
        model_id = cast(Any, self.model).id
        result = await self.session.execute(select(self.model).where(model_id == id))
        return result.scalar_one_or_none()

    async def get_all(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        order_by: Any = None,
    ) -> list[ModelType]:
        """Get all entities with optional pagination."""
        query = select(self.model)
        if order_by is not None:
            query = query.order_by(order_by)
        if limit is not None:
            query = query.limit(limit)
        if offset is not None:
            query = query.offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, **kwargs: Any) -> ModelType:
        """Create new entity."""
        entity = self.model(**kwargs)
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def update_by_id(self, id: int, **kwargs: Any) -> ModelType | None:
        """Update entity by ID."""
        entity = await self.get_by_id(id)
        if entity is None:
            return None
        for key, value in kwargs.items():
            setattr(entity, key, value)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete_by_id(self, id: int) -> bool:
        """Delete entity by ID."""
        model_id = cast(Any, self.model).id
        result = await self.session.execute(delete(self.model).where(model_id == id))
        return int(getattr(result, "rowcount", 0)) > 0

    async def exists(self, **filters: Any) -> bool:
        """Check if entity exists with given filters."""
        query = select(cast(Any, self.model).id)
        for key, value in filters.items():
            query = query.where(getattr(self.model, key) == value)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None

    async def count(self, **filters: Any) -> int:
        """Count entities with given filters."""
        query: Select[tuple[int]] = select(func.count(cast(Any, self.model).id))
        for key, value in filters.items():
            query = query.where(getattr(self.model, key) == value)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def find_one(self, **filters: Any) -> ModelType | None:
        """Find one entity by filters."""
        query = select(self.model)
        for key, value in filters.items():
            query = query.where(getattr(self.model, key) == value)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def find_many(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        order_by: Any = None,
        **filters: Any,
    ) -> list[ModelType]:
        """Find entities by filters with optional pagination."""
        query = select(self.model)
        for key, value in filters.items():
            query = query.where(getattr(self.model, key) == value)
        if order_by is not None:
            query = query.order_by(order_by)
        if limit is not None:
            query = query.limit(limit)
        if offset is not None:
            query = query.offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def bulk_create(self, entities: list[dict[str, Any]]) -> list[ModelType]:
        """Bulk create entities."""
        instances = [self.model(**data) for data in entities]
        self.session.add_all(instances)
        await self.session.flush()
        for instance in instances:
            await self.session.refresh(instance)
        return instances

    async def bulk_update(self, updates: list[dict[str, Any]]) -> int:
        """Bulk update entities. Each dict must contain 'id' key."""
        if not updates:
            return 0
        result = await self.session.execute(update(self.model), updates)
        return int(getattr(result, "rowcount", 0))
