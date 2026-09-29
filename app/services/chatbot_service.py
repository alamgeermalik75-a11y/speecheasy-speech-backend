import logging
import asyncio
from groq import AsyncGroq
from app.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AI speech-therapy assistant helping parents whose children are learning Urdu pronunciation and speech sounds.

Provide supportive, clear, practical general information.

If the user asks in Urdu, respond in Urdu.
If the user asks in English, respond in English.

Do not claim to be a licensed clinician.
Do not diagnose medical or speech disorders.
Do not provide emergency medical advice.
When a question requires professional assessment, recommend consulting a qualified speech-language pathologist or appropriate healthcare professional."""

class ChatbotService:
    def __init__(self):
        self._client = None
        if settings.GROQ_API_KEY and settings.GROQ_API_KEY != "dummy_or_provide_in_env":
            try:
                self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")

    async def get_reply(self, message: str) -> str:
        if not self._client:
            # Fallback for dev/testing when no live API key is set
            return (
                "Hello! I am your Urdu speech learning assistant. Practice phonetics daily in a quiet room, "
                "focusing on one target letter at a time (like 'Bay' or 'Alif'). Celebrate every small win!"
            )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ]

        # Try primary model, fallback if needed
        models_to_try = [settings.GROQ_MODEL, settings.GROQ_FALLBACK_MODEL]
        last_error = None

        for model in models_to_try:
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=600,
                        temperature=0.7,
                    ),
                    timeout=settings.CHAT_REQUEST_TIMEOUT
                )
                if response.choices and response.choices[0].message.content:
                    return response.choices[0].message.content.strip()
            except asyncio.TimeoutError:
                logger.error("Chatbot request timed out")
                raise AppException(status_code=504, detail="AI assistant is taking too long to respond. Please try again.")
            except Exception as e:
                logger.error(f"Error querying model {model}: {e}")
                last_error = e

        logger.error(f"All Groq models failed: {last_error}")
        raise AppException(status_code=502, detail="AI assistant is temporarily unavailable. Please try again shortly.")

chatbot_service = ChatbotService()
