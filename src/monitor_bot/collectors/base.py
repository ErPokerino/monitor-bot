"""Abstract base class for data collectors."""

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from monitor_bot.config import Settings
    from monitor_bot.models import Opportunity

logger = logging.getLogger(__name__)

ItemProgressFn = Callable[[str], None]


class BaseCollector(abc.ABC):
    """Every collector must implement :meth:`collect`."""

    def __init__(self, settings: Settings, on_item_done: ItemProgressFn | None = None) -> None:
        self.settings = settings
        self._on_item_done = on_item_done

    def _report_item(self, label: str) -> None:
        if self._on_item_done:
            self._on_item_done(label)

    @abc.abstractmethod
    async def collect(self) -> list[Opportunity]:
        """Fetch and return normalised opportunities from the source."""

    @property
    def name(self) -> str:
        return self.__class__.__name__
