from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from . import database

if TYPE_CHECKING:
    from Backend.scoring.PostClassifier import PostClassifier

logger = logging.getLogger(__name__)


class ScraperPrototype(ABC):
    def __init__(self) -> None:
        self.location = None
        self.keywords: set[str] = set()
        self.flagged_keywords: set[str] = set()
        self.join = None
        self.payment = None
        self.url = None
        self.text_search = None
        self._classifier: PostClassifier | None = None

    @abstractmethod
    def initialize(self):
        pass

    @abstractmethod
    def open_webpage(self):
        pass

    @abstractmethod
    def close_webpage(self):
        pass

    @abstractmethod
    def get_formatted_url(self):
        pass

    @abstractmethod
    def get_data(self, links):
        pass

    @abstractmethod
    def check_for_payment_methods(self, description: str) -> bool:
        pass

    @abstractmethod
    def capture_screenshot(self, screenshot_name):
        pass

    @abstractmethod
    def check_and_append_keywords(self, data: str) -> None:
        pass

    @staticmethod
    def open_database() -> database.Connection:
        """Open a connection to the database."""
        return database.connect()

    def _get_classifier(self) -> PostClassifier:
        """Lazy-initialize PostClassifier once per scraper instance."""
        if self._classifier is None:
            from Backend.scoring.PostClassifier import PostClassifier
            self._classifier = PostClassifier(
                flagged_keywords=self.flagged_keywords,
                regular_keywords=self.keywords,
            )
        return self._classifier

    def classify_post(
        self,
        source_table: str,
        link: str,
        city_or_region: str,
        post_text: str,
        keywords_found: list[str],
        payment_methods: list[str],
        social_media_accounts: list[str],
    ) -> None:
        """Classify a post and persist the result to post_classifications.

        Errors are caught and logged; classification failure never aborts a scrape.
        """
        try:
            self._get_classifier().classify(
                source_table=source_table,
                link=link,
                city_or_region=city_or_region,
                post_text=post_text,
                keywords_found=keywords_found,
                payment_methods=payment_methods,
                social_media_accounts=social_media_accounts,
            )
        except Exception as exc:
            logger.error(
                "[PostClassifier] classification failed for %s: %s", link, exc
            )
