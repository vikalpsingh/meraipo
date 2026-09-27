"""IPO provider contract. Adapters normalize external schemas before staging.

Exchange and versioned-feed modes retain their existing collectors; new vendor
adapters implement batches() and register here without changing master/UI schemas.
"""

from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass
class IPOBatch:
    url: str
    raw: str
    records: list
    errors: list


class IPOProvider(Protocol):
    name: str
    authority: str

    def batches(self, deadline: float) -> AsyncIterator[IPOBatch]: ...


def get_ipo_provider(config) -> IPOProvider:
    from packages.providers.ipoalerts import IPOAlerts

    adapters = {"ipoalerts": IPOAlerts}
    return adapters[config.ipo_data_provider](
        config.ipoalerts_api_key.get_secret_value(), page_size=config.ipoalerts_page_size
    )


def primary_ipo_provider(config):
    return {"ipoalerts": "IPOALERTS"}.get(config.ipo_data_provider)
