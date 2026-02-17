"""Abstract base class for data collectors."""

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from monitor_bot.config import Settings
    from monitor_bot.models import Opportunity

logger = logging.getLogger(__name__)


class BaseCollector(abc.ABC):
    """Every collector must implement :meth:`collect`."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abc.abstractmethod
    async def collect(self) -> list[Opportunity]:
        """Fetch and return normalised opportunities from the source."""

    @property
    def name(self) -> str:
        return self.__class__.__name__
