from email.message import EmailMessage

from server import mail


def _msg(**headers):
    m = EmailMessage()
    m["From"] = headers.pop("From", "Klant <klant@example.org>")
    m["Subject"] = headers.pop("Subject", "Vraag")
    for k, v in headers.items():
        m[k] = v
    m.set_content("Hallo, is dit nog beschikbaar?")
    return m


def test_normal_mail_is_not_automated():
    assert not mail.is_automated(_msg(), "assistant@example.test")


def test_auto_submitted_is_skipped():
    assert mail.is_automated(_msg(**{"Auto-Submitted": "auto-replied"}), "x@y")


def test_bulk_and_list_are_skipped():
    assert mail.is_automated(_msg(Precedence="bulk"), "x@y")
    assert mail.is_automated(_msg(**{"List-Unsubscribe": "<mailto:u@x>"}), "x@y")


def test_noreply_sender_is_skipped():
    assert mail.is_automated(_msg(From="noreply@shop.example"), "x@y")
    assert mail.is_automated(_msg(From="MAILER-DAEMON@mx.example"), "x@y")


def test_own_address_is_skipped():
    assert mail.is_automated(_msg(From="assistant@example.test"), "assistant@example.test")


def test_strip_quoted_english_and_dutch():
    text = "Bedankt voor de info.\n\nOp di 3 okt 2026 schreef Shop <info@x>:\n> oude tekst\n> nog meer"
    assert mail.strip_quoted(text) == "Bedankt voor de info."
    text2 = "Thanks!\n\nOn Tue, Oct 3, 2026 at 10:00 AM Shop <info@x> wrote:\n> old"
    assert mail.strip_quoted(text2) == "Thanks!"


def test_body_text_prefers_plain_and_flags_attachment():
    m = EmailMessage()
    m["From"] = "a@b"
    m.set_content("plain part")
    m.add_alternative("<p>html part</p>", subtype="html")
    m.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename="plan.pdf")
    text, attach = mail.body_text(m)
    assert text == "plain part" and attach


def test_html_only_converted():
    m = EmailMessage()
    m["From"] = "a@b"
    m.set_content("<p>Hallo<br>wereld &amp; co</p>", subtype="html")
    text, attach = mail.body_text(m)
    assert "Hallo" in text and "wereld & co" in text and "<p>" not in text and not attach
