"""The assistant's task list, kept per conversation (UX-009, ADR-0083).

`Planning` reads and changes the list through a `PlanStore`; this one keeps it
in `conversation_plans`, under the run's request context, so that it lasts
from run to run.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai_harness.planning import InMemoryPlanStore, PlanItem, TaskStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from mazzamurello_server.database import Identity, transaction

ITEMS: TypeAdapter[list[PlanItem]] = TypeAdapter(list[PlanItem])
# A conversation's task list, as a column of a query on `conversations`.
CONVERSATION_PLAN = "(SELECT p.items FROM conversation_plans p WHERE p.conversation_id = conversations.id) AS plan"


async def plan_items(connection: AsyncConnection, conversation_id: uuid.UUID) -> list[PlanItem]:
    """The conversation's task list, empty until the assistant writes one."""
    row = (
        await connection.execute(
            text("SELECT items FROM conversation_plans WHERE conversation_id = :id"), {"id": conversation_id}
        )
    ).one_or_none()
    return [] if row is None else ITEMS.validate_python(row.items)


def plan_steps(items: Any) -> list[dict[str, Any]]:
    """The task list as the API shows it, from its stored items."""
    if items is None:
        return []
    return [
        {"id": item.id, "content": item.content, "active_form": item.active_form, "status": item.status.value}
        for item in ITEMS.validate_python(items)
    ]


async def copy_plan(connection: AsyncConnection, source: uuid.UUID, target: uuid.UUID) -> None:
    """Give a fork the task list of its original (ADR-0083)."""
    await connection.execute(
        text(
            "INSERT INTO conversation_plans (conversation_id, tenant_id, owner_id, items, updated_at)"
            " SELECT :target, tenant_id, owner_id, items, now() FROM conversation_plans WHERE conversation_id = :source"
        ),
        {"source": source, "target": target},
    )


class ConversationPlanStore:
    """A `PlanStore` over one conversation's row; every change is written back at once."""

    def __init__(self, engine: AsyncEngine, identity: Identity, conversation_id: uuid.UUID) -> None:
        self._engine = engine
        self._identity = identity
        self._conversation_id = conversation_id

    async def _apply[T](self, change: Callable[[InMemoryPlanStore], Awaitable[T]], *, write: bool) -> T:
        async with transaction(self._engine, self._identity) as connection:
            store = InMemoryPlanStore()
            await store.set_items(await plan_items(connection, self._conversation_id))
            result = await change(store)
            if write:
                items = ITEMS.dump_python(await store.get_items(), mode="json")
                await connection.execute(
                    text(
                        "INSERT INTO conversation_plans (conversation_id, tenant_id, owner_id, items, updated_at)"
                        " VALUES (:id, :tenant_id, :owner_id, CAST(:items AS jsonb), now())"
                        " ON CONFLICT (conversation_id) DO UPDATE SET items = excluded.items, updated_at = now()"
                    ),
                    {
                        "id": self._conversation_id,
                        "tenant_id": self._identity.tenant_id,
                        "owner_id": self._identity.user_id,
                        "items": json.dumps(items),
                    },
                )
            return result

    async def get_items(self) -> list[PlanItem]:
        return await self._apply(lambda store: store.get_items(), write=False)

    async def set_items(self, items: list[PlanItem]) -> None:
        await self._apply(lambda store: store.set_items(items), write=True)

    async def get_item(self, item_id: str) -> PlanItem | None:
        return await self._apply(lambda store: store.get_item(item_id), write=False)

    async def add_item(self, item: PlanItem) -> PlanItem:
        return await self._apply(lambda store: store.add_item(item), write=True)

    async def update_item(
        self,
        item_id: str,
        *,
        content: str | None = None,
        status: TaskStatus | None = None,
        active_form: str | None = None,
        parent_id: str | None = None,
        depends_on: list[str] | None = None,
    ) -> PlanItem | None:
        return await self._apply(
            lambda store: store.update_item(
                item_id,
                content=content,
                status=status,
                active_form=active_form,
                parent_id=parent_id,
                depends_on=depends_on,
            ),
            write=True,
        )

    async def remove_item(self, item_id: str) -> bool:
        return await self._apply(lambda store: store.remove_item(item_id), write=True)
