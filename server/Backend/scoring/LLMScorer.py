"""LLM-based scorer using a local Ollama server.

Requires Ollama to be installed and running locally:
  https://ollama.com/download

Pull a model before first use, e.g.:
  ollama pull llama3.2

Only invoked for posts where rule_score >= RULE_SCORE_THRESHOLD to avoid
unnecessary latency on clearly safe content.
"""

import json
import logging
import os
import re
from dataclasses import dataclass

import ollama

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "llama3.2"
_DEFAULT_HOST  = "http://localhost:11434"

_SYSTEM_PROMPT = """\
You are an analyst assistant for a law enforcement agency investigating online \
escort and adult service advertisements. Your task is to evaluate whether a post \
is soliciting illegal commercial sex services (human trafficking, prostitution) \
or is a legitimate, legal adult entertainment listing.

You MUST respond with ONLY a JSON object — no markdown, no explanation, no extra text:
{"score": <integer 0-100>, "bucket": <1, 2, or 3>, "reasoning": "<1-2 sentences>"}

Scoring guidance:
- score 0-39 / bucket 1: Clearly safe; no credible indicators of illegal solicitation.
- score 40-60 / bucket 2: Suggestive but consistent with legal adult entertainment.
- score 61-100 / bucket 3: Strong indicators of illegal commercial sex solicitation \
  (explicit pricing, transactional language, known code words for paid sex acts).\
"""

_USER_PROMPT_TEMPLATE = """\
POST TEXT:
{post_text}

KEYWORDS FLAGGED: {keywords_found}
PAYMENT METHODS: {payment_methods}
SOCIAL MEDIA: {social_media_accounts}
RULE-BASED SCORE: {rule_score}

Respond with JSON only: {{"score": ..., "bucket": ..., "reasoning": "..."}}"""


@dataclass
class LLMScoreResult:
    score: float
    bucket: int
    reasoning: str
    raw_response: str


class LLMScorerError(Exception):
    """Raised when the Ollama call or response parsing fails."""


class LLMScorer:
    def __init__(self, model: str = _DEFAULT_MODEL) -> None:
        self.model = os.environ.get("OLLAMA_MODEL", model)
        host = os.environ.get("OLLAMA_HOST", _DEFAULT_HOST)
        self.client = ollama.Client(host=host)

    def score(
        self,
        post_text: str,
        keywords_found: list[str],
        payment_methods: list[str],
        social_media_accounts: list[str],
        rule_score: float,
    ) -> LLMScoreResult:
        """Send post data to a local Ollama model and return a risk assessment.

        Raises LLMScorerError if the call fails or the response cannot be parsed.
        """
        user_prompt = self._build_user_prompt(
            post_text, keywords_found, payment_methods, social_media_accounts, rule_score
        )
        try:
            response = self.client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                options={"temperature": 0},
            )
            raw_text = response["message"]["content"]
        except Exception as exc:
            raise LLMScorerError(f"Ollama call failed: {exc}") from exc

        score_val, bucket, reasoning = self._parse_response(raw_text)
        return LLMScoreResult(
            score=score_val,
            bucket=bucket,
            reasoning=reasoning,
            raw_response=raw_text,
        )

    def _build_user_prompt(
        self,
        post_text: str,
        keywords_found: list[str],
        payment_methods: list[str],
        social_media_accounts: list[str],
        rule_score: float,
    ) -> str:
        truncated = post_text[:2000] if len(post_text) > 2000 else post_text
        return _USER_PROMPT_TEMPLATE.format(
            post_text=truncated,
            keywords_found=", ".join(keywords_found) if keywords_found else "none",
            payment_methods=", ".join(payment_methods) if payment_methods else "none",
            social_media_accounts=", ".join(social_media_accounts) if social_media_accounts else "none",
            rule_score=f"{rule_score:.1f}",
        )

    def _parse_response(self, raw_text: str) -> tuple[float, int, str]:
        """Parse the JSON response from Ollama. Returns (score, bucket, reasoning).

        Local models sometimes wrap JSON in markdown fences or add prose —
        this method strips common noise before parsing.
        """
        text = raw_text.strip()

        # Strip markdown code fences if present
        if "```" in text:
            # Extract content between first ``` pair
            text = re.sub(r"```(?:json)?\s*", "", text).strip()

        # Try to extract a JSON object if the model added surrounding prose
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMScorerError(
                f"Could not parse Ollama response as JSON: {raw_text!r}"
            ) from exc

        try:
            score_val = float(data["score"])
            bucket    = int(data["bucket"])
            reasoning = str(data.get("reasoning", ""))
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMScorerError(
                f"Ollama response missing required fields: {raw_text!r}"
            ) from exc

        if not (0 <= score_val <= 100):
            raise LLMScorerError(
                f"Ollama returned out-of-range score {score_val}: {raw_text!r}"
            )
        if bucket not in (1, 2, 3):
            raise LLMScorerError(
                f"Ollama returned invalid bucket {bucket}: {raw_text!r}"
            )

        return score_val, bucket, reasoning
