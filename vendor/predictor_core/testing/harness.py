"""harness — controle positivo: um veredito só é interpretável se o pipeline tem PODER.

Um pipeline de avaliação que devolve NO-GO pode estar certo (não há edge) OU cego (não
detectaria edge nenhum). O controle positivo distingue os dois: injeta um edge sintético
e exige detecção (sensibilidade), depois injeta ruído e exige rejeição (especificidade).
Sem passar nos dois, nenhum GO/NO-GO do pipeline significa coisa alguma.

Integração com o Experiment Registry (2026-07-09): `attest_pipeline_power` roda o
controle positivo E emite um ATESTADO em arquivo — o que `measurement.trials.
register_trial` exige para aceitar uma trial NOVA. Arquivo (não flag em memória)
porque o harness roda na suíte e o registro roda no pipeline: processos distintos.
"""
import json
import hashlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ATTESTATION_SCHEMA_VERSION = "pipeline-power/2"


def pipeline_fingerprint(evaluate_func, edge_generator, noise_generator, *, metric: str) -> str:
    """Fingerprint reprodutível da régua atestada e dos seus controles.

    O registry recebe o mesmo valor ao abrir uma trial; assim um atestado de um
    pipeline anterior não autoriza silenciosamente uma régua modificada. É
    evidência de proveniência, não assinatura criptográfica: a confiança no
    arquivo de atestado permanece no ambiente que o produz.
    """
    def describe(func):
        try:
            source = inspect.getsource(func)
        except (OSError, TypeError):
            source = repr(func)
        return {"module": getattr(func, "__module__", None),
                "qualname": getattr(func, "__qualname__", None), "source": source}

    payload = {"metric": metric, "evaluate": describe(evaluate_func),
               "edge_generator": describe(edge_generator), "noise_generator": describe(noise_generator)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _core_version() -> str:
    return (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").splitlines()[0]


def _atomic_write_json(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


class PipelineHasNoPowerError(AssertionError):
    """O pipeline de avaliação falhou o controle positivo — seus vereditos são
    ininterpretáveis até isto ser corrigido."""


def assert_pipeline_has_power(evaluate_func, edge_generator, noise_generator,
                              *, edge_verdict: str = "COMPROVADA",
                              null_verdict: str = "REFUTADA") -> bool:
    """Valida que `evaluate_func` detecta edge e rejeita ruído.

    evaluate_func(series) -> dict com chave 'verdict'.
    edge_generator()  -> série COM edge (deve produzir `edge_verdict`).
    noise_generator() -> série SEM edge (NÃO pode produzir `edge_verdict`;
                         qualquer outro veredito — `null_verdict`, "INCONCLUSIVO" —
                         conta como rejeição. `null_verdict` é usado só no
                         diagnóstico da mensagem de erro, não como exigência).

    Levanta PipelineHasNoPowerError se: (a) o edge não for detectado — falso negativo,
    o pipeline é cego; ou (b) o ruído for confirmado — falso positivo, o pipeline
    fabrica significância. Retorna True se ambos os braços passarem."""
    v_edge = evaluate_func(edge_generator())
    got_edge = v_edge.get("verdict")
    if got_edge != edge_verdict:
        raise PipelineHasNoPowerError(
            f"SENSIBILIDADE falhou: edge sintético não detectado "
            f"(verdict={got_edge!r}, esperado {edge_verdict!r}) — pipeline cego.")

    v_noise = evaluate_func(noise_generator())
    got_noise = v_noise.get("verdict")
    if got_noise == edge_verdict:
        raise PipelineHasNoPowerError(
            f"ESPECIFICIDADE falhou: ruído confirmado como edge "
            f"(verdict={got_noise!r}, esperado {null_verdict!r} ou qualquer "
            f"não-{edge_verdict!r}) — pipeline fabrica significância.")
    return True


def attest_pipeline_power(evaluate_func, edge_generator, noise_generator,
                          *, attestation_path: Path | str, note: str = "",
                          edge_verdict: str = "COMPROVADA",
                           null_verdict: str = "REFUTADA",
                           metric: str = "",
                           valid_for: timedelta = timedelta(days=7)) -> dict:
    """Roda o controle positivo e, PASSANDO, emite o atestado que destrava a
    criação de trials novas no Experiment Registry (measurement.trials).

    `attestation_path`: onde gravar — use `trials.attestation_path_for(trials_json)`
    para o local canônico (irmão do trials.json). Falhando o controle, levanta
    PipelineHasNoPowerError e NÃO grava nada. Retorna o dict do atestado.

    `metric`: nome da métrica que o pipeline atestado
    usa (ex.: "brier" para binário, "rps" para ordinal). Vai no atestado; o
    registry exige que a trial declare a MESMA métrica e o
    `pipeline_fingerprint` retornado. `valid_for` limita a vida do atestado."""
    if not isinstance(metric, str) or not metric:
        raise ValueError("metric é obrigatória para emitir atestado de poder")
    if valid_for <= timedelta(0):
        raise ValueError("valid_for deve ser positivo")
    assert_pipeline_has_power(evaluate_func, edge_generator, noise_generator,
                               edge_verdict=edge_verdict, null_verdict=null_verdict)
    issued_at = datetime.now(timezone.utc)
    record = {
        "schema_version": _ATTESTATION_SCHEMA_VERSION,
        "passed_at": issued_at.isoformat(timespec="seconds"),
        "expires_at": (issued_at + valid_for).isoformat(timespec="seconds"),
        "core_version": _core_version(),
        "evaluate": getattr(evaluate_func, "__name__", repr(evaluate_func)),
        "edge_verdict": edge_verdict,
        "note": note,
        "metric": metric,
        "pipeline_fingerprint": pipeline_fingerprint(
            evaluate_func, edge_generator, noise_generator, metric=metric),
    }
    ap = Path(attestation_path)
    _atomic_write_json(ap, record)
    return record
