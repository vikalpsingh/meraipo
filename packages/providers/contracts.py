from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class Batch:
    provider: str
    request_id: str
    kind: str
    records: list[dict]


class IPOProvider(Protocol):
    async def get_open_ipos(self) -> Batch: ...
    async def get_upcoming_ipos(self) -> Batch: ...
    async def get_ipo_details(self, slug: str) -> dict | None: ...
    async def get_subscription(self, slug: str) -> dict | None: ...
    async def get_company_identity(self, slug: str) -> dict | None: ...


class CorporateResultsProvider(Protocol):
    async def get_financial_results(self, slug: str) -> Batch: ...
    async def get_latest_result(self, slug: str) -> dict | None: ...


class MarketPriceProvider(Protocol):
    async def get_eod_price(self, slug: str) -> dict | None: ...
    async def get_price_history(self, slug: str, start: date, end: date) -> Batch: ...


class GMPProvider(Protocol):
    async def get_gmp(self, slug: str) -> dict | None: ...


class DocumentProvider(Protocol):
    async def get_offer_documents(self, slug: str) -> Batch: ...


class RefreshProvider(Protocol):
    async def fetch(self, kind: str) -> Batch: ...
