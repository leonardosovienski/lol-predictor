# PROMPT — Fase 1 do lol-predictor (dados históricos + backtest walk-forward)

> Rascunho preparado em 2026-07-11, informado pelos ciclos do
> brasileirao-predictor e nba-predictor. Revisar antes de disparar.

**Projeto**: evoluir o lol-predictor da Fase 0 (Elo por bandas de liga +
abates pela média) para um modelo backtestado com dados reais de
LCK/LPL/LEC/LCS, sob a governança da plataforma.

**Contexto do que já existe**: EloModel por mapa + combinatória de série com
`prob_underdog`, totais de abates via Normal (placeholders declarados:
28/mapa, σ8), 30 times semeados por bandas do GPR regional, suíte 25 verdes,
CI 3/3, vendor core v1.1.0.

**Regras**: as mesmas de sempre — nada inventado, governança antes de
resultado, nenhuma aposta real nesta fase.

---

## PASSO 0 — Sondagem da fonte (BLOQUEANTE)

Via mais provável: **Oracle's Elixir** (oracleselixir.com — CSVs curados de
partidas profissionais, por temporada, com resultado E estatísticas por jogo,
incluindo kills). Testar o download direto do CSV 2025/2026; a Riot API é
fallback ruim (esports sem endpoint público estável). Atenção: o CSV é por
JOGO (mapa), com `gameid`/`teamname`/`result`/`kills` — perfeito para o
modelo por mapa.

Entregável: `src/data/riot_provider.py` (ou `oracle_provider.py`) sai de stub
para `fetch_results`/`fetch_team_stats` reais, com cache local do CSV bruto
em `data/raw/` (fora do git).

## PASSO 1 — Dados históricos

- Janela alvo: **temporadas 2025 e 2026** das 4 ligas (LCK, LPL, LEC,
  LCS/LTA) + MSI/Worlds (jogos internacionais calibram força entre ligas —
  sem eles as bandas regionais nunca se corrigem).
- SQLite `data/lol.db`: tabela `games` (game_id, date, league, split,
  team_a, team_b, winner, kills_a, kills_b, duration) e `series` derivada
  (agrupamento por match_id quando o CSV fornecer). Padrão db.py do nba.
- Reconciliação de nomes: CSV usa nomes oficiais longos — mapear para
  `teams_lol.json` (expandir para os times das ligas que aparecerem; o Top 30
  da Fase 0 é semente, não fronteira).
- **Odds**: sem fonte histórica gratuita confirmada para LoL. Mesma divisão
  honesta do CS: **1a = backtest de skill** (Brier/log-loss/calibração vs
  baseline); **1b futura = odds ao vivo em sombra** se 1a passar.

## PASSO 2 — Backtest walk-forward (prequential)

- Elo por mapa processado em ordem cronológica (prever → atualizar), burn-in
  de 1 split.
- **Vencedor**: Brier/log_loss/calibration_table (core) vs baselines "maior
  Elo" e "banda regional da semente". Diebold-Mariano para significância.
- **Abates**: calibrar por LIGA (LCK ≠ LPL em ritmo): média e σ de
  kills_a+kills_b por liga, janela móvel; avaliar o modelo Normal com CRPS ou
  Brier do Over/Under em linhas sintéticas {24.5, 27.5, 30.5} vs baseline
  "média global". Materializar `data/team_stats.json` ({time:
  {kills_per_game}}) e `data/calibration.json` por liga — o serving da Fase 0
  já consome sem mudar código.
- Sensibilidade controlada (= tentativas N+1): K por formato, fator de
  ajuste inter-liga pós-internacionais.

## PASSO 3 — Governança

1. Harness: time sintético com +100 Elo verdadeiro (vencedor) e liga com
   +4 kills/jogo (totais) → pipeline detecta; ruído → rejeita. Atestado.
2. Pré-registro em `data/trials.json` (VERSIONADO):
   - **H1-LOL**: Elo por mapa prevê vencedor melhor que baseline de banda
     regional (Brier, DM p<0,05) em 2025-2026.
   - **H2-LOL**: Normal de abates calibrada por liga tem Brier de O/U melhor
     que a média global nas linhas {24.5, 27.5, 30.5}.
3. Backtest só depois; resultados gravados nas trials.

## PASSO 4 — Recalibração do serving

- `data/ratings.json` da passada prequential (Elo vivido) + team_stats/
  calibration por liga → `model` passa a reportar `elo-fase1`/`kills-fase1`.

## PASSO 5 — Testes e entrega

- Novos testes: parser do CSV, reconciliação de nomes, prequential sem
  lookahead, calibração por liga, harness.
- Suíte ≥ 40 verdes, CI 3/3, tree limpa.
- Relatório `docs/RELATORIO_FASE1.md` com vereditos de H1-LOL/H2-LOL e
  recomendação sobre a Fase 1b (odds ao vivo em sombra). Sem aposta real.
