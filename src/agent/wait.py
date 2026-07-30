"""Wait Profile：等人策略（Step 3）。"""

from __future__ import annotations

from typing import Literal

WaitProfile = Literal["interactive", "turn_based", "no_wait"]

DEFAULT_WAIT_PROFILE: WaitProfile = "turn_based"

_VALID: frozenset[str] = frozenset({"interactive", "turn_based", "no_wait"})


def normalize_wait_profile(raw: str | None) -> WaitProfile:
    text = (raw or DEFAULT_WAIT_PROFILE).strip().lower()
    if text not in _VALID:
        raise ValueError(
            f"未知 wait_profile={raw!r}，可选: interactive / turn_based / no_wait"
        )
    return text  # type: ignore[return-value]
