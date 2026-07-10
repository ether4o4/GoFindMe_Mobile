"""Server-side provider lookups for key-gated (and a few keyless) OSINT APIs.

Calling these from the server (not the browser) is what removes the CORS wall.
Each provider exposes ``test`` (cheap auth check) and ``lookup`` (returns a
normalized ProviderResult with a small shared ``summary`` plus the raw payload).
Request hosts are hardcoded per provider — the user-supplied target only ever
lands in a path/query parameter (httpx URL-encodes it), never the host (SSRF).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .config import settings
from .validators import ip_is_internal

RAW_CAP = 200_000  # chars of raw JSON kept per finding


@dataclass
class ProviderResult:
    provider: str
    ok: bool
    target: str
    summary: dict
    raw: Any | None = None
    error: str | None = None
    status_code: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# Minimal set of multi-label public suffixes so we can derive a registrable
# domain without shipping the full Public Suffix List. Good enough to turn a deep
# host (a.b.example.co.uk) into its org domain (example.co.uk).
_MULTI_SUFFIX = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "co.jp", "co.nz", "co.za",
    "com.au", "net.au", "org.au", "com.br", "com.mx", "co.in", "co.kr", "com.cn",
    "com.tr", "com.sg", "com.hk", "com.tw", "co.il", "com.ua",
}


def registrable_domain(host: str) -> str | None:
    """Best-effort eTLD+1: a.b.tubi.io -> tubi.io ; x.example.co.uk -> example.co.uk."""
    host = (host or "").strip().strip(".").lower()
    if not host or "." not in host:
        return None
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in _MULTI_SUFFIX:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def make_client() -> httpx.AsyncClient:
    s = settings()
    verify: Any = s.ca_bundle if s.ca_bundle else True
    return httpx.AsyncClient(
        trust_env=True,
        verify=verify,
        timeout=httpx.Timeout(20.0),
        headers={"User-Agent": "GoFindMe/1.0 (+https://github.com/ether4o4/gofindme)"},
        follow_redirects=False,
    )


def _auth_error(code: int) -> str | None:
    if code in (401, 403):
        return "invalid_or_unauthorized_key"
    if code == 429:
        return "rate_limited"
    if code >= 500:
        return f"upstream_error_{code}"
    return None


class Provider:
    name: str = ""
    requires_key: bool = True
    vault_key: str | None = None
    input_types: list[str] = []
    needs_two_part: bool = False  # key stored as "a:b"
    pricing: str = "freemium"     # free | freemium | paid  (for the UI free/paid split)

    async def test(self, client: httpx.AsyncClient, key: str | None) -> ProviderResult:
        raise NotImplementedError

    async def lookup(self, client: httpx.AsyncClient, key: str | None,
                     target: str, ttype: str) -> ProviderResult:
        raise NotImplementedError

    # helpers
    def ok(self, target, summary, raw=None, code=None) -> ProviderResult:
        return ProviderResult(self.name, True, target, summary, raw, None, code)

    def fail(self, target, error, code=None) -> ProviderResult:
        return ProviderResult(self.name, False, target, {}, None, error, code)

    async def _json(self, client, method, url, **kw):
        try:
            r = await client.request(method, url, **kw)
        except httpx.HTTPError as exc:
            return None, None, f"request_failed: {type(exc).__name__}"
        err = _auth_error(r.status_code)
        if err:
            return r, None, err
        try:
            return r, r.json(), None
        except Exception:
            return r, None, "bad_json"


# --------------------------------------------------------------------------
class CrtSh(Provider):
    name, requires_key, input_types = "crtsh", False, ["domain"]

    async def test(self, client, key):
        return await self.lookup(client, key, "example.com", "domain")

    async def lookup(self, client, key, target, ttype):
        # Query the registrable domain, not the exact host — that's where the
        # related subdomains/infrastructure actually live (a.b.tubi.io -> tubi.io).
        base = registrable_domain(target) or target
        url = f"https://crt.sh/?q=%25.{base}&output=json"
        r, data, err = await self._json(client, "GET", url, timeout=35.0)
        if err:
            return self.fail(target, err, r.status_code if r else None)
        names = set()
        for row in (data or []):
            for name in str(row.get("name_value", "")).splitlines():
                n = name.strip().lstrip("*.").lower()
                if n and "@" not in n and " " not in n:
                    names.add(n)
        subs = sorted(names)
        return self.ok(target, {"found": bool(subs), "count": len(subs),
                                "base_domain": base, "subdomains": subs[:200]},
                       (data or [])[:200])


class Shodan(Provider):
    name, vault_key, input_types = "shodan", "shodan", ["ip", "domain"]

    async def test(self, client, key):
        r, data, err = await self._json(client, "GET",
                                        f"https://api.shodan.io/api-info?key={key}")
        if err:
            return self.fail("api-info", err, r.status_code if r else None)
        return self.ok("api-info", {"found": True, "plan": (data or {}).get("plan")}, data)

    async def lookup(self, client, key, target, ttype):
        if ttype == "ip":
            if ip_is_internal(target):
                return self.fail(target, "internal_ip_refused")
            url = f"https://api.shodan.io/shodan/host/{target}?key={key}"
        else:
            url = f"https://api.shodan.io/dns/domain/{target}?key={key}"
        r, data, err = await self._json(client, "GET", url)
        if err:
            return self.fail(target, err, r.status_code if r else None)
        d = data or {}
        if ttype == "ip":
            summary = {"found": True, "ports": d.get("ports", []), "org": d.get("org"),
                       "country": d.get("country_name"), "hostnames": d.get("hostnames", [])}
        else:
            subs = d.get("subdomains", [])
            summary = {"found": bool(subs), "count": len(subs), "subdomains": subs[:50]}
        return self.ok(target, summary, d)


class Censys(Provider):
    name, vault_key, input_types, needs_two_part = "censys", "censys", ["ip", "domain"], True

    def _auth(self, key):
        uid, _, secret = (key or "").partition(":")
        return (uid, secret)

    async def test(self, client, key):
        r, data, err = await self._json(client, "GET",
                                        "https://search.censys.io/api/v1/account",
                                        auth=self._auth(key))
        if err:
            return self.fail("account", err, r.status_code if r else None)
        return self.ok("account", {"found": True, "quota": (data or {}).get("quota")}, data)

    async def lookup(self, client, key, target, ttype):
        if ttype != "ip":
            return self.fail(target, "censys lookup supports ip in v1")
        if ip_is_internal(target):
            return self.fail(target, "internal_ip_refused")
        r, data, err = await self._json(client, "GET",
                                        f"https://search.censys.io/api/v2/hosts/{target}",
                                        auth=self._auth(key))
        if err:
            return self.fail(target, err, r.status_code if r else None)
        result = (data or {}).get("result", {})
        services = result.get("services", [])
        return self.ok(target, {"found": True, "count": len(services),
                                "ports": [s.get("port") for s in services]}, result)


class VirusTotal(Provider):
    name, vault_key, input_types = "virustotal", "virustotal", ["hash", "domain", "ip"]

    async def test(self, client, key):
        r, data, err = await self._json(client, "GET",
                                        "https://www.virustotal.com/api/v3/domains/google.com",
                                        headers={"x-apikey": key or ""})
        if err:
            return self.fail("test", err, r.status_code if r else None)
        return self.ok("test", {"found": True}, None)

    async def lookup(self, client, key, target, ttype):
        path = {"hash": "files", "domain": "domains", "ip": "ip_addresses"}[ttype]
        r, data, err = await self._json(
            client, "GET", f"https://www.virustotal.com/api/v3/{path}/{target}",
            headers={"x-apikey": key or ""})
        if r is not None and r.status_code == 404:
            return self.ok(target, {"found": False}, None, 404)
        if err:
            return self.fail(target, err, r.status_code if r else None)
        attrs = (data or {}).get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats", {})
        return self.ok(target, {"found": True, "malicious": stats.get("malicious", 0),
                                "suspicious": stats.get("suspicious", 0),
                                "reputation": attrs.get("reputation")}, attrs)


class HIBP(Provider):
    name, vault_key, input_types = "hibp", "hibp", ["email"]

    async def test(self, client, key):
        # /breaches needs no key but validates connectivity; key check via a benign account.
        r, data, err = await self._json(
            client, "GET",
            "https://haveibeenpwned.com/api/v3/breachedaccount/test@example.com?truncateResponse=true",
            headers={"hibp-api-key": key or "", "User-Agent": "GoFindMe"})
        if r is not None and r.status_code in (200, 404):
            return self.ok("test", {"found": True}, None, r.status_code)
        return self.fail("test", err or "unexpected", r.status_code if r else None)

    async def lookup(self, client, key, target, ttype):
        r, data, err = await self._json(
            client, "GET",
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{target}?truncateResponse=false",
            headers={"hibp-api-key": key or "", "User-Agent": "GoFindMe"})
        if r is not None and r.status_code == 404:
            return self.ok(target, {"found": False, "breaches": 0, "names": []}, None, 404)
        if err:
            return self.fail(target, err, r.status_code if r else None)
        names = [b.get("Name") for b in (data or [])]
        return self.ok(target, {"found": bool(names), "breaches": len(names),
                                "names": names[:50]}, data)


class Hunter(Provider):
    name, vault_key, input_types = "hunter", "hunter", ["domain", "email"]

    async def test(self, client, key):
        r, data, err = await self._json(client, "GET",
                                        f"https://api.hunter.io/v2/account?api_key={key}")
        if err:
            return self.fail("account", err, r.status_code if r else None)
        return self.ok("account", {"found": True}, (data or {}).get("data"))

    async def lookup(self, client, key, target, ttype):
        if ttype == "email":
            url = f"https://api.hunter.io/v2/email-verifier?email={target}&api_key={key}"
        else:
            url = f"https://api.hunter.io/v2/domain-search?domain={target}&api_key={key}"
        r, data, err = await self._json(client, "GET", url)
        if err:
            return self.fail(target, err, r.status_code if r else None)
        d = (data or {}).get("data", {})
        if ttype == "email":
            summary = {"found": True, "status": d.get("status"), "score": d.get("score")}
        else:
            emails = d.get("emails", [])
            summary = {"found": bool(emails), "count": len(emails),
                       "emails": [e.get("value") for e in emails[:50]]}
        return self.ok(target, summary, d)


class GreyNoise(Provider):
    name, requires_key, vault_key, input_types = "greynoise", False, "greynoise", ["ip"]

    async def test(self, client, key):
        return await self.lookup(client, key, "8.8.8.8", "ip")

    async def lookup(self, client, key, target, ttype):
        if ip_is_internal(target):
            return self.fail(target, "internal_ip_refused")
        headers = {"key": key} if key else {}
        r, data, err = await self._json(
            client, "GET", f"https://api.greynoise.io/v3/community/{target}", headers=headers)
        if r is not None and r.status_code == 404:
            return self.ok(target, {"found": False, "noise": False}, None, 404)
        if err:
            return self.fail(target, err, r.status_code if r else None)
        d = data or {}
        return self.ok(target, {"found": True, "noise": d.get("noise"),
                                "classification": d.get("classification"),
                                "name": d.get("name")}, d)


class AbuseIPDB(Provider):
    name, vault_key, input_types = "abuseipdb", "abuseipdb", ["ip"]

    async def test(self, client, key):
        return await self.lookup(client, key, "8.8.8.8", "ip")

    async def lookup(self, client, key, target, ttype):
        if ip_is_internal(target):
            return self.fail(target, "internal_ip_refused")
        r, data, err = await self._json(
            client, "GET",
            f"https://api.abuseipdb.com/api/v2/check?ipAddress={target}&maxAgeInDays=90",
            headers={"Key": key or "", "Accept": "application/json"})
        if err:
            return self.fail(target, err, r.status_code if r else None)
        d = (data or {}).get("data", {})
        return self.ok(target, {"found": True, "abuse_score": d.get("abuseConfidenceScore"),
                                "country": d.get("countryCode"), "isp": d.get("isp"),
                                "total_reports": d.get("totalReports")}, d)


class SecurityTrails(Provider):
    name, vault_key, input_types = "securitytrails", "securitytrails", ["domain"]

    async def test(self, client, key):
        r, data, err = await self._json(client, "GET",
                                        "https://api.securitytrails.com/v1/ping",
                                        headers={"APIKEY": key or ""})
        if err:
            return self.fail("ping", err, r.status_code if r else None)
        return self.ok("ping", {"found": True}, data)

    async def lookup(self, client, key, target, ttype):
        r, data, err = await self._json(
            client, "GET", f"https://api.securitytrails.com/v1/domain/{target}/subdomains",
            headers={"APIKEY": key or ""})
        if err:
            return self.fail(target, err, r.status_code if r else None)
        subs = (data or {}).get("subdomains", [])
        return self.ok(target, {"found": bool(subs), "count": len(subs),
                                "subdomains": subs[:50]}, data)


class IPInfo(Provider):
    name, vault_key, input_types = "ipinfo", "ipinfo", ["ip"]

    async def test(self, client, key):
        r, data, err = await self._json(client, "GET", f"https://ipinfo.io/json?token={key}")
        if err:
            return self.fail("json", err, r.status_code if r else None)
        return self.ok("json", {"found": True}, data)

    async def lookup(self, client, key, target, ttype):
        if ip_is_internal(target):
            return self.fail(target, "internal_ip_refused")
        r, data, err = await self._json(client, "GET",
                                        f"https://ipinfo.io/{target}/json?token={key}")
        if err:
            return self.fail(target, err, r.status_code if r else None)
        d = data or {}
        return self.ok(target, {"found": True, "org": d.get("org"), "city": d.get("city"),
                                "country": d.get("country"), "hostname": d.get("hostname")}, d)


class EmailRep(Provider):
    name, requires_key, vault_key, input_types = "emailrep", False, "emailrep", ["email"]

    async def test(self, client, key):
        return await self.lookup(client, key, "test@example.com", "email")

    async def lookup(self, client, key, target, ttype):
        headers = {"Key": key} if key else {}
        r, data, err = await self._json(client, "GET",
                                        f"https://emailrep.io/{target}", headers=headers)
        if err:
            return self.fail(target, err, r.status_code if r else None)
        d = data or {}
        details = d.get("details", {})
        return self.ok(target, {"found": True, "reputation": d.get("reputation"),
                                "suspicious": d.get("suspicious"),
                                "blacklisted": details.get("blacklisted"),
                                "data_breach": details.get("data_breach")}, d)


class LeakCheck(Provider):
    name, vault_key, input_types = "leakcheck", "leakcheck", ["email", "username", "phone"]

    async def test(self, client, key):
        r, data, err = await self._json(
            client, "GET", "https://leakcheck.io/api/public?check=test@example.com")
        if r is not None and r.status_code == 200:
            return self.ok("test", {"found": True}, None)
        return self.fail("test", err or "unexpected", r.status_code if r else None)

    async def lookup(self, client, key, target, ttype):
        if key:
            url = f"https://leakcheck.io/api/v2/query/{target}"
            r, data, err = await self._json(client, "GET", url,
                                            headers={"X-API-Key": key})
        else:
            r, data, err = await self._json(
                client, "GET", f"https://leakcheck.io/api/public?check={target}")
        if err:
            return self.fail(target, err, r.status_code if r else None)
        d = data or {}
        found = bool(d.get("found") or d.get("success"))
        return self.ok(target, {"found": found, "count": d.get("found", 0),
                                "sources": d.get("sources", [])[:50] if isinstance(
                                    d.get("sources"), list) else []}, d)


class IntelX(Provider):
    name, vault_key, input_types = "intelx", "intelx", ["email", "domain", "ip", "phone", "bitcoin"]

    async def test(self, client, key):
        r, data, err = await self._json(client, "GET",
                                        "https://2.intelx.io/authenticate/info",
                                        headers={"x-key": key or ""})
        if err:
            return self.fail("info", err, r.status_code if r else None)
        return self.ok("info", {"found": True}, data)

    async def lookup(self, client, key, target, ttype):
        # 2-step: start a search, then read results.
        try:
            start = await client.post("https://2.intelx.io/intelligent/search",
                                      headers={"x-key": key or ""},
                                      json={"term": target, "maxresults": 50, "media": 0})
        except httpx.HTTPError as exc:
            return self.fail(target, f"request_failed: {type(exc).__name__}")
        if _auth_error(start.status_code):
            return self.fail(target, _auth_error(start.status_code), start.status_code)
        try:
            sid = start.json().get("id")
        except Exception:
            return self.fail(target, "bad_json", start.status_code)
        if not sid:
            return self.fail(target, "no_search_id", start.status_code)
        r, data, err = await self._json(
            client, "GET",
            f"https://2.intelx.io/intelligent/search/result?id={sid}&limit=50",
            headers={"x-key": key or ""})
        if err:
            return self.fail(target, err, r.status_code if r else None)
        records = (data or {}).get("records", [])
        return self.ok(target, {"found": bool(records), "count": len(records)}, records[:50])


class DeHashed(Provider):
    name, vault_key, input_types, needs_two_part = "dehashed", "dehashed", \
        ["email", "username", "ip", "phone"], True

    def _auth(self, key):
        email, _, apikey = (key or "").partition(":")
        return (email, apikey)

    async def test(self, client, key):
        r, data, err = await self._json(
            client, "GET", "https://api.dehashed.com/search?query=email:test@example.com&size=1",
            headers={"Accept": "application/json"}, auth=self._auth(key))
        if err:
            return self.fail("test", err, r.status_code if r else None)
        return self.ok("test", {"found": True}, None)

    async def lookup(self, client, key, target, ttype):
        field = {"email": "email", "username": "username", "ip": "ip_address",
                 "phone": "phone"}.get(ttype, "email")
        r, data, err = await self._json(
            client, "GET",
            f"https://api.dehashed.com/search?query={field}:{target}",
            headers={"Accept": "application/json"}, auth=self._auth(key))
        if err:
            return self.fail(target, err, r.status_code if r else None)
        d = data or {}
        entries = d.get("entries") or []
        return self.ok(target, {"found": bool(entries), "count": d.get("total", len(entries))},
                       entries[:50])


_PROVIDERS: dict[str, Provider] = {
    p.name: p for p in [
        CrtSh(), Shodan(), Censys(), VirusTotal(), HIBP(), Hunter(), GreyNoise(),
        AbuseIPDB(), SecurityTrails(), IPInfo(), EmailRep(), LeakCheck(), IntelX(), DeHashed(),
    ]
}


# Direct links to where each provider's API key is obtained.
# Direct deep-links to each provider's API-KEY page (not the marketing homepage).
KEY_URLS = {
    "shodan": "https://account.shodan.io",
    "censys": "https://search.censys.io/account/api",
    "virustotal": "https://www.virustotal.com/gui/my-apikey",
    "hibp": "https://haveibeenpwned.com/API/Key",
    "hunter": "https://hunter.io/api-keys",
    "greynoise": "https://viz.greynoise.io/account/api-key",
    "abuseipdb": "https://www.abuseipdb.com/account/api",
    "securitytrails": "https://securitytrails.com/app/account/credentials",
    "ipinfo": "https://ipinfo.io/account/token",
    "emailrep": "https://emailrep.io/key",
    "leakcheck": "https://leakcheck.io/dashboard",
    "intelx": "https://intelx.io/account?tab=developer",
    "dehashed": "https://dehashed.com/profile",
}

# Where to sign up / read pricing for a source (shown alongside the key link).
SIGNUP_URLS = {
    "crtsh": "https://crt.sh/",
    "shodan": "https://account.shodan.io/register",
    "censys": "https://accounts.censys.io/register",
    "virustotal": "https://www.virustotal.com/gui/join-us",
    "hibp": "https://haveibeenpwned.com/API/Key",
    "hunter": "https://hunter.io/users/sign_up",
    "greynoise": "https://viz.greynoise.io/signup",
    "abuseipdb": "https://www.abuseipdb.com/register",
    "securitytrails": "https://securitytrails.com/app/signup",
    "ipinfo": "https://ipinfo.io/signup",
    "emailrep": "https://emailrep.io/key",
    "leakcheck": "https://leakcheck.io/pricing",
    "intelx": "https://intelx.io/product",
    "dehashed": "https://dehashed.com/register",
}

# Pricing tier per source so the UI can separate FREE from PAID API pages:
#   free     = usable with no payment (often no key at all)
#   freemium = free key / free tier available, paid plans for more volume
#   paid     = an API key requires a paid subscription
PRICING = {
    "crtsh": "free", "greynoise": "free", "emailrep": "freemium",
    "shodan": "freemium", "censys": "freemium", "virustotal": "freemium",
    "hunter": "freemium", "abuseipdb": "freemium", "securitytrails": "freemium",
    "ipinfo": "freemium", "intelx": "freemium",
    "hibp": "paid", "leakcheck": "paid", "dehashed": "paid",
}


def get_provider(name: str) -> Provider | None:
    return _PROVIDERS.get(name)


def list_providers(configured: set[str]) -> list[dict]:
    out = []
    for p in _PROVIDERS.values():
        out.append({
            "name": p.name,
            "requires_key": p.requires_key,
            "vault_key": p.vault_key,
            "input_types": p.input_types,
            "needs_two_part": p.needs_two_part,
            "configured": (not p.requires_key) or (p.vault_key in configured),
            "key_url": KEY_URLS.get(p.name, ""),
            "signup_url": SIGNUP_URLS.get(p.name, ""),
            "pricing": PRICING.get(p.name, "freemium"),
        })
    return out


def providers_for_type(ttype: str) -> list[Provider]:
    return [p for p in _PROVIDERS.values() if ttype in p.input_types]
