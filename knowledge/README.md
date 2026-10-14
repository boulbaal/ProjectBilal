# knowledge/

Everything the assistant knows about your business. The service reads these files on every request. Change a file, redeploy (`server/deploy/update.sh`), behaviour changes.

| File | What | Who fills it |
|---|---|---|
| `company.md` | Facts: what you sell, where, hours, languages | setup, then you |
| `faq.md` | Questions customers ask and your answers | setup from your history, then you |
| `style.md` | How you write, with real examples | setup from your history |
| `pricing/rules.yaml` | How a quote is calculated | setup with you, verified against real quotes |
| `pricing/examples.md` | Real quotes used to verify the rules | setup |
| `escalation.md` | When a human must approve, what never to say | setup with you |
| `blocklist.txt` | Numbers/addresses the assistant never replies to (gitignored) | you |
| `raw/` | Mail and chat exports used for training (gitignored, never committed) | setup |

Rules:
- No customer names, phone numbers or addresses in committed files.
- No prices anywhere except `pricing/rules.yaml`.
- If it is not in these files, the assistant does not know it and will escalate.
