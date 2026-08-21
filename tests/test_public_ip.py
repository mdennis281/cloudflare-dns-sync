from cfdns.public_ip import extract


def test_extracts_plain_ipv4_body():
    assert extract("93.184.216.34\n", 4) == "93.184.216.34"


def test_extracts_ipv4_from_surrounding_html():
    body = "<html><head><title>Current IP Check</title></head><body>Current IP Address: 8.8.4.4</body></html>"
    assert extract(body, 4) == "8.8.4.4"


def test_skips_private_and_malformed_addresses():
    assert extract("999.1.1.1 192.168.0.5 1.1.1.1", 4) == "1.1.1.1"


def test_skips_non_routable_documentation_range():
    assert extract("203.0.113.7", 4) is None


def test_ipv4_response_is_rejected_when_ipv6_was_asked_for():
    # api6.ipify.org falls back to IPv4 on an IPv4-only host; an A address
    # must never end up in an AAAA record.
    assert extract("93.184.216.34", 6) is None


def test_extracts_ipv6():
    assert extract("2606:4700:4700::1111\n", 6) == "2606:4700:4700::1111"
