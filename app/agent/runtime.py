"""Process-local Ask admission; the supplied provider facade owns HTTP and typed routing."""

import os
import tomllib
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from threading import Lock
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.agent.answers import Answer, Paused

PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class Settings(BaseModel):
    """Nonsecret provider settings; each call reserves its full input allowance."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str = "https://api.typesafe.ai/v1/systemone"
    model: str = "jev-latest"
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 8
    request_input_tokens: PositiveInt = 8192
    daily_input_tokens: PositiveInt = 100000


def load_settings() -> Settings:
    path = Path(__file__).resolve().parents[2] / "config.toml"
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    return Settings.model_validate(config["ask"])


class Runtime:
    """Share ONE instance per worker; only single-worker deployments enforce global caps.

    The provider receives the environment key only after admission. It must bound
    the complete serialized input to settings.request_input_tokens and enforce the
    configured timeout. No refund: even failed calls may have been billed upstream.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings if settings is not None else load_settings()
        self._clock = clock
        self._lock = Lock()
        self._day = datetime.min.date()
        self._tokens = 0
        self._daily: dict[str, int] = {}
        self._recent: dict[str, deque[datetime]] = {}

    def run(self, ip: str, provider: Callable[[str], Answer]) -> Answer:
        """Admit atomically, then call outside the lock; never log provider exceptions.

        ip must be the trusted client address, not an unchecked forwarded header.
        A missing/blank key or any exhausted allowance returns #181's canned result.
        """
        address = str(ip_address(ip))
        key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        if not key:
            return Paused(kind="paused")
        with self._lock:
            now = self._clock().astimezone(UTC)
            if now.date() != self._day:
                self._day = now.date()
                self._daily.clear()
                self._recent.clear()
                self._tokens = 0
            recent = self._recent.get(address, deque())
            while recent and (now - recent[0]).total_seconds() >= 60:
                recent.popleft()
            count = self._daily.get(address, 0)
            reservation = self.settings.request_input_tokens
            if (
                len(recent) >= 10
                or count >= 100
                or self._tokens + reservation > self.settings.daily_input_tokens
            ):
                return Paused(kind="paused")
            recent.append(now)
            self._recent[address] = recent
            self._daily[address] = count + 1
            self._tokens += reservation
        try:
            return provider(key)
        except Exception:
            # Upstream exception messages can include credentials and request bodies.
            return Paused(kind="paused")
