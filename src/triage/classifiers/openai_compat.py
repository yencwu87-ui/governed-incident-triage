"""OpenAI-compatible classifier.

Same contract as the Anthropic classifier, pointed at any endpoint speaking the
OpenAI chat-completions shape. That covers a local Ollama install, which is
free and needs no key, as well as the free tiers of several hosted providers.

Standard library only - no extra dependency to install.

The reason this exists is not cost. Running the same governed pipeline across
several models turns a single eval into a comparison, and a comparison is the
only way to tell whether the gates are doing work or whether one model happened
to suit the rubric. A model that fails the under-classification gate while
another passes it is a finding about the models. Both failing is a finding
about the rubric.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..rubric import derive_severity
from ..schemas import Category, Impact, TriageDecision, Urgency
from .base import ClassifierError
from .llm import _SYSTEM_PROMPT, _extract_json

# Endpoint presets. Each is an OpenAI-compatible chat-completions base URL.
PROVIDERS: dict[str, dict[str, str]] = {
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "key_env": "OLLAMA_API_KEY",  # unused by Ollama, any value works
        "default_model": "llama3.1:8b",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.0-flash",
    },
}


class OpenAICompatClassifier:
    """Chat-completions classifier for local or free-tier endpoints."""

    def __init__(
        self,
        provider: str = "ollama",
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: int = 120,
    ) -> None:
        if provider not in PROVIDERS and base_url is None:
            raise ClassifierError(
                f"unknown provider '{provider}'. "
                f"Known: {sorted(PROVIDERS)}, or pass base_url explicitly."
            )
        preset = PROVIDERS.get(provider, {})
        self.provider = provider
        self.model = model or preset.get("default_model", "")
        self._base_url = (base_url or preset["base_url"]).rstrip("/")
        # Ollama ignores the key but the header must be present.
        self._api_key = api_key or os.environ.get(preset.get("key_env", ""), "local")
        self._timeout = timeout
        self.name = f"{provider}-{self.model}"

    def _post(self, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise ClassifierError(
                f"HTTP {exc.code} from {self.provider}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            hint = ""
            if self.provider == "ollama":
                hint = " - is Ollama running? Try: ollama serve"
            raise ClassifierError(f"cannot reach {self._base_url}{hint}: {exc}") from exc

    def classify(
        self,
        incident_id: str,
        text: str,
        feedback: str | None = None,
    ) -> TriageDecision:
        user_content = f"<incident>\n{text}\n</incident>"
        if feedback:
            user_content += (
                "\n\nYour previous attempt was rejected by the safety gate for "
                f"these reasons:\n{feedback}\nProduce a corrected assessment."
            )

        data = self._post(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0,
                "max_tokens": 700,
            }
        )

        try:
            raw = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ClassifierError(
                f"unexpected response shape: {str(data)[:200]}"
            ) from exc

        payload = _extract_json(raw)

        try:
            impact = Impact(payload["impact"])
            urgency = Urgency(payload["urgency"])
            category = Category(payload["category"])
        except (KeyError, ValueError) as exc:
            raise ClassifierError(f"invalid enum value from model: {exc}") from exc

        # Smaller models frequently return confidence as a percentage or a
        # string. Coerce rather than fail - a malformed confidence is a Gate A
        # concern, not a parse error.
        raw_confidence = payload.get("confidence", 0.5)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = 0.5
        if confidence > 1.0:
            confidence = confidence / 100.0
        confidence = max(0.0, min(1.0, confidence))

        rationale = str(payload.get("rationale", "")).strip()
        if len(rationale) < 20:
            rationale = (
                f"{rationale} (model returned an under-length rationale; "
                "recorded verbatim for Gate A assessment)"
            ).strip()

        return TriageDecision(
            incident_id=incident_id,
            category=category,
            impact=impact,
            urgency=urgency,
            severity=derive_severity(impact, urgency),
            confidence=confidence,
            rationale=rationale[:1200],
            indicators=[str(i) for i in payload.get("indicators", [])][:12],
        )
