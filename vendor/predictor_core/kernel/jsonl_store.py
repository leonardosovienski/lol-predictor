"""predictor-core.kernel.jsonl_store — armazenamento JSONL iterável (Onda 1 da v1.3.0).

O padrão "um JSON por linha, append-only" já existia em dois lugares do
ecossistema (telemetria do obs, logs de eventos dos consumidores) sem uma
abstração comum. `JsonlStore` é o contrato mínimo: `append(record)` (escrita
atômica por linha, flush imediato), `__iter__` (leitura streaming — nunca
carrega o arquivo inteiro), `count()` e `tail(n)`.

Não é banco: sem índice, sem update, sem delete — coerente com a filosofia do
Ledger (correção é registro novo). Quem precisa de query estruturada usa o
SQLite do consumidor; isto é a camada de EVENTOS."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import MappingProxyType

__all__ = ["JsonlStore"]


def _json_immutable(value: object) -> object:
    """Reduz os containers imutáveis do core a equivalentes JSON nativos.

    `data.contracts._freeze` (2.0.0) congela os campos dos contratos
    recursivamente: dict vira MappingProxyType, list/tuple viram tuple e set
    vira frozenset. O json só conhece tuple (vira array) — os outros dois
    explodiam com `TypeError: Object of type mappingproxy is not JSON
    serializable` ao gravar aqui. Como `PredictionPoint.value` é congelado pelo
    core e `JsonlStore.append` é o gravador do próprio core, as duas APIs
    deixaram de compor: o consumidor faz tudo certo e ainda assim quebra.
    """
    if isinstance(value, MappingProxyType):
        return dict(value)
    if isinstance(value, frozenset):
        try:
            return sorted(value)
        except TypeError:
            # Elementos de tipos não comparáveis entre si (ex.: {1, "a"}).
            # `list(frozenset)` seria ordenado pelo HASH, que varia com o
            # PYTHONHASHSEED: a MESMA entrada geraria linhas diferentes entre
            # execuções. Num ledger de proveniência isso é inaceitável — o
            # arquivo é a memória da governança. `repr` dá uma ordem total
            # estável para qualquer mistura de tipos.
            return sorted(value, key=repr)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class JsonlStore:
    """Arquivo JSONL append-only com leitura streaming.

    A durabilidade é por chamada: `append` serializa antes de abrir, escreve uma
    linha, faz flush e pede fsync. Não é um protocolo de coordenação entre
    processos; escrita concorrente precisa ser serializada pelo consumidor.

    store = JsonlStore("events.jsonl")
    store.append({"kind": "bet", "stake": 10})
    for rec in store: ...
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, record: dict) -> None:
        """Grava `record` como uma linha JSON (compacta, ensure_ascii=False).
        Cria diretórios. `record` precisa ser JSON-serializável — falha ANTES
        de abrir o arquivo (nunca deixa linha truncada para trás)."""
        # allow_nan=False: NaN/inf virariam literais fora do RFC 8259 — a linha
        # seria ilegível para parsers estritos (corrupção explícita > silenciosa).
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False, default=_json_immutable)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def __iter__(self):
        """Itera os registros em ordem de escrita, streaming (linha a linha).
        Arquivo inexistente = iterador vazio. Linha corrompida (JSON inválido)
        levanta ValueError com o número da linha — corrupção silenciosa é pior
        que falha explícita."""
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError as exc:
                    raise ValueError(
                        f"{self.path}:{i}: linha JSONL corrompida — {exc}") from exc

    def count(self) -> int:
        return sum(1 for _ in self)

    def tail(self, n: int) -> list:
        """Últimos `n` registros (lê tudo — para arquivos de telemetria, ok;
        para logs gigantes o consumidor rotaciona antes)."""
        records = list(self)
        return records[-n:] if n > 0 else []
