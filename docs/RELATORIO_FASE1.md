# Relatório da Fase 1 — lol-predictor (2026-07-11)

## Fonte e dataset

**Oracle's Elixir** (CSVs públicos no Google Drive; IDs descobertos via
navegador — o S3 antigo está 404 e a página de downloads é SPA). Baixados
2025 (79 MB) e 2026 (48 MB); **3.877 mapas** ingeridos das ligas-alvo
(2025-01-12 → 2026-07-10): LPL 1.258, LCK 904, LEC 552, LTA S 222, LTA N
214, EWC 214, LCS 157, MSI 140, WLDs 96, FST 80, LTA 40.

## Metodologia

Backtest **prequential** (prever antes de atualizar — sem lookahead por
construção): Elo por mapa, K=32, semente = bandas do GPR (Fase 0), times
desconhecidos em 1400; burn-in de 90 dias; métrica só conta mapa em que
ambos os times têm ≥10 de histórico (n medido = 3.053). Governança completa:
harness do critério de decisão PASSOU antes do pré-registro; ambas as
hipóteses registradas antes de qualquer resultado.

## H1-LOL — Elo por mapa vs banda regional congelada

| Métrica | Modelo | Baseline banda | Coin-flip |
|---|---|---|---|
| Brier | **0,4434** | 0,4657 | 0,5000 |
| Log-loss | **0,6346** | 0,6570 | 0,6931 |
| Acerto | 64,5% | — | 50% |
| Diebold-Mariano | **p < 0,0001** | | |

**VEREDITO: COMPROVADA.** O Elo vivido carrega informação real acima da
força regional estática. Calibração boa nas pontas, levemente subconfiante
no meio (faixa 0,2–0,3 prevista → 0,34 observado): favoritos são um pouco
mais fortes do que o modelo diz — vetor natural de melhoria (K maior ou
escala /400 recalibrada = tentativa N+1).

## H2-LOL — Abates: Normal por time vs média da liga

| Linha | n | Brier modelo | Brier liga | DM p |
|---|---:|---:|---:|---:|
| 24,5 | 2.942 | 0,4345 | **0,4206** | 0,0007 |
| 27,5 | 2.942 | 0,5126 | **0,4915** | <0,0001 |
| 30,5 | 2.942 | 0,4933 | **0,4740** | 0,0001 |

**VEREDITO: REFUTADA — na direção oposta.** A média por time PERDE para a
média da liga nas 3 linhas, com significância. Leitura: o total de abates é
dominado pelo estilo da LIGA/patch, e a média por time (janela de 40 mapas)
injeta ruído amostral. Consequência prática: o serving de kills deve usar
**só a média/σ da liga** (data/calibration.json) até uma hipótese nova
(ritmo por lado? matchup de estilos?) entrar como N+1.

## Serving materializado

- `data/ratings.json` — Elo vivido de **85 times** (o predict passa a usar).
- `data/calibration.json` — média/σ do total de kills por liga (11 ligas)
  — ex.: a diferença LCK vs LPL agora é dado, não palpite.
- `data/team_stats_pesquisa.json` — as médias por time ficam disponíveis
  para PESQUISA, mas com nome que o serving NÃO consome (a H2 as refutou;
  `predict_kills_total` sem `team_stats.json` cai na média da liga, que é o
  comportamento validado).

## Fase 1b (futura)

Sem fonte de odds históricas de LoL. Se quiser mercado: coleta ao vivo em
modo sombra (padrão H3 do brasileirão) usando o vencedor (H1 comprovada)
como modelo — precisa de fonte de odds corrente antes de existir.
