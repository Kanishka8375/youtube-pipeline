"""Canonical forms for entity names and fact values.

Two different comparisons in the continuity system fail for the same reason:
the same thing written two ways does not compare equal.

*Names.* ``"Mira"``, ``"MIRA"`` and ``"Mira "`` are one character. Resolving
them separately forks canon into parallel histories that can never contradict
each other, because they never meet.

*Values.* ``"Safehouse"``, ``"safehouse"`` and ``{"value": "safehouse"}`` are
one location. Comparing them raw reports a contradiction on every one of them,
and a gate that cries wolf is a gate somebody turns off.

Both problems are solved the same way: reduce to a canonical form, compare
that, and keep the original for display.

What is deliberately *not* done here
------------------------------------
Normalisation never merges things that are merely similar. ``"Mira"`` and
``"Mara"`` stay distinct; deciding they are the same character is a judgement
call, and getting it wrong attaches a fact to the wrong person -- a quiet,
permanent corruption of canon. Near-miss detection lives in
``canon_registry.suggest()``, which proposes and lets a human decide.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Optional

#: Everything that is not a letter or a digit. Stripped outright from names --
#: see `normalise_alias` for why a separator cannot be kept.
_SEPARATORS = re.compile(r"[^0-9A-Za-z]+", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

#: Wrapper keys agents habitually use for a scalar: {"v": x}, {"value": x}.
#: Unwrapped so that a fact written as a bare string and the same fact written
#: as a wrapped one compare equal.
_SCALAR_WRAPPER_KEYS = ("value", "v", "val", "text", "name")

#: Distinguishes an absent value from the string "null". Control characters
#: cannot survive `normalise_alias` and are absent from real fact values.
NULL_SENTINEL = "\x00null"

#: Longer than this and the normalised form is not stored -- the column is
#: indexed, and an index over prose is a cost with no lookup behind it.
MAX_NORMALISED_LENGTH = 512


def normalise_alias(name: str) -> str:
    """Canonical lookup form for a name: letters and digits only, case-folded.

    Accents, punctuation and spaces are all removed rather than normalised to a
    separator. That is deliberate, and it is the only rule that makes the whole
    family agree: ``"Rene O'Hara"``, ``"René OHara"`` and ``"rene o hara"`` are
    one person, and any rule that keeps a separator makes two of those three
    disagree with the third.

    The cost is that two names differing only by a space collide -- ``"Red Sun"``
    and ``"Redsun"`` become one key. For character names that is nearly always
    right, and where it is wrong the unique constraint on `entity_aliases`
    surfaces it as a refused write rather than a silent merge.

    Returns ``""`` for anything that reduces to nothing, which callers must
    treat as "not a usable name" rather than as a key.
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _SEPARATORS.sub("", text)
    return text.casefold()


def unwrap_scalar(value: Any) -> Any:
    """Strip a single-key scalar wrapper, recursively.

    ``{"value": {"v": "alley"}}`` -> ``"alley"``. A dict with more than one key,
    or whose single key is not a known wrapper, is returned untouched: guessing
    which of several keys is "the value" would be inventing meaning.
    """
    seen = 0
    while isinstance(value, dict) and len(value) == 1 and seen < 8:
        (key,), (inner,) = value.keys(), value.values()
        if key.strip().casefold() not in _SCALAR_WRAPPER_KEYS:
            return value
        value = inner
        seen += 1
    return value


def normalise_fact_value(value: Any) -> Optional[str]:
    """A stable string for comparing two fact values, or ``None``.

    ``None`` means "no canonical form" -- the value is a structure rich enough
    that flattening it would lose information. Callers fall back to comparing
    the raw values, which is stricter, not looser: the failure mode is a
    reported difference that a human dismisses, never a missed contradiction.
    """
    value = unwrap_scalar(value)

    if value is None:
        # A sentinel no string can produce. Returning plain "null" would make
        # an absent value compare equal to a fact whose value is literally the
        # text "null" -- rare, but a false negative in the one direction this
        # module must not have them.
        return NULL_SENTINEL
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        # 3 and 3.0 are the same quantity; "3.0" and "3" should not differ.
        as_float = float(value)
        text = str(int(as_float)) if as_float.is_integer() else repr(as_float)
        return text
    if isinstance(value, str):
        text = _WHITESPACE.sub(" ", value.strip()).casefold()
        return text[:MAX_NORMALISED_LENGTH] if text else ""
    if isinstance(value, (list, tuple, set)):
        parts = [normalise_fact_value(item) for item in value]
        if any(part is None for part in parts):
            return None
        # Sorted: ["a", "b"] and ["b", "a"] are the same set of traits. Order
        # matters in a sequence, but fact values that are lists are overwhelm-
        # ingly unordered sets in practice, and treating a reordering as a
        # contradiction is the false positive that gets the gate disabled.
        joined = "|".join(sorted(parts))
        return joined[:MAX_NORMALISED_LENGTH] if len(joined) <= MAX_NORMALISED_LENGTH else None
    if isinstance(value, dict):
        try:
            flat = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            return None
        return flat.casefold() if len(flat) <= MAX_NORMALISED_LENGTH else None
    return None


def values_agree(left: Any, right: Any) -> bool:
    """Whether two fact values mean the same thing.

    Falls back to raw equality when either side has no canonical form.
    """
    left_norm = normalise_fact_value(left)
    right_norm = normalise_fact_value(right)
    if left_norm is None or right_norm is None:
        return unwrap_scalar(left) == unwrap_scalar(right)
    return left_norm == right_norm
