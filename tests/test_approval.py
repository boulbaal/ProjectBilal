from server import approval


def test_link_signature_verifies_and_rejects_tampering():
    tok = approval.new_token()
    url = approval.link(tok, "approve", "boss@example.test")
    assert url.startswith("https://example.test/approval/approve/")
    sig = url.rsplit("/", 1)[1]
    assert approval.verify_link(tok, "approve", "boss@example.test", sig)
    assert not approval.verify_link(tok, "reject", "boss@example.test", sig)
    assert not approval.verify_link(tok, "approve", "other@example.test", sig)
    assert not approval.verify_link(tok + "x", "approve", "boss@example.test", sig)
