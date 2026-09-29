from fastapi import APIRouter, Depends
from app.core.security import get_current_user_uid
from app.core.rate_limit import chat_rate_limiter
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chatbot_service import chatbot_service

router = APIRouter(prefix="/chat", tags=["AI Chatbot"])

@router.post("", response_model=ChatResponse)
async def chat_with_assistant(
    data: ChatRequest,
    current_uid: str = Depends(get_current_user_uid)
):
    """
    AI Speech-Language Pathologist Assistant.
    Enforces per-user rate limiting and safe timeout/provider error handling.
    """
    # 1. Enforce sliding window rate limit per user
    chat_rate_limiter.check_rate_limit(current_uid)

    # 2. Get safe AI reply from Groq
    reply = await chatbot_service.get_reply(data.message)
    return ChatResponse(reply=reply)
