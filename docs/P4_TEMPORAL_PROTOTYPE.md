# P4-B temporal contract prototype

This test-only experiment adapts the canonical EWC ledger produced by
`build`, `register_pre_event`, `PredictionPoint`, and `mature_results`. It does
not reopen H4, use market data, call external services, or change production
pipelines, persisted schemas, models, ratings, datasets, Core, or Ops.

The LoL cutoff is the scheduled series start. The canonical maturity horizon
depends on format (BO1/BO3/BO5), while the experiment separately requires an
aware `result_available_at` at or after series start and no later than the
recorded maturation. The PRE_EVENT record must contain no result, Brier, or
correctness value. The MATURED record must preserve its identity and every
original prediction field.

Unlike F1, LoL already has an append-only canonical ledger and a deterministic
`prediction_id`; it predicts a series between two teams and uses the native
two-outcome sum-of-squared-errors Brier scale. The pilot proves offline
temporal integrity only. It does not prove live result-publication latency,
model quality, market value, or cross-domain metric equivalence.

Gap classification:

| Concern | Classification |
|---|---|
| aware prediction/maturity and replay | `CORE_CONTRACT_SUFFICIENT` |
| scheduled cutoff, result publication, ledger transition checks | `CONSUMER_ADAPTER_REQUIRED` |
| canonical JSON/hash helper | `POSSIBLE_FUTURE_CORE_CANDIDATE` |
| BO format, teams, score validation and series Brier | `DOMAIN_SPECIFIC` |
| estimated format horizon versus actual result publication | `SEMANTIC_CONFLICT` unless kept explicit locally |

No Core extraction is proposed from F1 and LoL alone. Further consumers and a
separate human decision are required.

## Evidence-backed comparison

| Element | F1 reference | LoL P4-B |
|---|---|---|
| predicted unit | race winner | BO1/BO3/BO5 series winner |
| predicted_at | snapshot generation | EWC ledger emission |
| cutoff | explicit pre-race cutoff | scheduled series start |
| event_start | scheduled race start | scheduled series start |
| matures_at | explicit result horizon | format estimate: 1h/2.5h/4h |
| result availability | adapter-required timestamp | adapter-required timestamp |
| identity | event and linked artifact hashes | deterministic `prediction_id` |
| local rule | PRE_EVENT/MATURED snapshot link | append-only ledger and valid series score |
| native golden metric | single-winner squared error | two-outcome sum of squared errors |
| adapter needed | yes | yes |
| Core candidate | not yet | not yet |
