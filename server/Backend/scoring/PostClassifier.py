"""PostClassifier orchestrates rule-based and LLM scoring for a single post,
then persists the result to the post_classifications table.

This is the single entry point called from each scraper's append_data().
"""

import logging
from dataclasses import dataclass

from Backend import database
from Backend.scoring.RuleBasedScorer import RuleBasedScorer
from Backend.scoring.LLMScorer import LLMScorer, LLMScoreResult, LLMScorerError

logger = logging.getLogger(__name__)

# Posts with rule_score below this threshold are classified as safe (bucket 1)
# without calling the LLM, to avoid unnecessary API cost and latency.
RULE_SCORE_THRESHOLD = 40.0

# LLM bucket-3 posts with final_score at or above this value are flagged for
# human review (review_status = 'pending').  Below it they are downgraded to
# bucket 2 / cleared.
REVIEW_THRESHOLD = 60.0


@dataclass
class ClassificationResult:
    rule_score: float
    llm_score: float | None
    final_score: float
    bucket: int
    llm_reasoning: str | None
    review_status: str


class PostClassifier:
    def __init__(
        self,
        flagged_keywords: set[str],
        regular_keywords: set[str],
    ) -> None:
        self.rule_scorer = RuleBasedScorer(flagged_keywords, regular_keywords)
        self._llm_scorer: LLMScorer | None = None

    @property
    def llm_scorer(self) -> LLMScorer:
        """Lazy-initialize LLMScorer so import doesn't fail when API key is absent."""
        if self._llm_scorer is None:
            self._llm_scorer = LLMScorer()
        return self._llm_scorer

    def classify(
        self,
        source_table: str,
        link: str,
        city_or_region: str,
        post_text: str,
        keywords_found: list[str],
        payment_methods: list[str],
        social_media_accounts: list[str],
    ) -> ClassificationResult:
        """Run the full classification pipeline and persist the result.

        1. Compute rule_score.
        2. If rule_score >= RULE_SCORE_THRESHOLD, call the LLM.
        3. Determine final bucket and review_status.
        4. Write to post_classifications (ON CONFLICT DO NOTHING — idempotent).
        5. Return ClassificationResult.
        """
        rule_result = self.rule_scorer.score(
            post_text, keywords_found, payment_methods, social_media_accounts
        )
        rule_score = rule_result.score

        llm_result: LLMScoreResult | None = None
        if rule_score >= RULE_SCORE_THRESHOLD:
            try:
                llm_result = self.llm_scorer.score(
                    post_text=post_text,
                    keywords_found=keywords_found,
                    payment_methods=payment_methods,
                    social_media_accounts=social_media_accounts,
                    rule_score=rule_score,
                )
            except LLMScorerError as exc:
                logger.warning(
                    "LLM scoring failed for %s — falling back to rule-only: %s",
                    link,
                    exc,
                )

        bucket, final_score, review_status = self._determine_outcome(
            rule_score, llm_result
        )

        result = ClassificationResult(
            rule_score=rule_score,
            llm_score=llm_result.score if llm_result else None,
            final_score=final_score,
            bucket=bucket,
            llm_reasoning=llm_result.reasoning if llm_result else None,
            review_status=review_status,
        )

        self._write_to_db(source_table, link, city_or_region, result)
        return result

    def _determine_outcome(
        self,
        rule_score: float,
        llm_result: LLMScoreResult | None,
    ) -> tuple[int, float, str]:
        """Map rule + LLM outputs to (bucket, final_score, review_status).

        Decision table:
          rule_score < threshold, no LLM  → bucket 1, marked_safe
          LLM bucket = 1                  → bucket 1, marked_safe
          LLM bucket = 2                  → bucket 2, cleared
          LLM bucket = 3, score > 60      → bucket 3, pending
          LLM bucket = 3, score <= 60     → bucket 2, cleared
          LLM failed (None), rule >= 40   → bucket 3, pending (conservative)
        """
        if llm_result is None:
            if rule_score < RULE_SCORE_THRESHOLD:
                return 1, rule_score, "marked_safe"
            # LLM unavailable but rule score is elevated — flag conservatively
            return 3, rule_score, "pending"

        final_score = llm_result.score

        if llm_result.bucket == 1:
            return 1, final_score, "marked_safe"
        if llm_result.bucket == 2:
            return 2, final_score, "cleared"
        # bucket == 3
        if final_score > REVIEW_THRESHOLD:
            return 3, final_score, "pending"
        return 2, final_score, "cleared"

    def _write_to_db(
        self,
        source_table: str,
        link: str,
        city_or_region: str,
        result: ClassificationResult,
    ) -> None:
        """Insert classification record, silently skipping duplicates."""
        try:
            with database.connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into post_classifications
                        (source_table, link, city_or_region,
                         rule_score, llm_score, final_score,
                         llm_reasoning, bucket, review_status)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (source_table, link, city_or_region) do nothing;
                    """,
                    (
                        source_table,
                        link,
                        city_or_region,
                        result.rule_score,
                        result.llm_score,
                        result.final_score,
                        result.llm_reasoning,
                        result.bucket,
                        result.review_status,
                    ),
                )
        except Exception as exc:
            logger.error(
                "Failed to write classification for %s to database: %s", link, exc
            )
