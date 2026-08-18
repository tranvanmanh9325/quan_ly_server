import logging
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.llm_router import LlmRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["9Router OpenAI Gateway"])


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = Field(default=None, description="Requested model ID or alias")
    messages: List[Dict[str, Any]] = Field(..., description="OpenAI chat messages list")
    temperature: Optional[float] = Field(default=0.1, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=1024, description="Max tokens for completion")
    tools: Optional[List[Dict[str, Any]]] = Field(default=None, description="List of available tools")
    tool_choice: Optional[Any] = Field(default="auto", description="Tool choice mode")
    stream: Optional[bool] = Field(default=False, description="Stream mode (not yet supported)")


@router.post("/v1/chat/completions")
@router.post("/api/ai/chat/completions")
async def openai_chat_completions(
    req: ChatCompletionRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    """
    Unified 9Router OpenAI-compatible chat completion gateway.
    Accepts standard OpenAI payloads and routes through Smart 3-Tier Fallback Pool.
    """
    llm_router: LlmRouter = getattr(request.app.state, "llm_router", None)
    if not llm_router or not llm_router.has_active_providers:
        raise HTTPException(
            status_code=503,
            detail="9Router has no available AI providers or all keys are in cooldown. Check .env configuration.",
        )

    # Compress user messages / system prompts with RTK if oversized
    compressed_messages = []
    for m in req.messages:
        content = m.get("content")
        if isinstance(content, str) and len(content) > 150:
            content = llm_router.rtk.compress(content, max_chars=3000, max_lines=35)
            m_copy = dict(m)
            m_copy["content"] = content
            compressed_messages.append(m_copy)
        else:
            compressed_messages.append(m)

    result = await llm_router.complete(
        messages=compressed_messages,
        tools=req.tools,
        tool_choice=req.tool_choice if isinstance(req.tool_choice, str) else "auto",
        temperature=req.temperature or 0.1,
        max_tokens=req.max_tokens or 1024,
        requested_model=req.model,
    )

    if not result:
        raise HTTPException(
            status_code=502,
            detail="9Router was unable to complete the request across all active provider tiers.",
        )

    return result


@router.get("/v1/models")
@router.get("/api/ai/models")
async def list_openai_models(request: Request):
    """Returns available models across active 9Router providers."""
    llm_router: LlmRouter = getattr(request.app.state, "llm_router", None)
    model_entries = [
        {
            "id": "openai/gpt-oss-120b",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "groq",
            "permission": [],
            "root": "openai/gpt-oss-120b",
        },
        {
            "id": "qwen/qwen3.6-27b",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "groq",
            "permission": [],
            "root": "qwen/qwen3.6-27b",
        },
        {
            "id": "llama-3.1-8b-instant",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "groq",
            "permission": [],
            "root": "llama-3.1-8b-instant",
        },
        {
            "id": "nvidia/nemotron-3-super-120b-a12b:free",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "openrouter",
            "permission": [],
            "root": "nvidia/nemotron-3-super-120b-a12b:free",
        },
        {
            "id": "openrouter/free",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "openrouter",
            "permission": [],
            "root": "openrouter/free",
        },
    ]

    return {
        "object": "list",
        "data": model_entries,
    }


@router.get("/v1/status")
@router.get("/api/ai/router/status")
async def get_router_status(request: Request):
    """Returns real-time 9Router metrics, pool health, and RTK token savings."""
    llm_router: LlmRouter = getattr(request.app.state, "llm_router", None)
    if not llm_router:
        return {"status": "uninitialized", "providers": []}
    return llm_router.get_status()
