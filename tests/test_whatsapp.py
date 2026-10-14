import json

from server import whatsapp

SAMPLE = {
    "object": "whatsapp_business_account",
    "entry": [{"id": "WABA", "changes": [{"value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "32400000000", "phone_number_id": "PNID"},
        "contacts": [{"profile": {"name": "Test"}, "wa_id": "32470000000"}],
        "messages": [{"from": "32470000000", "id": "wamid.TEST1", "timestamp": "1700000000",
                      "type": "text", "text": {"body": "hallo, test 1"}}],
    }, "field": "messages"}]}],
}

STATUS = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.X", "status": "delivered"}]}}]}]}


def test_signature_roundtrip():
    body = json.dumps(SAMPLE).encode()
    sig = whatsapp.sign(body, "test-secret")
    assert whatsapp.verify_signature(body, sig, "test-secret")
    assert not whatsapp.verify_signature(body, sig, "other-secret")
    assert not whatsapp.verify_signature(body, "sha256=deadbeef", "test-secret")
    assert not whatsapp.verify_signature(body, None, "test-secret")
    assert not whatsapp.verify_signature(body, sig, "")


def test_parse_text_message():
    msgs, statuses = whatsapp.parse_inbound(SAMPLE)
    assert statuses == []
    assert len(msgs) == 1
    m = msgs[0]
    assert m.message_id == "wamid.TEST1" and m.sender == "32470000000"
    assert m.text == "hallo, test 1" and not m.has_attachment
    assert m.timestamp == 1700000000.0


def test_status_is_not_a_message():
    msgs, statuses = whatsapp.parse_inbound(STATUS)
    assert msgs == [] and statuses[0]["status"] == "delivered"


def test_media_marks_attachment():
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "1", "id": "wamid.IMG", "timestamp": "1", "type": "image", "image": {"id": "123", "caption": "plan"}}]}}]}]}
    msgs, _ = whatsapp.parse_inbound(payload)
    assert msgs[0].has_attachment and msgs[0].text == "plan"
