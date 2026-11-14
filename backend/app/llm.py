from collections.abc import AsyncIterator

from ollama import AsyncClient

from app.config import settings
from app.schemas import ChatMessage

SYSTEM_PROMPT = "You are a helpful assistant. Answer clearly and concisely."

# One client for the whole app: it reuses the HTTP connection to Ollama.
_client = AsyncClient(host=settings.ollama_host)


async def stream_chat(messages: list[ChatMessage]) -> AsyncIterator[dict]:
    """Send the conversation to Ollama and yield events as the answer streams in."""
    conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
    conversation += [m.model_dump() for m in messages]

    stream = await _client.chat(
        model=settings.chat_model,
        messages=conversation,
        stream=True,
        think=settings.think,
    )

    async for chunk in stream:
        if chunk.message.thinking:
            yield {"type": "thinking", "content": chunk.message.thinking}
        if chunk.message.content:
            yield {"type": "token", "content": chunk.message.content}