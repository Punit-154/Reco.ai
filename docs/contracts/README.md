# Reco.ai Data Contracts

These contracts are synthetic examples for local development and tests.

Official references:

- Razorpay settlements API: https://razorpay.com/docs/api/settlements/fetch-all/
- Razorpay settlement webhook: https://razorpay.com/docs/webhooks/settlements/
- Razorpay webhook validation: https://razorpay.com/docs/webhooks/validate-test/

Rules:

- Razorpay amounts are represented in paise.
- Bank CSV rupee amounts must be converted to integer paise with decimal-safe parsing.
- Ground truth labels are stored only in fixtures used by evaluation tests.
- Do not feed ground truth labels into the matcher or LLM.
