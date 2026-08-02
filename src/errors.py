from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDescriptor:
    code: str
    retryable: bool
    operational_status: str


class LolPredictorError(RuntimeError):
    descriptor = ErrorDescriptor("LOL_FAILED", False, "FAILED")


class ConfigurationError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_CONFIGURATION", False, "CONFIGURATION_ERROR")


class AuthenticationError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_AUTHENTICATION", False, "CONFIGURATION_ERROR")


class AuthorizationError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_AUTHORIZATION", False, "FAILED")


class DataUnavailableError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_DATA_UNAVAILABLE", True, "SOURCE_UNAVAILABLE")


class DataStaleError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_DATA_STALE", True, "SOURCE_UNAVAILABLE")


class DataIntegrityError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_DATA_INTEGRITY", False, "FAILED")


class ProviderRateLimitError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_PROVIDER_RATE_LIMIT", True, "SOURCE_UNAVAILABLE")


class ProviderSchemaError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_PROVIDER_SCHEMA", False, "SOURCE_UNAVAILABLE")


class PredictionError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_PREDICTION", False, "FAILED")


class ScientificGateError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_SCIENTIFIC_GATE", False, "NO_GO")


class PersistenceError(LolPredictorError):
    descriptor = ErrorDescriptor("LOL_PERSISTENCE", True, "FAILED")
