from packages.providers.contracts import Batch


class ManualProvider:
    """No outbound requests. Admin writes are validated by the same services."""

    async def fetch(self, kind: str) -> Batch:
        return Batch("manual", "manual-no-remote-feed", kind, [])


class FixtureProvider:
    """Explicit test adapter; never selected implicitly in production."""

    def __init__(self, batches: dict[str, list[dict]]):
        self.batches = batches

    async def fetch(self, kind: str) -> Batch:
        return Batch("fixture", f"fixture-{kind}", kind, self.batches.get(kind, []))


def provider(mode: str):
    if mode != "manual":
        raise ValueError(
            "Live provider unavailable: configure an approved adapter before enabling it"
        )
    return ManualProvider()
