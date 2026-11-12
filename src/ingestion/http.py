"""
Shared HTTP settings for the CHN scrapers, including the robots.txt check.

Every network request goes through `check_robots(url)` first. CHN's robots.txt asks
crawlers to skip some paths (e.g. box scores from 2024 and earlier); a disallowed URL raises
RobotsDisallowed instead of being fetched. robots.txt is read once per process.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT_TOKEN = "chirp-hockey"
HEADERS = {"User-Agent": f"Mozilla/5.0 (compatible; {USER_AGENT_TOKEN}/0.1; personal research)"}

_parsers: dict[str, RobotFileParser] = {}


class RobotsDisallowed(Exception):
    pass


def parse_robots(text: str) -> RobotFileParser:
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    return rp


def robots_for(url: str) -> RobotFileParser:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _parsers:
        resp = requests.get(f"{origin}/robots.txt", headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            _parsers[origin] = parse_robots(resp.text)
        elif resp.status_code in (401, 403):
            _parsers[origin] = parse_robots("User-agent: *\nDisallow: /")  # treat as "keep out"
        elif 400 <= resp.status_code < 500:
            _parsers[origin] = parse_robots("")  # no robots.txt: nothing is disallowed
        else:
            resp.raise_for_status()  # server trouble: don't guess, fail this run
    return _parsers[origin]


def check_robots(url: str) -> None:
    if not robots_for(url).can_fetch(USER_AGENT_TOKEN, url):
        raise RobotsDisallowed(f"robots.txt disallows {url}")
