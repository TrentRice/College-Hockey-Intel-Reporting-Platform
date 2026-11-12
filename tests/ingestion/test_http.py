import pytest

from src.ingestion import http
from src.ingestion.http import USER_AGENT_TOKEN, RobotsDisallowed, check_robots, parse_robots

# the shape of CHN's real robots.txt
ROBOTS = """
User-agent: *
Disallow: /box/livebox.php
Disallow: /box/final/2023
Disallow: /box/final/2024
Disallow: /users

User-agent: CCBot
Disallow: /
"""
SITE = "https://www.collegehockeynews.com"


@pytest.mark.parametrize(
    "path, allowed",
    [
        ("/box/final/20241004/bgs/mrc/", False),
        ("/box/final/20231110/bu/bc/", False),
        ("/box/final/20251003/clk/cns/", True),
        ("/box/final/20261107/bu/bc/", True),
        ("/schedules/team/Boston-University/10/20262027", True),
        ("/box/livebox.php?gd=1", False),
    ],
)
def test_robots_rules(path, allowed):
    assert parse_robots(ROBOTS).can_fetch(USER_AGENT_TOKEN, SITE + path) is allowed


def test_check_robots_raises_for_disallowed_urls(monkeypatch):
    monkeypatch.setitem(http._parsers, SITE, parse_robots(ROBOTS))
    check_robots(f"{SITE}/box/final/20261107/bu/bc/")  # fine
    with pytest.raises(RobotsDisallowed):
        check_robots(f"{SITE}/box/final/20241004/bgs/mrc/")
