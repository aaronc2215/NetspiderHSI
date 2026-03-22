"""Rule-based scorer for NetspiderHSI post classification.

Computes a 0-100 risk score based on:
  - Flagged keyword hits (weighted higher than regular keywords)
  - Regular keyword hits
  - Payment method count and high-risk payment types
  - Social media account presence
  - Obfuscation patterns (leet-speak, character substitution, spaced letters)
  - Keyword density relative to post length
"""

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Scoring weights — adjust here without touching method logic
# ---------------------------------------------------------------------------
FLAGGED_KEYWORD_WEIGHT  = 15.0   # per flagged keyword found
REGULAR_KEYWORD_WEIGHT  =  5.0   # per regular keyword found
PAYMENT_METHOD_WEIGHT   =  6.0   # per payment method found
HIGH_RISK_PAYMENT_BONUS =  8.0   # flat bonus when a high-risk payment method appears
SOCIAL_MEDIA_WEIGHT     =  3.0   # per social media platform found
OBFUSCATION_WEIGHT      = 10.0   # flat bonus when obfuscation is detected
DENSITY_BONUS_MAX       = 10.0   # max contribution from keyword density component
MAX_SCORE               = 100.0

HIGH_RISK_PAYMENT_METHODS: set[str] = {
    "cashapp", "venmo", "zelle", "crypto", "western union"
}

# Common obfuscation patterns found in escort/illicit-service posts
_OBFUSCATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'\b\w*[4@]\w*\b'),         # 'a' replaced with 4 or @
    re.compile(r'\b\w*[3]\w*\b'),           # 'e' replaced with 3
    re.compile(r'\b\w*[1!]\w*\b'),          # 'i' replaced with 1 or !
    re.compile(r'\b\w*[0]\w*\b'),           # 'o' replaced with 0
    re.compile(r'[a-z][\*\.][a-z]'),        # dots or asterisks between letters (e.g. s*x)
    re.compile(r'(?<![a-z])[a-z] [a-z] [a-z](?![a-z])'),  # spaced letters (s e x)
]


@dataclass
class RuleScoreResult:
    score: float
    flagged_keywords_hit: list[str] = field(default_factory=list)
    regular_keywords_hit: list[str] = field(default_factory=list)
    payment_methods_found: list[str] = field(default_factory=list)
    social_media_found: list[str] = field(default_factory=list)
    obfuscation_detected: bool = False
    breakdown: dict = field(default_factory=dict)


class RuleBasedScorer:
    def __init__(
        self,
        flagged_keywords: set[str] | None = None,
        regular_keywords: set[str] | None = None,
    ) -> None:
        self.flagged_keywords: set[str] = flagged_keywords or set()
        self.regular_keywords: set[str] = regular_keywords or set()

    def score(
        self,
        post_text: str,
        keywords_found: list[str],
        payment_methods: list[str],
        social_media_accounts: list[str],
    ) -> RuleScoreResult:
        """Compute a rule-based risk score (0–100) for a single post."""
        flagged_hit, regular_hit, kw_points = self._score_keywords(keywords_found)
        pm_points = self._score_payment_methods(payment_methods)
        sm_points = self._score_social_media(social_media_accounts)
        obfuscation = self._detect_obfuscation(post_text)
        obf_points = OBFUSCATION_WEIGHT if obfuscation else 0.0
        density_points = self._score_density(post_text, keywords_found)

        raw = kw_points + pm_points + sm_points + obf_points + density_points
        final = min(raw, MAX_SCORE)

        return RuleScoreResult(
            score=final,
            flagged_keywords_hit=flagged_hit,
            regular_keywords_hit=regular_hit,
            payment_methods_found=list(payment_methods),
            social_media_found=list(social_media_accounts),
            obfuscation_detected=obfuscation,
            breakdown={
                "keyword_points": kw_points,
                "payment_points": pm_points,
                "social_media_points": sm_points,
                "obfuscation_points": obf_points,
                "density_points": density_points,
                "raw_total": raw,
            },
        )

    def _score_keywords(
        self, keywords_found: list[str]
    ) -> tuple[list[str], list[str], float]:
        flagged_hit: list[str] = []
        regular_hit: list[str] = []
        points = 0.0
        for kw in keywords_found:
            if kw in self.flagged_keywords:
                flagged_hit.append(kw)
                points += FLAGGED_KEYWORD_WEIGHT
            else:
                regular_hit.append(kw)
                points += REGULAR_KEYWORD_WEIGHT
        return flagged_hit, regular_hit, points

    def _score_payment_methods(self, payment_methods: list[str]) -> float:
        points = len(payment_methods) * PAYMENT_METHOD_WEIGHT
        if any(pm.strip() in HIGH_RISK_PAYMENT_METHODS for pm in payment_methods):
            points += HIGH_RISK_PAYMENT_BONUS
        return points

    def _score_social_media(self, social_media_accounts: list[str]) -> float:
        return len(social_media_accounts) * SOCIAL_MEDIA_WEIGHT

    def _detect_obfuscation(self, post_text: str) -> bool:
        text_lower = post_text.lower()
        for pattern in _OBFUSCATION_PATTERNS:
            if pattern.search(text_lower):
                return True
        return False

    def _score_density(self, post_text: str, keywords_found: list[str]) -> float:
        if not post_text or not keywords_found:
            return 0.0
        word_count = len(post_text.split())
        if word_count == 0:
            return 0.0
        density = len(keywords_found) / word_count
        return min(density * DENSITY_BONUS_MAX * 10, DENSITY_BONUS_MAX)
