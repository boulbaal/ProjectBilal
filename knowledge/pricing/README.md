# Pricing

Quotes are calculated by code (`server/pricing.py`) from `rules.yaml`. The AI assistant never does the math itself.

To change a price:
1. Edit the number in `rules.yaml`.
2. Run `cd server && python -m server.pricing --check ../knowledge/pricing/examples.md`. All examples must still match (update an example if the price change is intended to change it).
3. Redeploy with `server/deploy/update.sh`.

To add a product: copy a product block, give it a unique `id`, list the words customers use for it under `aliases` in every language.

Anything that cannot be written as a rule (a discretionary discount, a special deal) is not calculated. The assistant will hold such a request for a human.
