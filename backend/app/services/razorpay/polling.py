from __future__ import annotations

import logging
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


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
        all_items: list[dict] = []
        skip = 0
        count = 100

        with httpx.Client(auth=(self.key_id, self.key_secret), timeout=30) as client:
            while True:
                log.info("Fetching settlements skip=%d count=%d", skip, count)
                resp = client.get(
                    f"{RAZORPAY_API_BASE}/settlements",
                    params={"count": count, "skip": skip},
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])
                all_items.extend(items)
                log.info("Got %d settlements (total so far: %d)", len(items), len(all_items))
                if len(items) < count:
                    break
                skip += count

        return all_items
