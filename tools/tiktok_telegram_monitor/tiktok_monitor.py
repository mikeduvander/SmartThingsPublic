#!/usr/bin/env python3
"""Poll TikTok search results and notify a Telegram chat about new videos."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Protocol


# All configuration and requirements live in this file.
TELEGRAM_BOT_TOKEN = "8058625389:AAEJcRKBoKnF8kJhDdDqXRlPW-UsAa4VRuc"
TELEGRAM_CHAT_ID = os.getenv("KOE_TELEGRAM_CHAT_ID", "-4879627185")
TIKTOK_MS_TOKEN = "INDSAET_TIKTOK_MS_TOKEN"

SEARCH_TERM = "Vollsmose"
POLL_INTERVAL_SECONDS = 60
RESULTS_PER_CHECK = 30
STATE_FILE = Path(__file__).with_name("seen_videos.json")
MAX_SEEN_IDS = 2_000
REQUIRED_PACKAGES = ("TikTokApi==7.1.0",)

LOGGER = logging.getLogger("tiktok-monitor")
PLACEHOLDER_PREFIX = "INDSAET_"


class SearchClient(Protocol):
    def search_type(
        self, search_term: str, object_type: str, count: int
    ) -> AsyncIterator[Any]: ...


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    tiktok_ms_token: str
    search_term: str = SEARCH_TERM
    poll_interval_seconds: int = POLL_INTERVAL_SECONDS
    results_per_check: int = RESULTS_PER_CHECK
    state_file: Path = STATE_FILE

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            telegram_bot_token=TELEGRAM_BOT_TOKEN,
            telegram_chat_id=TELEGRAM_CHAT_ID,
            tiktok_ms_token=os.getenv("TIKTOK_MS_TOKEN", TIKTOK_MS_TOKEN),
            search_term=os.getenv("SEARCH_TERM", SEARCH_TERM),
            poll_interval_seconds=_positive_int_env(
                "POLL_INTERVAL_SECONDS", POLL_INTERVAL_SECONDS
            ),
            results_per_check=_positive_int_env(
                "RESULTS_PER_CHECK", RESULTS_PER_CHECK
            ),
            state_file=Path(os.getenv("STATE_FILE", str(STATE_FILE))),
        )

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("TELEGRAM_BOT_TOKEN", self.telegram_bot_token),
                ("TELEGRAM_CHAT_ID", self.telegram_chat_id),
                ("TIKTOK_MS_TOKEN", self.tiktok_ms_token),
            )
            if not value or value.startswith(PLACEHOLDER_PREFIX)
        ]
        if missing:
            raise ValueError(
                "Udfyld følgende indstillinger i miljøet eller øverst i scriptet: "
                + ", ".join(missing)
            )


def _positive_int_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} skal være større end 0")
    return value


def install_dependencies() -> None:
    """Install the pinned Python package and its Chromium browser."""
    subprocess.run(
        [sys.executable, "-m", "pip", "install", *REQUIRED_PACKAGES], check=True
    )
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"], check=True
    )


def load_seen_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Kunne ikke læse state-filen {path}: {error}") from error
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise RuntimeError(f"State-filen {path} har et ugyldigt format")
    return data


def save_seen_ids(path: Path, seen_ids: list[str]) -> None:
    """Atomically save recent IDs so an interrupted write cannot corrupt state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(seen_ids[-MAX_SEEN_IDS:], handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def video_data(video: Any) -> dict[str, Any]:
    data = getattr(video, "as_dict", None)
    return data if isinstance(data, dict) else {}


def video_id(video: Any) -> str | None:
    value = getattr(video, "id", None) or video_data(video).get("id")
    return str(value) if value else None


def video_timestamp(video: Any) -> int:
    value = video_data(video).get("createTime", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def video_message(video: Any, search_term: str) -> str:
    data = video_data(video)
    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    username = str(author.get("uniqueId") or "ukendt")
    description = str(data.get("desc") or "(ingen beskrivelse)").strip()
    identifier = video_id(video) or ""
    url = f"https://www.tiktok.com/@{urllib.parse.quote(username)}/video/{identifier}"
    return (
        f"Ny TikTok-video fundet for '{search_term}'\n\n"
        f"Bruger: @{username}\n"
        f"Tekst: {description[:1000]}\n\n"
        f"{url}"
    )


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    request = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Telegram-kaldet fejlede: {error}") from error
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram afviste beskeden: {payload}")


async def fetch_videos(search: SearchClient, settings: Settings) -> list[Any]:
    return [
        video
        async for video in search.search_type(
            settings.search_term, "item", count=settings.results_per_check
        )
    ]


async def check_once(search: SearchClient, settings: Settings) -> int:
    videos = await fetch_videos(search, settings)
    seen_ids = load_seen_ids(settings.state_file)
    seen = set(seen_ids)

    # First run establishes a baseline instead of sending a burst of old results.
    if not settings.state_file.exists():
        baseline = [identifier for video in videos if (identifier := video_id(video))]
        save_seen_ids(settings.state_file, baseline)
        LOGGER.info("Første kørsel: gemte %d eksisterende videoer", len(baseline))
        return 0

    new_videos = sorted(
        (video for video in videos if video_id(video) not in seen),
        key=video_timestamp,
    )
    sent = 0
    for video in new_videos:
        identifier = video_id(video)
        if not identifier:
            continue
        await asyncio.to_thread(
            send_telegram_message,
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            video_message(video, settings.search_term),
        )
        seen_ids.append(identifier)
        seen.add(identifier)
        save_seen_ids(settings.state_file, seen_ids)
        sent += 1
        LOGGER.info("Sendte Telegram-besked for video %s", identifier)
    return sent


async def run(settings: Settings, once: bool = False) -> None:
    try:
        from TikTokApi import TikTokApi
    except ImportError as error:
        raise RuntimeError(
            "TikTokApi mangler. Kør scriptet med --install-dependencies først."
        ) from error

    async with TikTokApi() as api:
        await api.create_sessions(
            num_sessions=1,
            ms_tokens=[settings.tiktok_ms_token],
            headless=True,
            sleep_after=3,
        )
        while True:
            try:
                await check_once(api.search, settings)
            except Exception:
                if once:
                    raise
                LOGGER.exception("Kontrollen fejlede; prøver igen ved næste interval")
            if once:
                return
            await asyncio.sleep(settings.poll_interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Kontrollér én gang og stop")
    parser.add_argument(
        "--install-dependencies",
        action="store_true",
        help="Installér de fastlåste dependencies og Playwright Chromium",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        if args.install_dependencies:
            install_dependencies()
            LOGGER.info("Dependencies er installeret")
            return 0
        settings = Settings.from_environment()
        settings.validate()
        asyncio.run(run(settings, once=args.once))
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        LOGGER.error("%s", error)
        return 1
    except KeyboardInterrupt:
        LOGGER.info("Stopper")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
