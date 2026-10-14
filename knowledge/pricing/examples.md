# Pricing examples

<!--
Real quotes used to verify rules.yaml. The check `python -m server.pricing --check knowledge/pricing/examples.md`
must reproduce every "expected_total" to the cent. Format is strict: one YAML block per example.
The example below matches the template rules.yaml. Replace with real quotes during setup.
-->

```yaml
name: template example
inputs:
  product: example_panel
  quantity: 3
  options: [installation]
  postcode: "3500"
expected_total: 453.75
```
