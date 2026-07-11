# HANDOFF.md — lol-predictor

> ## 🎮 CRIAÇÃO (2026-07-10)
>
> **Projeto criado. Modelo Elo base implementado. Backtest e operação real
> pendentes.**
>
> Sétimo consumidor do predictor_core (v1.1.0, vendor via `sync_core --write`).
> Python 3.13 em `.venv` (pandas, numpy, scipy, pydantic, httpx, pytest).
>
> Decisões da Fase 0:
> - **Elo por MAPA + combinatória de série** (mesmo kernel do cs-predictor):
>   P(mapa) logística /400; BO1/BO3/BO5, prob da zebra explícita
>   (`prob_underdog`) e mapas esperados pela distribuição exata do placar.
>   K por formato 32/40/48 inferido do placar; soma zero; ratings persistidos
>   em `data/ratings.json` (gitignored).
> - **Totais de abates = Normal** (padrão nba-predictor): total/mapa ≈
>   N(kpg_a+kpg_b, σ). Placeholders DECLARADOS no config
>   (`league_avg_total_kills: 28.0`, `kills_std: 8.0`) — a Fase 1 mede por
>   liga/patch (LCK historicamente mais baixo que LPL). Linha default 24.5.
> - **Semente do Elo**: bandas por liga ancoradas no dado OFICIAL disponível
>   (Power Scores regionais do GPR split-2 2026, lolesports.com: LCK 1425 >
>   LPL 1419 > LEC 1297 > LCS 1081) + sinais editoriais (HLE topo da LCK com
>   Gumayusi/Kanavi; BLG/JDG na LPL; G2 top-3 global). **Ordem intra-liga é
>   estimativa declarada** — o GPR de times individual não carregou no fetch
>   (página truncada) e não existe ranking mundial de 30 canônico. 30 times:
>   LCK 10, LPL 10, LEC 6, LCS 4.
> - **Fonte da Fase 1 em aberto**: Riot API não tem endpoint público estável
>   de esports (match-v5 é de fila ranqueada); a via mais provável é o
>   **Oracle's Elixir** (CSV curado de partidas profissionais). Stub
>   `riot_provider.py` com DataUnavailableError.
> - Governança desde o dia zero: PredictionPoint (matures_at = 1h/2h30/4h
>   por formato), telemetria domínio `lol`, log append-only com override por
>   env; CI 3 barreiras; integridade do vendor + higiene de repo;
>   `.gitattributes` eol=lf.
> - Suíte: **25 verdes**.
>
> Próximo passo (Fase 1, prompt separado): histórico LCK/LPL/LEC/LCS,
> recalibração dos ratings e das médias de abates, backtest walk-forward e o
> fluxo de governança da plataforma (harness → TrialRegistry → GO/NO-GO)
> antes de qualquer aposta.

## O que é o projeto

Laboratório de previsão de partidas de LoL (vencedor, zebra, total de
abates) — Fase 0. Roda 100% local. Idioma do projeto: português. NÃO é
ferramenta de investimento; nenhum edge foi demonstrado.

Máquina do Leo: Windows, `C:\Claude-projetos\Claude\lol-predictor`,
venv `.venv` (Python 3.13.14), atrás de proxy corporativo Volvo.
