# Test plan

Run with the tester agent, in order, with `DRY_RUN=true`. Record every result in `tests/RESULTS.md`. Do not skip. Do not continue past a failure.

You need: a test phone with WhatsApp that is **not** the business number, a test email address that is **not** the business mailbox, and access to the approver inbox.

Legend: **Do** what the owner does. **Expect** what must happen. **Why** the real-world failure this catches. **Evidence** what the tester checks.

## 0. Automated tests

Do: `cd server && python -m pytest ../tests -q`
Expect: all green.
Why: pricing and gatekeeper logic must be right before anything touches a channel.
Evidence: pytest output pasted into RESULTS.md.

## 1. Service is up

Do: open `https://PUBLIC_DOMAIN/health` in a browser.
Expect: JSON with `"ok": true`, `dry_run: true`, a recent timestamp, mode from escalation.md.
Why: proves HTTPS, certificate, DNS and the process. Meta will refuse the webhook otherwise.
Evidence: the JSON.

## 2. Webhook verification

Do: in the Meta developer console, set the callback URL and verify token, click Verify and save.
Expect: Meta shows the webhook as verified; `messages` field subscribed.
Why: without this Meta never calls the service.
Evidence: `journalctl -u projectbilal` shows the GET with `hub.challenge` answered 200.

## 3. Inbound WhatsApp

Do: from the test phone, send "test 1" to the business number.
Expect: within 10 seconds a row in `messages` with channel `whatsapp`, text "test 1". `/health.last_whatsapp_webhook` updated. No reply sent (dry run).
Why: signature verification, JSON parsing and deduplication all sit on this path.
Evidence: `python -m server.db show --last 1`.

## 4. Inbound WhatsApp, duplicate delivery

Do: tester replays the exact webhook body from step 3 (from the log) with a valid signature.
Expect: no new row, log says "duplicate message id ignored".
Why: Meta redelivers. Without dedupe the customer gets two replies.
Evidence: row count unchanged.

## 5. Inbound WhatsApp, bad signature

Do: tester POSTs the same body with a wrong signature.
Expect: HTTP 403, nothing stored.
Why: anyone on the internet can POST to the URL. Only Meta may be believed.
Evidence: log line.

## 6. Inbound email

Do: from the test address, mail the business address, subject "test 6", body "hello, test 6".
Expect: within one poll interval (default 60 s) a row in `messages` with channel `email`, subject "test 6". No reply sent.
Why: IMAP login, UID tracking, parsing.
Evidence: `db show --last 1`, `/health.last_mail_poll`.

## 7. Email, auto-reply must be ignored

Do: tester sends a mail to the business address with header `Auto-Submitted: auto-replied` and subject "Out of office".
Expect: no row, log says "automated mail skipped".
Why: two auto-responders can mail each other forever.
Evidence: log line, row count unchanged.

## 8. Draft generation and language

Do: from the test phone send a simple question that is in faq.md, in the main language. Then the same question in a second allowed language. Then one in a language not allowed.
Expect: three drafts; first two in the right language with the FAQ answer in the business style; third is a short "we will come back to you" and the message is held with reason `language`.
Why: the core promise.
Evidence: `db show drafts --last 3`, owner reads the drafts and says they are ones they would send.

## 9. Hold and approval mail

Do: from the test phone send a message containing a hold keyword (for example "klacht" / "complaint").
Expect: draft status `held`, reason lists the keyword; every approver receives a mail with the customer message, the draft, the reasons and three links. Not in spam.
Why: the safety net.
Evidence: approver shows the mail; `db show drafts --last 1`.

## 10. Approve link

Do: approver clicks **Approve and send** in the mail from step 9.
Expect: page says approved; in dry run nothing is sent but status becomes `approved_dry`. Click again: page says "link already used".
Why: links must be single-use.
Evidence: status, log.

## 11. Reject link

Do: trigger another hold (step 9), approver clicks **Reject**.
Expect: status `rejected`, nothing else happens, no further mails.
Evidence: status.

## 12. Edit link

Do: trigger another hold, approver clicks **Edit**, changes one word, submits.
Expect: status `approved_dry` with the edited text stored as the final draft.
Why: approvers will want to fix a word rather than reject and type everything.
Evidence: `db show drafts --last 1` shows the edited text.

## 13. Pricing end to end

Do: from the test phone send a quote request that matches each of the three confirmed examples in `knowledge/pricing/examples.md`, in natural language ("I need 3 m2 of X with installation, postcode 3500").
Expect: each draft contains the expected total to the cent and the quote lines; no other numbers.
Why: this is where real money is.
Evidence: drafts compared with examples by the owner.

## 14. Pricing with missing input

Do: send a quote request without a required input (no size, or an unknown product).
Expect: the draft asks for exactly the missing input, contains no price.
Why: the assistant must not estimate.
Evidence: draft text.

## 15. Forbidden phrase

Do: send a message that invites a forbidden promise ("can you guarantee delivery by Friday?").
Expect: the draft does not contain any "Never" phrase, or the draft is held with reason `forbidden_phrase`. Either is a pass. A sent promise is a fail.
Evidence: draft text and status.

## 16. Number without quote

Do: send a message that invites a number without a quote ("roughly how much per m2?").
Expect: draft has no currency amount, or is held with reason `number_without_quote`.
Why: the model will try to be helpful. The gatekeeper stops it.
Evidence: draft text and status.

## 17. Conversation context

Do: from the test phone send "and in white?" right after a product question.
Expect: the draft understands it continues the previous message (uses the last messages from the database).
Evidence: draft text.

## 18. 24-hour window

Do: tester marks a stored WhatsApp conversation as last-inbound 25 hours ago in the database, then approves a held draft for it.
Expect: status `held` again with reason `window_closed`, approver notified.
Why: Meta rejects free text outside the window; the approver must know the customer did not get it.
Evidence: status, mail.

## 19. Restart under load

Do: `systemctl restart projectbilal`; while it restarts, send a WhatsApp message from the test phone.
Expect: message appears in the database within 30 seconds (Meta retries while the service is down).
Why: updates happen; messages must not be lost.
Evidence: row.

## 20. Reboot

Do: `sudo reboot` the VPS. Wait two minutes. Open `/health`. Send a test WhatsApp message and a test mail.
Expect: both arrive.
Why: the service must come back on its own.
Evidence: `/health`, rows.

## 21. Backup

Do: tester runs the backup script manually.
Expect: a dated copy of the database in the backup folder, and a cron/timer entry that runs it daily.
Evidence: `ls` output, `systemctl list-timers` or `crontab -l`.

## 22. Go-live (only after 0 to 21 are PASS)

Do: owner says, in their own words, that the assistant may reply to real customers in the mode set in escalation.md. Tester sets `DRY_RUN=false`, redeploys.
Then: repeat step 3 and step 6 with the test phone and test address. The replies must actually arrive on the test phone and in the test inbox.
Expect: both arrive; in `review_all` mode they arrive after approval, in `auto` mode directly.
Evidence: screenshots from the test phone and inbox.

Done. Keep `tests/RESULTS.md`.
