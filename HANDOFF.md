# HANDOFF.md — lol-predictor

> ## 🔴 N+2 REFUTADA — update online K=48 intra-torneio piora vs. prior estático (2026-07-12)
>
> Backtest ad-hoc (fora do harness formal) contra o **MSI 2026 real** (20
> séries, Play-In + Etapa 2, dados colados pelo Leo — torneio já encerrado,
> campeão HLE). Times fora do Top 30 (DCG, LYON, TSW) sem semente real
> usaram `default_seed_elo` 1400. Duas rodadas do mesmo conjunto de jogos:
>
> 1. **Prior estático** (semente de `data/teams_lol.json`, sem update
>    durante o torneio): acurácia 60,0%, Brier série 0,2355, prob. média no
>    vencedor real 60,9%.
> 2. **Update online** (`update_ratings`-equivalente, K=48 fixo BO5, Elo
>    recalculado partida a partida dentro do próprio MSI): acurácia caiu
>    para **50,0%**, Brier piorou para 0,2473.
>
> **Causa**: K=48 aplicado dentro de um mata-mata curto amplifica ruído de
> amostra pequena (séries de alta variância, poucos jogos) em vez de
> reduzi-lo — uma zebra cedo no bracket contamina as previsões dos jogos
> seguintes do MESMO torneio antes de haver sinal suficiente para
> confirmar se é forma real ou variância. Ex.: T1 perde de BLG (3-2, quase
> 50/50) no R1, cai de 1620→1602, e o modelo undervalua T1 nos jogos
> seguintes da chave dos perdedores mesmo T1 seguindo forte. LYON (seed
> 1400, sem histórico algum) seguiu sendo ponto cego nos dois cenários —
> não é falha do Elo, é ausência de dado sobre o time.
>
> **Implicação prática**: update K alto NÃO deve ser aplicado intra-torneio
> em brackets curtos — o ganho de reatividade não compensa o ruído em
> amostra pequena. Ratings ao vivo (Fase 1) devem seguir sendo atualizados
> só entre partidas/rodadas de temporada regular, não dentro do mesmo
> mata-mata. Script do teste não versionado (rodado em scratchpad de
> sessão); reproduzível a partir dos 20 placares reais do MSI 2026 citados
> acima caso vire item formal de backtest.
>
> ## 🟢🔴 FASE 1 CONCLUÍDA — H1 COMPROVADA, H2 REFUTADA (2026-07-11)
>
> Fonte: **Oracle's Elixir** (CSVs 2025+2026 do Google Drive — o S3 antigo
> está 404; IDs da pasta descobertos via navegador). **3.877 mapas**
> ingeridos (LCK/LPL/LEC/LCS/LTA/MSI/WLDs/FST/EWC, 2025-01→2026-07).
> Backtest prequential (prever→atualizar, K=32, burn-in 90d, n medido 3.053)
> com governança completa (harness do critério passou; hipóteses
> pré-registradas antes de rodar).
>
> **H1-LOL (vencedor) COMPROVADA**: Brier 0,4434 vs banda regional 0,4657,
> acerto 64,5%, DM p<1e-4. Calibração levemente subconfiante no favorito —
> vetor de melhoria (N+1). **H2-LOL (abates por time) REFUTADA na direção
> oposta**: média por time PERDE da média da liga nas 3 linhas (DM p<0,001)
> — total de kills é fenômeno de LIGA/patch; o serving usa só a média da
> liga (team_stats vai para `team_stats_pesquisa.json`, não consumido).
>
> Serving materializado: `ratings.json` (Elo vivido de 85 times) +
> `calibration.json` (média/σ de kills por liga, 11 ligas). Relatório:
> `docs/RELATORIO_FASE1.md`. Fase 1b (odds ao vivo em sombra) depende de
> fonte de odds corrente — não existe ainda.

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
