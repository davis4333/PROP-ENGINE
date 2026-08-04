# Cassandra Architecture Quick Reference

```mermaid
flowchart LR
  A[Lines + MLB Context] --> B[Raw Immutable Store]
  B --> C[Point-in-Time Canonical Snapshots]
  C --> D[Feature Pipeline]
  D --> E[Strikeout Model Ensemble]
  E --> F[Calibration + Uncertainty]
  F --> G{Decision Gate}
  G -->|Qualified| H[Publish + X]
  G -->|Weak/Risky| I[No Play Ledger]
  H --> J[Official Results + Grading]
  I --> J
  J --> K[Diagnostics + Drift]
  K --> L[Controlled Experiments]
  L --> E
```

## Ownership boundaries
- Deterministic services: identity, timestamps, snapshots, grading, audits.
- Statistical services: forecasts, uncertainty, calibration, ranking.
- Language AI: explanations and developer assistance grounded in stored facts.
- Human operator: approval, policy changes, model promotion and incident decisions.
