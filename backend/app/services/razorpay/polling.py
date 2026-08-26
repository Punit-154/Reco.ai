from __future__ import annotations

from typing import Protocol


class SettlementsSource(Protocol):
    def fetch_settlements(self) -> list[dict]: ...


class FixtureSettlementsPoller:
    def __init__(self, items: list[dict]):
        self._items = list(items)

    def fetch_settlements(self) -> list[dict]:
        return list(self._items)


class HttpSettlementsPoller:
    def __init__(self, key_id: str = "", key_secret: str = ""):
        if not key_id or not key_secret:
            raise RuntimeError(
                "live settlement polling requires RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET"
            )
        self.key_id = key_id
        self.key_secret = key_secret

    def fetch_settlements(self) -> list[dict]:
        raise NotImplementedError(
            "live GET /v1/settlements polling lands in a later phase; "
            "use FixtureSettlementsPoller for tests and demos"
        )
