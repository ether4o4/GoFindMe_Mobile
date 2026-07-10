import pytest

from app.validators import (ValidationError, build_argv, detect_types, is_valid,
                            validate)

VALID = {
    "username": ["johndoe", "a_b-c.1"],
    "email": ["alice@example.com", "a.b+c@sub.example.co"],
    "phone": ["+14155550123", "14155550123"],
    "domain": ["example.com", "a.b.example.io"],
    "ip": ["8.8.8.8", "2001:4860:4860::8888"],
    "hash": ["d41d8cd98f00b204e9800998ecf8427e", "a" * 64],
    "bitcoin": ["1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"],
    "realname": ["John Q. Public"],
}

# Shell metacharacters / arg-injection / traversal — must be rejected for EVERY type
# (realname's charset excludes all of these too).
INJECTION = [
    "; rm -rf /", "$(reboot)", "`id`", "a && b", "a|b", "-oProxyCommand=x",
    "--config=/etc/passwd", "../../etc/passwd", "a\nb", "<script>", "'", '"',
]

# Whitespace is safe under list-form argv but must not pass for tool-fed types.
TOOL_FED_TYPES = ("username", "email", "domain", "phone", "hash", "bitcoin", "ip")


@pytest.mark.parametrize("ttype,samples", VALID.items())
def test_valid_samples_pass(ttype, samples):
    for s in samples:
        assert is_valid(s, ttype), f"{s} should be valid {ttype}"
        assert validate(s, ttype) == s


@pytest.mark.parametrize("payload", INJECTION)
def test_injection_rejected_everywhere(payload):
    for ttype in ("username", "email", "domain", "phone", "hash", "bitcoin", "realname", "ip"):
        assert not is_valid(payload, ttype), f"{payload!r} wrongly valid as {ttype}"


@pytest.mark.parametrize("payload", ["a b", "john\tdoe", "a b c"])
def test_whitespace_rejected_for_tool_fed_types(payload):
    for ttype in TOOL_FED_TYPES:
        assert not is_valid(payload, ttype), f"{payload!r} wrongly valid as {ttype}"


def test_overlong_rejected():
    assert not is_valid("a" * 300, "username")


def test_leading_dash_rejected():
    assert not is_valid("-rf", "username")
    assert not is_valid("-x.com", "domain")
    # email local part must not start with '-' (argument-injection guard)
    assert not is_valid("-t@example.com", "email")
    assert not is_valid("--upload-file@a.co", "email")
    assert is_valid("alice@example.com", "email")


def test_internal_ip_still_valid_type_but_flagged():
    from app.validators import ip_is_internal
    assert is_valid("192.168.1.1", "ip")
    assert ip_is_internal("192.168.1.1")
    assert not ip_is_internal("8.8.8.8")


def test_detect_order():
    assert detect_types("alice@example.com")[0] == "email"
    assert detect_types("8.8.8.8")[0] == "ip"
    assert detect_types("a" * 64)[0] == "hash"
    assert detect_types("John Smith")[0] == "realname"
    assert detect_types("johndoe")[0] == "username"


def test_build_argv_keeps_target_discrete():
    argv = build_argv("{bin} -u {target}", "/usr/bin/sherlock", "johndoe")
    assert argv == ["/usr/bin/sherlock", "-u", "johndoe"]


def test_build_argv_embedded_substitution():
    argv = build_argv("{bin} --url=https://{target}", "/x/katana", "example.com")
    assert argv == ["/x/katana", "--url=https://example.com"]


def test_build_argv_rejects_unsafe_token():
    with pytest.raises(ValidationError):
        build_argv("{bin} ; rm {target}", "/x/tool", "t")
