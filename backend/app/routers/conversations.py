from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import conversations as store

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
def list_conversations() -> list[dict]:
    return store.list_conversations()


@router.get("/{conversation_id}")
def get_conversation(conversation_id: UUID) -> dict:  # UUID: anything else is rejected with 422
    conversation = store.get_conversation(str(conversation_id))
    if conversation is None:
        raise _not_found()
    return conversation


@router.put("/{conversation_id}")
def save_conversation(conversation_id: UUID, request: SaveRequest) -> dict:
    return store.save_conversation(str(conversation_id), [m.model_dump() for m in request.messages])


@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: UUID, request: RenameRequest) -> dict:
    if not store.rename_conversation(str(conversation_id), request.title.strip()):
        raise _not_found()
    return {"id": str(conversation_id), "title": request.title.strip()}


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID) -> None:
    if not store.delete_conversation(str(conversation_id)):
        raise _not_found()
