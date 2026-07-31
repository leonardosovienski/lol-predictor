"""predictor-core.kernel.jsonable — desfaz o congelamento dos contratos para JSON.

`data/contracts.py::_freeze` (2.0.0) congela os campos dos contratos
recursivamente para que ninguém os mute depois de atravessarem a fronteira:
dict vira `MappingProxyType`, list/tuple viram tuple, set vira `frozenset`.
Dessas três formas o `json` só conhece `tuple` (vira array); as outras duas
estouram `TypeError: Object of type mappingproxy is not JSON serializable`.

Este módulo é o caminho ÚNICO de volta. Existe para que o core não tenha duas
implementações da mesma conversão — foi exatamente esse tipo de divergência
(sync_core gravando o agregado completo enquanto os testes e o vendor_byte_audit
recomputavam truncado) que produziu o drift silencioso desta plataforma.

Vive em `kernel/` e não em `data/` por causa da direção de import: `data`
importa de `kernel`, nunca o contrário. `kernel/jsonl_store.py` consome daqui e
`contracts` reexporta `to_jsonable` como API pública.
"""
from __future__ import annotations

from types import MappingProxyType

__all__ = ["to_jsonable", "stable_sorted"]


def stable_sorted(values) -> list:
    """Ordem total ESTÁVEL para um conjunto, inclusive heterogêneo.

    `list(frozenset)` segue a ordem de iteração do set, que vem do hash e varia
    com o `PYTHONHASHSEED`: a MESMA entrada geraria saídas diferentes entre
    execuções. Num ledger de proveniência isso é inaceitável — o arquivo é a
    memória da governança. `sorted` normal resolve o caso homogêneo; para tipos
    não comparáveis entre si (ex.: `{1, "a"}`) o desempate é por `repr`.
    """
    try:
        return sorted(values)
    except TypeError:
        return sorted(values, key=repr)


def to_jsonable(value: object) -> object:
    """Converte recursivamente um valor congelado em tipos JSON nativos.

    Inverso de `data.contracts._freeze`: `MappingProxyType` vira dict,
    `frozenset`/`set` viram lista ordenada de forma estável, tuple vira list.
    Qualquer outro valor passa intacto — a função NÃO tenta serializar tipos
    que o json não conhece; isso continua sendo erro explícito na hora de gravar.

    Use isto quando precisar entregar um campo de contrato a `json.dumps`
    fora do `JsonlStore`:

        json.dumps(to_jsonable(point.value), sort_keys=True)
    """
    if isinstance(value, (MappingProxyType, dict)):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (frozenset, set)):
        return [to_jsonable(item) for item in stable_sorted(value)]
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value
