# HANDOFF.md — lol-predictor

> ## 📌 EWC 2026 — replay completo da fase de grupos e agenda restante (2026-07-16)
>
> **Método do replay.** Foram identificadas as 20 séries da fase de grupos
> (15–16/07) e os respectivos formatos públicos. Para cada confronto com dois
> ratings canônicos disponíveis, foi rodado o Elo H1 no snapshot congelado de
> `data/ratings.json` — SHA-256
> `d45a06c250b24fb69a758bd5362c6a803b8829b949f4b1823b5910cd528f262c`,
> mtime 2026-07-14T14:43:50Z — sem update intra-EWC, sem Platt, odds,
> kills, patch, draft, lado, roster ou ajuste regional manual. Só depois a
> saída foi comparada aos resultados públicos. É um **replay retrospectivo
> read-only**, não uma evidência de protocolo forward temporal.
>
> **Todos os resultados auditados:** Grupo A — G2 1–0 FURIA, AG.AL 1–0
> Dplus, Dplus 2–0 FURIA, AG.AL 1–0 G2, Dplus 2–0 G2. Grupo B — Sentinels
> 1–0 Secret Whales/Team Secret, Gen.G 1–0 Karmine Corp, Karmine Corp 2–1
> Secret Whales/Team Secret, Gen.G 1–0 Sentinels, Karmine Corp 2–0
> Sentinels. Grupo C — T1 1–0 GAM, BLG 1–0 Movistar KOI, GAM 2–1 Movistar
> KOI, BLG 1–0 T1, T1 2–0 GAM. Grupo D — JD Gaming 1–0 LYON, HLE 1–0
> MIBR.LØS, MIBR.LØS 2–0 LYON, HLE 1–0 JD Gaming, JD Gaming 2–0 MIBR.LØS.
>
> | Grupo | Jogos válidos | Acertos | Erros |
> |---|---:|---:|---:|
> | A | 5 | 3 | AG.AL 1–0 G2; Dplus 2–0 G2 |
> | B | 5 | 5 | — |
> | C | 5 | 4 | GAM 2–1 Movistar KOI |
> | D | 2 | 1 | JD Gaming 1–0 LYON |
> | **Total** | **17** | **13 (76,5%)** | **4** |
>
> As probabilidades dos favoritos nos 17 confrontos válidos implicavam 12,80
> acertos esperados (75,3%). Realizado: 13. Brier binário de séries: 0,1710
> (0,3419 na convenção multiclasse usada pelo projeto). A boa aderência desta
> rodada não deve ser transformada em edge financeiro nem em validação forward.
>
> **Bloqueios explícitos (VOID, não acerto/erro):** HLE 1–0 MIBR.LØS,
> MIBR.LØS 2–0 LYON e MIBR.LØS 0–2 JD Gaming. O alias de branding
> `MIBR.LØS → LØS` está documentado, mas `LØS` não existe no snapshot de
> ratings canônico. Não foi aplicado seed 1400 ou qualquer ajuste manual. O
> refresh deve resolver a identidade e materializar rating antes de servir
> outra previsão desse time.
>
> **Agenda restante da EWC (ainda aberta):**
>
> | Data | Fase/formato | Confronto | Situação |
> |---|---|---|---|
> | 17/07 | Quartas, MD3 | Hanwha Life Esports × T1 | previsão aberta: HLE 54,3% |
> | 17/07 | Quartas, MD3 | AG.AL / Anyone's Legend × Karmine Corp | previsão aberta: KC 51,6% |
> | 17/07 | Quartas, MD3 | Gen.G × JD Gaming | previsão aberta: Gen.G 80,8% |
> | 17/07 | Quartas, MD3 | Bilibili Gaming × Dplus Kia | previsão aberta: BLG 93,7% |
> | 18/07 | Semifinal 1 | vencedor de QF1 × vencedor de QF2 | pendente de participantes; não prever ainda |
> | 18/07 | Semifinal 2 | vencedor de QF3 × vencedor de QF4 | pendente de participantes; não prever ainda |
> | 19/07 | Disputa de 3º | perdedor de SF1 × perdedor de SF2 | pendente de participantes; não prever ainda |
> | 19/07 | Final | vencedor de SF1 × vencedor de SF2 | pendente de participantes; não prever ainda |
>
> Horários exatos dos playoffs ainda não foram materializados no fixture local;
> registrar em UTC antes da emissão de cada PredictionPoint. Após cada série,
> fechar resultado, Brier, acerto, hashes e commit sem atualizar Elo dentro do
> bracket curto.

> ## 🧪 Replays Tier 1 congelados pré-evento (2026-07-16)
>
> Novo runner read-only: `scripts/replay_tournament.py`. Ele reconstrói o Elo
> com todos os mapas estritamente anteriores ao início da janela e o congela
> durante o torneio; logo, não há lookahead nem reação intra-bracket. A unidade
> é o **mapa**, porque o banco do Oracle's Elixir não oferece um identificador
> de série confiável para todos os eventos. Artefato detalhado por mapa:
> `data/reports/tier1_replay_2026-07-16.json` (hash do banco:
> `b0839df999a59a2fe611e106f69a9899b5c458c5faba758d961be89728332c2b`).
>
> | Evento | Janela | Mapas | Histórico pré-evento | Acerto | Brier (multiclasse) | Log-loss | P média do vencedor real |
> |---|---|---:|---:|---:|---:|---:|---:|
> | MSI 2026 | 28/06–10/07 | 60 | 3.817 | 73,3% | 0,3782 | 0,5558 | 61,0% |
> | Worlds 2025 | 25/09–09/11 | 96 | 2.213 | 66,7% | 0,4477 | 0,6364 | 55,0% |
>
> Ambos são amostras de torneio pequenas, úteis como diagnóstico e não como
> substituto do backtest prequential amplo (n=3.053). Não foram usados Platt,
> kills, odds, patch, draft, lado, roster, ajustes regionais manuais ou shadow.

> ## 🔮 PREVISÕES EM ABERTO — Quartas do EWC 2026 em MD3 (registradas 2026-07-16, jogos 17/07)
>
> Rodadas via `scripts/predict_ewc_opening.py --fixture
> data/fixtures/ewc_quarterfinals_2026.json` (runner read-only, não toca o
> ledger), formato **bo3** (correto pra fase de playoffs do EWC), Elo real
> de `data/ratings.json` (sha256 d45a06c2…, mtime 2026-07-14):
>
> | Confronto | Elo A / B | P(A) / P(B) | Favorito |
> |---|---|---|---|
> | Hanwha Life x T1 | 1787 / 1767 | 54,3% / 45,7% | HLE (quase moeda) |
> | AG.AL x Karmine Corp | 1579 / 1586 | 48,4% / 51,6% | KC (quase moeda) |
> | Gen.G x JD Gaming | 1762 / 1599 | 80,8% / 19,2% | Gen.G |
> | Bilibili Gaming x Dplus Kia | 1858 / 1561 | 93,7% / 6,3% | BLG |
>
> **Achado no processo**: AG.AL é o branding EWC de **"Anyone's Legend"**,
> que TEM Elo real vivido em ratings.json (1578,8, 269 jogos, LPL,
> ACCEPTABLE) — o alias já estava mapeado em
> `data/fixtures/ewc_opening_2026.json`. A previsão "fora do serving" de
> 15/07 (Dplus 77,3% x AG.AL com seed 1400) foi feita sem saber disso;
> com o Elo real, AG.AL era na verdade ~2 pontos ACIMA do Dplus — o erro
> daquela previsão foi de resolução de identidade, não do modelo. Fica a
> lição: checar aliases de branding de torneio antes de aceitar seed.
> Registrar os placares reais aqui quando as quartas terminarem.

> ## ✅ RESULTADOS — EWC abertura + final do MSI, loop fechado (2026-07-16)
>
> Resultados reais colhidos da web (Liquipedia/imprensa) em 16/07 para
> fechar o loop acerto/erro das previsões registradas em 14-15/07.
> Todos os jogos de abertura do EWC foram **MD1** (as previsões foram
> geradas em bo3 — pra grading de vencedor o favorito é o mesmo; a prob.
> comparável em MD1 é a de MAPA, não a de série).
>
> **Final do MSI 2026 (12/07, Daejeon)**: **HLE 3x2 BLG — HLE campeã** ✅.
> Do parcial 0x1 registrado: BLG venceu mapas 2-3, HLE fechou 4-5. O
> modelo dava P(HLE campeã | 0x1) = 75,9% — acerto da previsão pontual.
>
> **EWC 2026 — jogos de abertura (15/07), serving oficial (6 jogos)**:
>
> | Confronto | Previsto (série / mapa) | Resultado | Acerto |
> |---|---|---|---|
> | Gen.G x Karmine Corp | Gen.G 82,5% / 73,4% | Gen.G 1-0 | ✅ |
> | Sentinels x Team Secret | Sentinels 51,0% / 50,7% | Sentinels 1-0 | ✅ (moeda) |
> | Bilibili Gaming x Movistar KOI | BLG 93,8% / 84,9% | BLG 1-0 | ✅ |
> | T1 x GAM Esports | T1 95,5% / 87,2% | T1 1-0 | ✅ |
> | G2 Esports x FURIA | G2 96,5% / 88,9% | G2 1-0 | ✅ |
> | LYON x JD Gaming | LYON 63,5% / 59,1% | **JDG 1-0** | ❌ |
>
> **5/6 no vencedor (83%)**. O erro foi justamente o jogo de menor
> confiança envolvendo LYON — ponto cego já conhecido da N+2 (LYON sem
> histórico ingerido, Elo pouco confiável).
>
> **Fora do serving (seeds 1400, previsões sob demanda de 15/07)**:
>
> | Confronto | Previsto | Resultado | Acerto |
> |---|---|---|---|
> | Dplus KIA x AG.AL | Dplus 77,3% | **AG.AL 1-0** | ❌ |
> | Hanwha Life x MIBR.LOS | HLE 97,3% | HLE 1-0 | ✅ |
>
> Os dois erros do dia (LYON, AG.AL) são os confrontos onde o modelo tinha
> menos informação. AG.AL não era zebra qualquer: venceu também o G2 na
> final superior e **liderou o Grupo A** (G2 acabou eliminado 0-2 pelo
> Dplus Kia na decisão inferior — Dplus também classificou). MIBR.LOS,
> outro seed 1400, eliminou LYON 2-0 antes de cair 0-2 pro JDG.
>
> **Dado órfão**: `predictions.jsonl` linha 2 registra "Karmine Corp x
> Movistar KOI" — esse confronto nunca existiu no EWC (KC caiu no Grupo B,
> KOI no C). Previsão especulativa sem jogo real; tratar como VOID no
> grading, não como erro.
>
> Classificados às quartas (17/07): HLE x T1, AG.AL x KC, Gen.G x JDG,
> BLG x Dplus Kia.

> ## 🟢 FIX — duplicata "Dplus KIA"/"Dplus Kia" em ratings.json (2026-07-15)
>
> Causa raiz confirmada nos CSVs brutos (`data/raw/2025_oe.csv`,
> `2026_oe.csv`): o **Oracle's Elixir grafa o time como "Dplus Kia"**
> (minúsculo no "Kia"), enquanto `data/teams_lol.json` semeou o nome como
> **"Dplus KIA"** (maiúsculo). O `scripts/backtest_walkforward.py`
> inicializa o dicionário de Elo com as chaves do teams_lol.json e depois
> atualiza usando o nome exato que vem do OE — como as grafias não batem,
> ele criou uma chave NOVA ("Dplus Kia") em vez de atualizar a existente.
> Resultado: "Dplus KIA" ficou congelada em 1540,0 (idêntica ao
> `initial_elo`, nunca recebeu um update real) enquanto "Dplus Kia"
> acumulou o Elo vivido de ~1.560 partidas/linhas do OE (1560,8).
>
> **Fix**: renomeada a entrada em `data/teams_lol.json` de "Dplus KIA" →
> "Dplus Kia" (grafia canônica do OE); removida a chave morta "Dplus KIA"
> de `data/ratings.json`, mantendo só "Dplus Kia": 1560,8 (o Elo real).
> Agora toda resolução (exata ou substring) converge pro rating aprendido.
> Suíte (31 testes) e CI seguem verdes. Vale conferir se outros times têm
> o mesmo tipo de mismatch de grafia entre `teams_lol.json` e o OE antes
> de confiar cegamente nos 30 times semeados — este caso só foi achado
> porque alguém pediu previsão pro time manualmente.
>
> ## 📋 Previsões EWC 2026-07-15 (com o fix do resolve_team)
>
> Reteste pós-fix do resolve_team (ver entrada abaixo), 8 jogos de abertura
> do Esports World Cup, `EloModel.predict_match` formato bo3 direto (não
> via CLI `src.predict`), Elo real de `data/ratings.json`:
>
> | Confronto | Elo A / B | P(A) / P(B) | Favorito |
> |---|---|---|---|
> | Team Secret x Sentinels | 1438 / 1443 | 49,0% / 51,0% | Sentinels (quase moeda) |
> | Gen.G x Karmine Corp | 1762 / 1586 | 82,5% / 17,5% | Gen.G |
> | Bilibili Gaming x Movistar KOI | 1858 / 1558 | 93,8% / 6,2% | Bilibili Gaming |
> | GAM Esports x T1 | 1434 / 1767 | 4,5% / 95,5% | T1 |
> | G2 Esports x FURIA | 1708 / 1347 | 96,5% / 3,5% | G2 Esports |
> | JD Gaming x LYON | 1599 / 1663 | 36,5% / 63,5% | LYON |
>
> **Fora do serving oficial** (Leo pediu depois um número mesmo assim, sob
> demanda, calculado à mão fora do `resolve_team` com `win_probability`/
> `series_probs` direto e `default_seed_elo=1400` do config.yaml — NÃO é
> Elo aprendido, é placeholder genérico, tratar como quase sem informação):
>
> | Confronto | Elo A | Elo B (seed) | P(A) / P(B) | Favorito |
> |---|---|---|---|---|
> | Dplus KIA x AG.AL | 1540,0 | 1400,0* | 77,3% / 22,7% | Dplus KIA |
> | Hanwha Life Esports x MIBR.LOS | 1787,3 | 1400,0* | 97,3% / 2,7% | Hanwha Life Esports |
>
> AG.AL e MIBR.LOS não têm nenhum registro nem em `teams_lol.json` nem em
> `ratings.json` (o Oracle's Elixir da Fase 1 nunca os ingeriu).
> `resolve_team` corretamente recusa esses dois com "time desconhecido" em
> vez de inventar um seed silencioso — comportamento mantido de propósito,
> não é bug; os números acima só existem porque foram pedidos explicitamente
> fora do caminho oficial.
>
> **Dado sujo achado no processo**: `data/ratings.json` tem `"Dplus KIA"`
> (1540,0) e `"Dplus Kia"` (1560,8) como duas entradas separadas — mesma
> equipe, capitalização diferente, não deduplicada na ingestão da Fase 1.
> Não corrigido ainda; vale investigar `scripts/atualiza_semanal.py`/pipeline
> de ingest do Oracle's Elixir antes de usar esse time com frequência,
> porque a previsão muda dependendo de qual grafia é passada.
>
> Formato usado nas duas tabelas: BO3 (`default_format` do config.yaml) —
> Leo confirmou depois o formato real do EWC 2026: **Fase de Grupos =
> MD1**, **Playoffs/eliminação = MD3**, **Grande Final = MD5**. O serving
> hoje não modela isso — `default_format` é um valor único fixo pro
> torneio inteiro, não varia por etapa. Refazer as previsões da fase de
> grupos acima com `--format bo1` deveria mudar a probabilidade de série
> (não a de mapa) pra mais perto do zebra, já que BO1 reduz a vantagem do
> favorito. Pendente: nenhum mecanismo hoje passa a etapa do torneio pro
> `predict` — teria que ser um argumento manual por chamada (`--format
> bo1` na fase de grupos, `bo3` nos playoffs, `bo5` só na final), não dá
> pra automatizar sem saber em que fase cada confronto está.
>
> ## 🟢 FIX — resolve_team não enxergava times extras de ratings.json (2026-07-14)
>
> Achado testando previsões do Esports World Cup (15/07): `src.predict`
> falhava com "time desconhecido" para FURIA, Sentinels, Team Secret, GAM
> Esports e LYON — apesar desses times terem Elo REAL vivido em
> `data/ratings.json` (a Fase 1 ingeriu mais times do Oracle's Elixir do
> que o Top 30 semeado em `teams_lol.json`). Causa: `resolve_team()`
> (`src/config.py`) só buscava nos 30 times fixos do teams_lol.json,
> nunca olhava as chaves extras de `ratings.json`.
>
> **Fix**: `resolve_team` agora cai para `load_rating_names()` (nomes de
> `ratings.json`) quando não acha no Top 30 — exact match e depois
> substring única, mesmo contrato de erro de antes. Times só encontrados
> em `ratings.json` retornam `{"name": ...}` (sem `region`/`initial_elo`,
> que só existem no teams_lol.json); `EloModel` já lia o Elo real desses
> times corretamente, o bloqueio era só na resolução do nome. Suíte
> (31 testes) e CI seguem verdes; comportamento dos 30 times Tier 1 não
> mudou (mesmos testes de `resolve_team("t1")["region"]` etc. continuam
> passando).

> ## ✅ FECHADA (ver entrada de 2026-07-16 no topo: HLE 3x2, acerto) — Final do MSI 2026 (BLG x HLE), registrada em 2026-07-12
>
> Série ainda não terminada: placar parcial **BLG 0 x 1 HLE** (Bo5). Usando
> o prior estático (mesma semente de `data/teams_lol.json`, sem update
> online intra-torneio — ver refutação N+2 abaixo) com Elo pré-final BLG
> 1615 x HLE 1650: P(HLE vence um mapa) = 55,0%. Condicionando no placar
> atual (HLE precisa +2, BLG precisa +3):
>
> - **P(HLE fecha a série e é campeã) = 75,9%**
> - P(BLG vira a série e é campeã) = 24,1%
>
> Previsão do modelo: **Hanwha Life Esports campeã do MSI 2026**. Registrar
> o placar final aqui quando sair, pra fechar o loop acerto/erro dessa
> previsão pontual (não é backtest formal, é chute do serving em cima de
> uma série real em andamento).
>
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
