"""Wrapper around the Groq SDK: connection test, chat calls, JSON parsing."""
import json
import logging
import re
from typing import List, Optional, Tuple

import groq
from groq import Groq

from config import (GROQ_MODEL, GROQ_FALLBACK_MODELS, GROQ_TIMEOUT_SECONDS,
                    MISSING_KEY_MESSAGE, get_groq_api_key)

logger = logging.getLogger(__name__)


class GroqConfigError(Exception):
    """Raised when the API key is missing."""


class AIError(Exception):
    """An AI request failed. The message is safe to show to the user."""


def get_client() -> Groq:
    api_key = get_groq_api_key()
    if not api_key:
        raise GroqConfigError(MISSING_KEY_MESSAGE)
    return Groq(api_key=api_key, timeout=GROQ_TIMEOUT_SECONDS)


def list_models() -> List[str]:
    return sorted(m.id for m in get_client().models.list().data)


# ---------------------------------------------------------------- connection test
def _try_model(model: str) -> Tuple[bool, str]:
    try:
        response = get_client().chat.completions.create(
            model=model, messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_completion_tokens=200)
        reply = (response.choices[0].message.content or "").strip()
        return True, f"Connected to Groq. Model '{model}' replied: {reply or '(empty reply)'}"
    except GroqConfigError as e:
        return False, str(e)
    except groq.AuthenticationError:
        return False, "Your Groq API key was rejected. Please check that it is correct."
    except groq.NotFoundError:
        return False, f"Model '{model}' was not found (it may have been retired)."
    except groq.RateLimitError:
        return False, "Groq rate limit reached. Wait a minute and try again."
    except groq.APITimeoutError:
        return False, "The request to Groq timed out. Please try again."
    except groq.APIConnectionError:
        return False, "Could not reach Groq. Check your internet connection."
    except groq.BadRequestError as e:
        return False, f"Model '{model}' rejected the request: {e}"
    except Exception as e:
        logger.exception("Unexpected Groq error")
        return False, f"Unexpected error: {type(e).__name__}"


def test_connection() -> Tuple[bool, str]:
    messages = []
    for model in [GROQ_MODEL] + GROQ_FALLBACK_MODELS:
        ok, message = _try_model(model)
        if ok:
            return True, message
        messages.append(message)
        if "API key" in message or "GROQ_API_KEY" in message:
            break
    return False, " | ".join(messages)


# ---------------------------------------------------------------- main chat function
_THINK_TAGS = re.compile(r"<think>.*?</think>", re.DOTALL)


def _build_kwargs(model: str, messages: list, json_mode: bool, max_tokens: int,
                  temperature: float, use_extras: bool) -> dict:
    kwargs = dict(model=model, messages=messages,
                  max_completion_tokens=max_tokens, temperature=temperature)
    if use_extras:
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if model.startswith("openai/gpt-oss"):
            kwargs["reasoning_effort"] = "low"   # leave more tokens for the answer
    return kwargs


def chat_completion(messages: list, json_mode: bool = False, max_tokens: int = 1500,
                    temperature: float = 0.1) -> str:
    """Ask Groq and return the reply text.
    Tries the main model, then the fallbacks. Raises GroqConfigError or AIError."""
    client = get_client()            # raises GroqConfigError if the key is missing
    problems = []
    for model in [GROQ_MODEL] + GROQ_FALLBACK_MODELS:
        for use_extras in (True, False):
            try:
                response = client.chat.completions.create(
                    **_build_kwargs(model, messages, json_mode, max_tokens, temperature, use_extras))
                text = _THINK_TAGS.sub("", response.choices[0].message.content or "").strip()
                if text:
                    return text
                problems.append(f"{model}: empty reply")
                break
            except groq.BadRequestError:
                if use_extras:
                    continue         # retry once without JSON mode / reasoning option
                problems.append(f"{model}: request rejected")
                break
            except groq.AuthenticationError:
                raise AIError("Your Groq API key was rejected. Please check that it is correct.")
            except groq.APIConnectionError:
                raise AIError("Could not reach Groq. Check your internet connection.")
            except groq.NotFoundError:
                problems.append(f"{model}: not available")
                break
            except groq.RateLimitError:
                problems.append(f"{model}: rate limit reached")
                break
            except groq.APITimeoutError:
                problems.append(f"{model}: timed out")
                break
            except Exception as exc:
                logger.exception("Unexpected Groq error")
                problems.append(f"{model}: {type(exc).__name__}")
                break
    raise AIError("The AI service could not answer right now (" + "; ".join(problems) + "). "
                  "Please wait a moment and try again.")


def parse_json_reply(text: Optional[str]):
    """Turn the AI's reply into Python data, or return None if it is not valid JSON."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None
