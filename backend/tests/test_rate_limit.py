"""Rate-limit client identity."""

from rate_limit import _client_key


def _request(headers=None, client_host="10.0.0.1"):
    return type(
        "Req",
        (),
        {
            "headers": headers or {},
            "client": type("C", (), {"host": client_host})(),
            "scope": {"client": (client_host, 0), "headers": []},
        },
    )()


def test_uses_the_socket_address_without_a_proxy_header():
    assert _client_key(_request()) == "10.0.0.1"


def test_prefers_the_original_client_from_x_forwarded_for():
    req = _request({"x-forwarded-for": "203.0.113.7, 10.0.0.5"})
    assert _client_key(req) == "203.0.113.7"


def test_trims_whitespace_in_the_forwarded_chain():
    req = _request({"x-forwarded-for": "  203.0.113.7  ,10.0.0.5"})
    assert _client_key(req) == "203.0.113.7"
