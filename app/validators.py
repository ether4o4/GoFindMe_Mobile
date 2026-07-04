"""Target type detection, strict validation, and safe argv construction.

Every value that reaches a subprocess passes through ``validate`` first. Patterns
are fully anchored whitelists, so a validated target can never contain whitespace
or shell metacharacters and can never begin with '-' (argument-injection guard).
Combined with list-form ``create_subprocess_exec`` (never a shell), this is the
core of the dispatcher's safety.
"""
from __future__ import annotations

import ipaddress
import re

MAX_LEN = 256

TARGET_TYPES = ["username", "realname", "email", "phone", "domain", "ip", "hash", "bitcoin", "image"]

# Anchored whitelists. None => validated by a dedicated function below.
_PATTERNS: dict[str, re.Pattern[str] | None] = {
    "username": re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"),
    # (?!-) keeps the local part from starting with '-' so a validated email can
    # never begin with a dash (preserves the argument-injection guard).
    "email": re.compile(r"^(?!-)[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,24}$"),
    "phone": re.compile(r"^\+?[1-9]\d{6,14}$"),
    "domain": re.compile(
        r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-)){1,}$"
    ),
    "hash": re.compile(r"^(?:[A-Fa-f0-9]{32}|[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})$"),
    "bitcoin": re.compile(r"^(?:bc1[ac-hj-np-z02-9]{11,71}|[13][A-HJ-NP-Za-km-z1-9]{25,39})$"),
    "realname": re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'\-]{0,79}$"),
    "ip": None,
    "image": None,
}


class ValidationError(ValueError):
    pass


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def ip_is_internal(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def is_valid(target: str, ttype: str) -> bool:
    if not target or len(target) > MAX_LEN:
        return False
    if ttype == "ip":
        return _is_ip(target)
    if ttype == "image":
        # Never a free string; the upload path is validated separately by the dispatcher.
        return False
    pat = _PATTERNS.get(ttype)
    return bool(pat and pat.match(target))


def validate(target: str, ttype: str) -> str:
    target = (target or "").strip()
    if ttype not in TARGET_TYPES:
        raise ValidationError(f"Unknown target type: {ttype}")
    if not is_valid(target, ttype):
        raise ValidationError(f"{target!r} is not a valid {ttype}")
    return target


def detect_types(raw: str) -> list[str]:
    """Return candidate types best-first (mirrors the prototype's detection order)."""
    q = (raw or "").strip()
    if not q or len(q) > MAX_LEN:
        return []
    out: list[str] = []
    if is_valid(q, "hash"):
        out.append("hash")
    if is_valid(q, "bitcoin"):
        out.append("bitcoin")
    if "@" in q and is_valid(q, "email"):
        out.append("email")
    if _is_ip(q):
        out.append("ip")
    if is_valid(q, "phone"):
        out.append("phone")
    if is_valid(q, "domain"):
        out.append("domain")
    if " " in q and is_valid(q, "realname"):
        out.append("realname")
    if is_valid(q, "username"):
        out.append("username")
    # de-dup preserving order
    seen: set[str] = set()
    return [t for t in out if not (t in seen or seen.add(t))]


def best_type(raw: str) -> str | None:
    types = detect_types(raw)
    return types[0] if types else None


# Tokens we allow templates to interpolate.
_PLACEHOLDER_RE = re.compile(r"\{(bin|target)\}")
# A template literal token may only contain these (no shell is used, but we keep
# templates boring so a custom tool can't smuggle odd bytes into argv).
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:=/@,+\-{}]+$")


def build_argv(run_template: str, bin_path: str, target: str) -> list[str]:
    """Turn a run template into an argv list.

    The template is split on whitespace into tokens; ``{bin}`` and ``{target}``
    are substituted within each token. Because the split happens first, a target
    is always a single argv element and can never introduce extra arguments.
    """
    argv: list[str] = []
    for tok in run_template.split():
        if not _SAFE_TOKEN_RE.match(tok):
            raise ValidationError(f"Unsafe token in run template: {tok!r}")
        if tok == "{target}":
            argv.append(target)
            continue
        if tok == "{bin}":
            argv.append(bin_path)
            continue
        sub = tok.replace("{bin}", bin_path).replace("{target}", target)
        argv.append(sub)
    if not argv:
        raise ValidationError("Empty run template")
    return argv
