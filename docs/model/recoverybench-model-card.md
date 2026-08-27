# RecoveryBench model card

Artifact: `recoverybench.v1`

Evidence: `SIMULATED`

Training seed: `20260827`

Artifact checksum: `f20ccfe34e35101e0a62eb91299d40b8501cfc88652d7bd25261c7b3cb20cbf8`

## Intended use

RecoveryBench tests whether a recoverability scorer can rank bounded actions on deterministic,
synthetic failed-subscription cases. It is a development/evaluation artifact, not a production
financial model. Its adapter falls back to deterministic scoring when the artifact is absent, but
the shipping Temporal worker still uses its Phase 1 deterministic scorer and does not invoke this
adapter. The policy engine retains final authority when model integration is added.

## Data and split

The hidden-customer-state generator creates paired treatment and baseline potential outcomes using
no LLM labels. The checked-in dataset contains 1,200 cases: 720 training, 240 calibration, and 240
evaluation. Features are amount at risk in paise, diagnosis, candidate action, tenure, prior
successful payments, failed-attempt count, customer-agent availability, voice consent, and quiet-hour
state. Diagnosis and candidate action are categorical.

## Model and calibration

The artifact is a CatBoost classifier followed by isotonic calibration. The report and manifest are
versioned and checksummed beside `model.cbm` and `calibration.json` under
`ml/recoverybench/artifacts/recoverybench.v1/`.

## Fixed evaluation result

| Metric                         |                     Value |
| ------------------------------ | ------------------------: |
| PR-AUC                         |                  0.672943 |
| Brier score                    |                  0.202311 |
| Top-decile lift                |                  2.000000 |
| Amount-weighted lift           |                  2.031359 |
| Simulated incremental recovery | 7,277,100 paise (₹72,771) |

These values describe one fixed synthetic run. They do not estimate real merchant lift and must be
displayed as “simulated incremental recovery.” Sparse calibration bins and the small 240-case
evaluation split make fine-grained conclusions inappropriate.

## Safety, limitations, and monitoring

- Synthetic hidden states simplify customer behavior and cannot represent real selection bias,
  seasonality, fraud, or provider drift.
- Treatment and baseline outcomes are simulated, not randomized production experiments.
- Voice consent and agent availability are modeled features, not permission to contact or pay.
- The model cannot override opt-out, wrong-person, dispute, already-paid, quiet-hour, contact-limit,
  deadline, kill-switch, approval, or payment-surface rules.
- No model output is payment evidence or eligible for verified revenue accounting.
- Before production, validate calibration and action lift on consented, privacy-reviewed data; add
  drift, subgroup, abstention, and outcome-quality monitoring; and document rollback criteria.

## Reproduction

The implemented build command is:

```powershell
uv run python -m ml.recoverybench.build --seed 20260827 --case-count 1200
uv run pytest ml/recoverybench/tests
```

Regeneration overwrites the checked-in artifact directory and must be reviewed as a versioned model
change. The root `generate:data`, `train`, and `evaluate` scripts currently reference modules that do
not exist; use the command above until the coordinator repairs that shared command contract.
