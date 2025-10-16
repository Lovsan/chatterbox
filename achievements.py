"""Utility helpers for gamification progress."""

from typing import Tuple
from models import LEVELS


def determine_level_and_badge(xp: int) -> Tuple[int, str]:
    """Return the appropriate level and badge for the given XP."""
    level = 1
    badge = "Newcomer"
    for lvl, name, threshold in LEVELS:
        if xp >= threshold:
            level = lvl
            badge = name
        else:
            break
    return level, badge


def apply_progress(user, xp_delta: int) -> Tuple[int, str]:
    """Apply an XP delta to the user and update their level/badge."""
    user.xp = max(0, user.xp + xp_delta)
    level, badge = determine_level_and_badge(user.xp)
    user.level = level
    user.badge = badge
    return level, badge
