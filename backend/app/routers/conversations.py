from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import conversations as store
from app.auth.deps import CurrentAccess

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class SavedMessage(BaseModel):
    """role and content are checked; display data (steps, sources, tables) is stored as sent."""

    model_config = ConfigDict(extra="allow")
    role: Literal["user", "assistant"]
    content: str = Field(max_length=100_000)


class SaveRequest(BaseModel):
    messages: list[SavedMessage] = Field(max_length=500)


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Conversation not found")


@router.get("")
def list_conversations(access: CurrentAccess) -> list[dict]:
    return store.list_conversations(access.user_id)


@router.get("/{conversation_id}")
def get_conversation(access: CurrentAccess, conversation_id: UUID) -> dict:
    conversation = store.get_conversation(access.user_id, str(conversation_id))
    if conversation is None:
        raise _not_found()
    return conversation


@router.put("/{conversation_id}")
def save_conversation(access: CurrentAccess, conversation_id: UUID, request: SaveRequest) -> dict:
    saved = store.save_conversation(
        access.user_id, str(conversation_id), [m.model_dump() for m in request.messages]
    )
    if saved is None:
        raise _not_found()  # the id belongs to another user
    return saved


@router.patch("/{conversation_id}")
def rename_conversation(access: CurrentAccess, conversation_id: UUID, request: RenameRequest) -> dict:
    if not store.rename_conversation(access.user_id, str(conversation_id), request.title.strip()):
        raise _not_found()
    return {"id": str(conversation_id), "title": request.title.strip()}


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(access: CurrentAccess, conversation_id: UUID) -> None:
    if not store.delete_conversation(access.user_id, str(conversation_id)):
        raise _not_found()
