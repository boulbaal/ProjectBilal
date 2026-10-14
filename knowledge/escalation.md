# Escalation rules

<!-- The service parses this file. Keep the headings and the "key: value" lines. -->

## Mode
mode: review_all
<!-- review_all: every reply is held for approval. auto: safe replies go out, the rules below decide what is held. Start with review_all for the first week. -->

## Approvers
<!-- one email per line; also set APPROVER_EMAILS in .env -->
-

## Hold when (deterministic)
quote_total_above: 50000
languages_allowed: nl, fr, en
hold_on_attachment: yes
hold_on_keywords: lawyer, advocaat, avocat, klacht, plainte, complaint, schade, dommage, damage, kapot, cassé, broken, terugbetaling, remboursement, refund, korting, remise, discount, garantie, warranty, rechtbank, tribunal
hold_on_number_without_quote: yes
hold_on_window_closed: yes

## Hold when (classified intent, minimum confidence 0 to 1)
complaint: 0.6
discount_or_special_terms: 0.6
existing_order_or_appointment: 0.5
legal_or_warranty: 0.5
unknown_or_cannot_answer: 0.5
human_requested: 0.4

## Never
<!-- phrases the assistant may never produce; checked literally, case-insensitive. Filled during training. -->
- we guarantee
- wij garanderen
- nous garantissons
- delivered by
- geleverd tegen
- livré avant

## After hours
reply_after_hours: yes
after_hours_message:
