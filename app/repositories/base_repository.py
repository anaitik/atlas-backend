"""
Generic async CRUD repository for Beanie documents.
"""

from __future__ import annotations

from typing import Any, Generic, Optional, Type, TypeVar

from beanie import Document

T = TypeVar("T", bound=Document)


class BaseRepository(Generic[T]):
    """
    Generic repository providing base CRUD operations for Beanie documents.
    Domain repositories extend this with domain-specific queries.
    """

    def __init__(self, model: Type[T]):
        self.model = model

    async def get_by_id(self, entity_id: str) -> Optional[T]:
        """Fetch a single document by ID."""
        return await self.model.get(entity_id)

    async def get_one(self, **filters: Any) -> Optional[T]:
        """Fetch a single document matching filters."""
        return await self.model.find_one(filters)

    async def get_many(
        self,
        filters: Optional[dict[str, Any]] = None,
        skip: int = 0,
        limit: int = 20,
        sort: Optional[str] = None,
    ) -> list[T]:
        """Fetch multiple documents with pagination and optional sorting."""
        query = self.model.find(filters or {})
        if sort:
            # Prefix with "-" for descending, e.g. "-created_at"
            query = query.sort(sort)
        return await query.skip(skip).limit(limit).to_list()

    async def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        """Count documents matching filters."""
        return await self.model.find(filters or {}).count()

    async def create(self, document: T) -> T:
        """Insert a new document."""
        await document.insert()
        return document

    async def update(self, document: T) -> T:
        """Save changes to an existing document."""
        await document.save_with_timestamp()
        return document

    async def delete(self, entity_id: str) -> bool:
        """Hard-delete a document by ID."""
        doc = await self.get_by_id(entity_id)
        if doc:
            await doc.delete()
            return True
        return False

    async def paginated(
        self,
        filters: Optional[dict[str, Any]] = None,
        page: int = 1,
        page_size: int = 20,
        sort: str = "-created_at",
    ) -> tuple[list[T], int]:
        """Return (items, total) for paginated queries."""
        skip = (page - 1) * page_size
        total = await self.count(filters)
        items = await self.get_many(filters, skip=skip, limit=page_size, sort=sort)
        return items, total
