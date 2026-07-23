"""Fachada pública do contrato arquivístico COLLECTION_ONLY."""
from predictor_core.data.collection import (  # noqa: F401
    COLLECTION_SCHEMA_VERSION, LifecycleState, ObservationEnvelope,
    CollectionArchive, CollectionTransitionError, ScientificPromotionError,
    aggregate_funnel,
)

__all__ = ["COLLECTION_SCHEMA_VERSION", "LifecycleState", "ObservationEnvelope",
           "CollectionArchive", "CollectionTransitionError", "ScientificPromotionError",
           "aggregate_funnel"]
