from fastapi import APIRouter
from app.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return {
        "status": "UP",
        "service": "ai-agent-service",
        "model": settings.GROQ_MODEL,
        "keys_count": len(settings.groq_keys),
    }
