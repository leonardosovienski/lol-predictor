"""predictor-core.contracts — Camada de Tipagem Pura (fachada canônica, v1.3.0).

O masterplan definitivo separa CONTRATOS (o que atravessa fronteiras) dos
MOTORES (o que calcula). Este pacote é a fachada da camada de contratos:

  contracts.points   — MarketDataPoint, SignalPoint, PredictionPoint
  contracts.registry — TrialRegistry e a governança N+1 / trava de poder

As implementações continuam onde os consumidores já as vendorizam
(`data/contracts.py`, `measurement/trials.py`) — mover o arquivo físico
quebraria os 8 vendors sem ganho; a fachada dá o caminho de import canônico
novo (`from predictor_core.contracts.points import PredictionPoint`) sem
quebrar nenhum caminho antigo. Quando os consumidores migrarem, a implementação
física pode se mudar para cá num MAJOR futuro."""
from predictor_core.contracts.points import (   # noqa: F401
    MarketDataPoint, SignalPoint, PredictionPoint, DataUnavailableError,
)
from predictor_core.contracts.registry import (  # noqa: F401
    TrialRegistry, register_trial, load_trials, validate_trials,
    deflated_sharpe_ratio, attestation_path_for, PowerAttestationMissingError,
    MetricMismatchError,
)
from predictor_core.contracts.collection import (  # noqa: F401
    COLLECTION_SCHEMA_VERSION, LifecycleState, ObservationEnvelope, CollectionArchive,
    CollectionTransitionError, ScientificPromotionError, aggregate_funnel,
)
# Os campos dos contratos são congelados (MappingProxyType/tuple/frozenset) e o
# json não serializa duas dessas três formas. `to_jsonable` é o caminho
# sancionado de volta para quem precisa entregar um campo de contrato ao
# json.dumps FORA do JsonlStore — que resolve o caso internamente, mas só
# para si.
from predictor_core.kernel.jsonable import to_jsonable  # noqa: F401

__all__ = [
    "MarketDataPoint", "SignalPoint", "PredictionPoint", "DataUnavailableError",
    "TrialRegistry", "register_trial", "load_trials", "validate_trials",
    "deflated_sharpe_ratio", "attestation_path_for", "PowerAttestationMissingError",
    "MetricMismatchError",
    "COLLECTION_SCHEMA_VERSION", "LifecycleState", "ObservationEnvelope", "CollectionArchive",
    "CollectionTransitionError", "ScientificPromotionError", "aggregate_funnel",
    "to_jsonable",
]
