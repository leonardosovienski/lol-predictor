"""Contratos da camada de dados — os envelopes que atravessam a fronteira fonte→domínio.

`MarketDataPoint` (OHLCV) e `SignalPoint` (sinal de baixa frequência, macro/sentimento)
carregam `published_at` OBRIGATÓRIO — o instante em que o dado ficou publicamente
disponível, âncora do as-of join contra lookahead. Um conector concreto traduz o
formato nativo de uma API para estes envelopes; o domínio só enxerga os contratos.
"""
from __future__ import annotations

import abc
import copy
from dataclasses import dataclass
from datetime import datetime


class DataUnavailableError(Exception):
    """Nenhuma fonte conseguiu entregar o dado — sinal terminal do Router após esgotar
    todos os provedores. O domínio decide como reagir (pular ativo, degradar, etc.)."""


@dataclass(frozen=True)
class MarketDataPoint:
    """Envelope imutável de um ponto de mercado (OHLCV + metadados de origem).

    `timestamp` = instante do candle (abertura do período). `published_at` = quando o
    dado ficou disponível (âncora anti-lookahead). Para preço de exchange coincidem;
    para fontes de baixa frequência, divergem. `high >= low` e `published_at >=
    timestamp` são invariantes checadas na construção (falha explícita)."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    interval: str
    published_at: datetime

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(
                f"MarketDataPoint inválido para {self.symbol}: high={self.high} < low={self.low}")
        if self.published_at < self.timestamp:
            raise ValueError(
                f"MarketDataPoint inválido para {self.symbol}: published_at "
                f"({self.published_at.isoformat()}) anterior ao timestamp "
                f"({self.timestamp.isoformat()}) — violaria integridade temporal")


@dataclass(frozen=True)
class SignalPoint:
    """Envelope de um sinal de baixa frequência não-OHLCV (Fear&Greed, Selic, IPCA...).

    `published_at` para o as-of join, idêntico em papel ao do MarketDataPoint. Séries
    macro são REVISADAS: cada revisão é um SignalPoint separado, com seu `published_at`
    (quando ficou público) e `vintage` (quando foi coletado). O as-of por published_at
    escolhe o valor vigente em cada data — sem lookahead, sem lógica extra.
      timestamp      : instante do dado (grade do as-of e do max_staleness).
      reference_date : referência semântica (ex.: mês do IPCA); default = timestamp.
      vintage        : quando o dado foi coletado; distingue revisões na persistência."""

    name: str
    timestamp: datetime
    value: float
    source: str
    published_at: datetime
    reference_date: datetime | None = None
    vintage: datetime | None = None

    def __post_init__(self) -> None:
        if self.published_at < self.timestamp:
            raise ValueError(
                f"SignalPoint '{self.name}': published_at anterior ao timestamp "
                "— violaria integridade temporal")


@dataclass(frozen=True)
class PredictionPoint:
    """Envelope do ciclo de vida de uma PREVISÃO: emissão → maturação → resultado.

    O padrão existia implícito em dois consumidores (2026-07-09): o bet_log do
    wc-predictor (logged_at → kickoff → settle) e o close_trial_sharpes do
    previsao-cripto (previsão → D+horizonte → Sharpe por-trade). Este contrato
    torna o ciclo explícito para que funções do core (query de maturação,
    futuro ledger) operem sobre qualquer domínio.

      predicted_at : quando a previsão foi emitida (o "logged_at").
      matures_at   : quando o resultado se torna OBSERVÁVEL (kickoff+jogo,
                     t+horizonte). Invariante: matures_at >= predicted_at —
                     prever o que já maturou é lookahead, barrado na construção.
      value        : o valor previsto (prob, score, classe) — opaco pro core.
      metadata     : contexto de domínio (ativo, mercado, modelo). Opcional.

    `is_mature(now)`: o resultado já é observável? É a query universal que os
    dois consumidores reimplementavam ("o que já posso liquidar/fechar?")."""

    predicted_at: datetime
    matures_at: datetime
    value: object
    metadata: dict | None = None

    def __post_init__(self) -> None:
        # Auditoria hostil 2026-07-17 (rodada predictor_core): o construtor
        # aceitava QUALQUER objeto em predicted_at/matures_at sem checagem de
        # tipo — uma string ISO (sobrevivente comum de um round-trip JSON)
        # passava direto, e o invariante abaixo então comparava strings
        # LEXICOGRAFICAMENTE em vez de cronologicamente (dois offsets
        # diferentes do mesmo instante UTC podem comparar "fora de ordem"
        # como string), podendo tanto aceitar um PredictionPoint realmente
        # inválido quanto rejeitar um válido — e o próprio caminho de erro
        # quebrava com AttributeError ao tentar chamar .isoformat() numa str.
        for field_name in ("predicted_at", "matures_at"):
            value = getattr(self, field_name)
            if not isinstance(value, datetime):
                raise TypeError(
                    f"PredictionPoint.{field_name} deve ser datetime, recebeu "
                    f"{type(value).__name__} — desserialize para datetime antes de "
                    "construir (ex.: datetime.fromisoformat), não passe a string crua")
        # Mesma auditoria: comparar um datetime naive com um aware levanta
        # TypeError cru do Python ("can't compare offset-naive and
        # offset-aware datetimes"), vazando sem contexto de domínio.
        if (self.predicted_at.tzinfo is None) != (self.matures_at.tzinfo is None):
            raise ValueError(
                "PredictionPoint inválido: predicted_at e matures_at misturam "
                "datetime naive e timezone-aware — normalize os dois para o mesmo "
                "regime (preferencialmente UTC-aware) antes de construir")
        if self.matures_at < self.predicted_at:
            raise ValueError(
                f"PredictionPoint inválido: matures_at ({self.matures_at.isoformat()}) "
                f"anterior a predicted_at ({self.predicted_at.isoformat()}) — "
                "previsão do já-observável é lookahead")
        # `frozen=True` só impede REBIND de atributo, não mutação do objeto
        # referenciado (auditoria hostil 2026-07-17: um dict/list passado em
        # metadata/value continuava mutável pós-construção, deixando o
        # invariante "impossível, não prometido" falso na prática). Cópia
        # defensiva de containers mutáveis conhecidos; `value` só é copiado
        # quando é list/dict/set — tipos escalares/imutáveis/objetos de
        # domínio opacos passam direto, sem tentativa de deepcopy arbitrária.
        object.__setattr__(self, "metadata",
                           copy.deepcopy(self.metadata) if self.metadata is not None else None)
        if isinstance(self.value, (list, dict, set)):
            object.__setattr__(self, "value", copy.deepcopy(self.value))

    def is_mature(self, now: datetime) -> bool:
        return now >= self.matures_at

    def __hash__(self) -> int:
        # Auditoria hostil 2026-07-17: o __hash__ auto-gerado por
        # @dataclass(frozen=True) hasheia TODOS os campos, incluindo
        # metadata/value — que podem ser dict/list (não-hasheáveis). Isso
        # tornava a hasheabilidade dependente do CONTEÚDO em runtime (às
        # vezes funciona, às vezes `TypeError: unhashable type`), não da
        # estrutura da classe. Hash baseado só nos dois campos sempre-
        # datetime é sempre hasheável e continua consistente com __eq__
        # (objetos __eq__-iguais têm necessariamente os mesmos dois campos,
        # logo o mesmo hash; colisão de hash entre objetos DIFERENTES é
        # permitida pelo contrato de hash e não é um bug).
        return hash((self.predicted_at, self.matures_at))


class DataProvider(abc.ABC):
    """Contrato que todo conector de mercado concreto implementa.

    Implementações devem ser baratas de instanciar (sem rede no __init__) e fazer toda
    a I/O nos métodos async abaixo."""

    #: Nome curto e estável da fonte (ex.: "binance"). Vai no campo `source` e na telemetria.
    name: str = "abstract"

    @abc.abstractmethod
    async def fetch_ohlcv(self, symbol: str, interval: str = "1d",
                          limit: int = 1) -> list[MarketDataPoint]:
        """Últimos `limit` candles de `symbol` no `interval`. `symbol` é o ID canônico
        do domínio (ex.: "bitcoin"); o conector o traduz para o formato nativo. Deve
        levantar exceção (qualquer) em falha — o Router decide se tenta a próxima fonte."""

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """True se a fonte parece saudável. Usado pelo Circuit Breaker."""


class SignalProvider(abc.ABC):
    """Contrato de uma fonte de sinal de baixa frequência (não-OHLCV)."""

    name: str = "abstract_signal"

    @abc.abstractmethod
    async def fetch(self, limit: int = 30) -> list[SignalPoint]:
        """Últimos `limit` pontos do sinal, com published_at."""
