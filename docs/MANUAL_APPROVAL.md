# Aprovação manual

Mesmo após o gate financeiro retornar `GO`, `--real` exige um JSON local com
`schema_version: 1`, `status: "APPROVED"`, `approval_id`, `approved_by`,
`approved_at`, `expires_at` e `bet_fingerprint`. O fingerprint amarra a
aprovação à seleção, odds, probabilidade e banca da ordem exata.

O comando só registra o bilhete no ledger; não integra nem envia ordens para
qualquer casa de apostas.
