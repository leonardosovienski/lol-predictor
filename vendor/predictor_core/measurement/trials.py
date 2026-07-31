"""predictor-core.measurement.trials — Experiment Registry + Deflated Sharpe Ratio.

RECONCILIAÇÃO (2026-07-09): esta é a versão EVOLUÍDA, re-promovida do
previsao-cripto (analyzers/trials.py), que havia divergido da cópia original do
core — o pior tipo de drift: duas réguas de governança na mesma plataforma.
Ganhos sobre a v1: schema formal (`validate_trials`), governança de identidade
N+1 (mudar `params` de trial existente é ERRO, não update silencioso) e a trava
de controle positivo (criar trial NOVA exige atestado do harness — ver abaixo).

Governança contra data-snooping: cada configuração avaliada contra os dados
(ativo, horizonte, prompt, feature, fonte) é uma TENTATIVA. Avaliar N
configurações e reportar a melhor infla o Sharpe esperado por pura sorte —
E[max SR] cresce com N mesmo sem skill. O DSR (Bailey & López de Prado, 2014)
desconta isso: é o PSR calculado contra E[max SR | H0, N] em vez de zero.

O arquivo de tentativas é VERSIONADO de propósito: o desconto só é honesto se o
denominador (quantas tentativas houve) sobreviver ao esquecimento seletivo.

TRAVA DE PODER (harness ↔ registry): um NO-GO só é interpretável se o pipeline
provou que detectaria edge plantado (testing/harness). Criar uma trial NOVA
exige um ATESTADO — arquivo irmão `<trials>.harness_attestation.json`, emitido
por `testing.harness.attest_pipeline_power` — senão o registro está governando
vereditos de um juiz possivelmente cego. Atualizar sharpe/notes de trial
EXISTENTE não exige (a maturação automática de resultados não pode depender do
harness ter rodado na mesma máquina). O atestado é arquivo, não flag em
memória, porque o harness roda na suíte de testes e o registro roda no
pipeline: processos distintos.

Unidades: os `sharpe` registrados e o DSR operam POR-PERÍODO (a mesma unidade
que o PSR observa internamente), NÃO anualizada.

O caminho do arquivo é do DOMÍNIO: passe `path` explicitamente ou use o default
`./trials.json` no diretório de trabalho.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist, variance

from predictor_core.measurement.stats import probabilistic_sharpe_ratio

_EULER = 0.5772156649015329  # γ de Euler–Mascheroni
_DEFAULT_PATH = Path("trials.json")
_ALLOWED_EXTRA = {"features_used", "train_period", "test_period",
                  "status", "rps_dixon", "rps_elo_baseline", "delta_rps_ci95"}
_TRIAL_FIELDS = {"name", "registered_at", "params", "sharpe", "notes", "metric", *_ALLOWED_EXTRA}


class PowerAttestationMissingError(RuntimeError):
    """Tentativa de criar trial NOVA sem atestado de controle positivo.

    Rode `testing.harness.attest_pipeline_power(...)` — que exige que o SEU
    pipeline detecte edge sintético e rejeite ruído — para emitir o atestado
    irmão do trials.json. Sem essa prova, o registro governaria vereditos de
    um juiz que ninguém confirmou não ser cego."""


def attestation_path_for(trials_path: Path | str) -> Path:
    """Caminho canônico do atestado: irmão do trials.json."""
    p = Path(trials_path)
    return p.with_name(p.stem + ".harness_attestation.json")


def _load_attestation(att: Path) -> dict | None:
    """Lê um atestado legível; a validação de campos cabe ao registry."""
    if not att.exists():
        return None
    try:
        parsed = json.loads(att.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ---------- registro ----------

def load_trials(path: Path | str | None = None) -> list[dict]:
    p = Path(path or _DEFAULT_PATH)
    if not p.exists():
        return []
    try:
        parsed = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # Auditoria hostil 2026-07-17: antes propagava JSONDecodeError cru,
        # sem caminho — inconsistente com kernel/obs.py e kernel/jsonl_store.py,
        # que sempre incluem o arquivo na mensagem desde df575a9.
        raise ValueError(f"{p}: trials.json corrompido — {exc}") from exc
    if not isinstance(parsed, list):
        # JSON válido (ex.: `null`) mas não é a lista esperada — sem esta
        # checagem, validate_trials(None) explodia com TypeError opaco,
        # sem relação nenhuma com a causa real (arquivo com conteúdo errado).
        raise ValueError(f"{p}: trials.json deve conter uma lista de tentativas "
                         f"— encontrado {type(parsed).__name__}")
    return parsed


def _pid_alive(pid: int) -> bool:
    """Best-effort: existe processo com este PID? Falha de leitura = "não sei",
    trata como vivo (nunca reclama antecipadamente por incerteza). Mesmo
    padrão de tools/operational_runner.py — duplicado aqui deliberadamente:
    predictor_core não deve depender de tools/ (camada operacional), mesmo
    para uma checagem pequena e estável como esta."""
    if pid <= 0:
        return True
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _lock_owner_pid_dead(lock_path: Path) -> bool:
    """True somente quando o conteúdo do lock é legível, tem um pid, e esse
    pid está comprovadamente morto. Qualquer outra situação (ilegível, sem
    pid, vivo) é False — a política de idade abaixo continua sendo o
    fallback, nunca substituída."""
    try:
        content = json.loads(lock_path.read_text(encoding="ascii"))
        pid = content.get("pid")
    except (OSError, ValueError, AttributeError):
        return False
    if not isinstance(pid, int):
        return False
    return not _pid_alive(pid)


def _acquire_trials_lock(p: Path, *, timeout: float = 60.0, poll: float = 0.05) -> Path:
    """Lock de arquivo (O_CREAT|O_EXCL) em torno da seção crítica read-modify-
    write de register_trial. Sem isto, dois processos podiam ler o mesmo
    estado, cada um calcular sua própria trial nova, e a segunda escrita
    sobrescrevia a primeira EM SILÊNCIO — reproduzido na auditoria hostil
    2026-07-17: uma trial registrada desaparecia do arquivo final sem erro
    nem aviso algum, justamente o "esquecimento seletivo" que a governança
    N+1 do módulo existe para impedir. Advisory only (protege register_trial
    contra si mesmo em processos concorrentes, não contra edição manual do
    arquivo). Um lock cujo PID esteja comprovadamente vivo NUNCA é roubado: o
    timeout limita somente a espera do concorrente. Locks sem dono legível
    podem ser recuperados por idade como fallback conservador.

    Auditoria hostil 2026-07-17 (rodada predictor_core): a versão original só
    reclamava por IDADE (timeout default de 10s) — curto demais para dados
    científicos: um escritor legítimo mas lento (I/O de disco, pausa de GC)
    podia ter o lock "roubado" por outro processo, reabrindo exatamente a
    corrida que este lock existe para impedir. Agora o conteúdo do lock grava
    o PID do dono, e um PID comprovadamente morto é reclamado IMEDIATAMENTE.
    Um PID vivo prevalece sobre a idade; isso impede que I/O lento reabra a
    corrida que o lock existe para evitar."""
    lock_path = p.with_suffix(p.suffix + ".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, json.dumps({"pid": os.getpid()}, sort_keys=True).encode("ascii"))
            os.close(fd)
            return lock_path
        except FileExistsError:
            if _lock_owner_pid_dead(lock_path):
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            # Se o lock declara um PID vivo (ou não conseguimos provar que está
            # morto), não o removemos por idade. `timeout` só decide quando o
            # concorrente desiste de esperar, nunca autoriza dois escritores.
            try:
                content = json.loads(lock_path.read_text(encoding="ascii"))
                owner_is_live = isinstance(content.get("pid"), int) and _pid_alive(content["pid"])
            except (OSError, ValueError, AttributeError):
                owner_is_live = False
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                continue  # lock sumiu entre o open e o stat: tenta de novo
            if not owner_is_live and age > timeout:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"não foi possível obter o lock de {p} (concorrendo com "
                    f"outro processo) em {timeout}s")
            time.sleep(poll)


def _release_trials_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _find_non_finite_float(obj: object, path: str = "") -> str | None:
    """Percorre dict/list recursivamente; retorna o caminho (estilo `[.foo][2]`)
    do primeiro float NaN/Infinity encontrado, ou None se tudo for finito."""
    if isinstance(obj, float) and not isinstance(obj, bool) and not math.isfinite(obj):
        return path
    if isinstance(obj, dict):
        for key, value in obj.items():
            found = _find_non_finite_float(value, f"{path}[{key!r}]")
            if found is not None:
                return found
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            found = _find_non_finite_float(value, f"{path}[{i}]")
            if found is not None:
                return found
    return None


def validate_trials(trials: list[dict]) -> list[str]:
    """Schema formal do registro. Retorna a lista de violações (vazia = conforme).
    A suíte do consumidor deve falhar se o trials.json real não conformar — o
    registro só protege o DSR se todo campo do denominador for interpretável.

    Obrigatórios: name (str não-vazio, sem espaços — identidade), registered_at
    (ISO-8601 UTC 'Z'), params (dict NÃO-vazio — a configuração exata), sharpe
    (None ou número finito, unidade por-período), notes (str).
    Opcionais tipados: features_used (list[str]), train_period/test_period
    ([início, fim] ISO-8601).
    """
    errs: list[str] = []
    seen: set[str] = set()
    for i, t in enumerate(trials):
        tag = f"trial[{i}]"
        if not isinstance(t, dict):
            errs.append(f"{tag}: trial deve ser objeto JSON, encontrado {type(t).__name__}")
            continue
        unknown = set(t) - _TRIAL_FIELDS
        if unknown:
            errs.append(f"{tag}: campos desconhecidos: {sorted(unknown)}")
        name = t.get("name")
        if not isinstance(name, str) or not name or " " in name:
            errs.append(f"{tag}: name inválido ({name!r}) — str não-vazia sem espaços")
        elif name in seen:
            errs.append(f"{tag}: name duplicado ({name!r}) — identidade precisa ser única")
        else:
            seen.add(name)
            tag = f"trial[{name}]"
        ra = t.get("registered_at", "")
        try:
            datetime.strptime(ra, "%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            errs.append(f"{tag}: registered_at inválido ({ra!r}) — use ISO-8601 UTC 'Z'")
        params = t.get("params")
        if not isinstance(params, dict) or not params:
            errs.append(f"{tag}: params precisa ser dict NÃO-vazio (a configuração exata "
                        "é o que permite ao DSR distinguir tentativas)")
        elif (bad_path := _find_non_finite_float(params)) is not None:
            # Auditoria hostil 2026-07-17: sharpe já era validado com
            # math.isfinite, mas um float NaN/Infinity dentro de params
            # passava direto — json.dumps do Python grava esses valores como
            # os literais não-padrão `NaN`/`Infinity` (fora da RFC 8259), que
            # um parser JSON estrito (outra linguagem, jq, validador externo)
            # rejeita. O arquivo continuava relendo bem NO PRÓPRIO Python,
            # então o problema só aparecia ao integrar com qualquer
            # ferramenta que valide JSON de verdade.
            errs.append(f"{tag}: params{bad_path} é NaN/Infinity — não serializável "
                        "em JSON portável (RFC 8259)")
        sharpe = t.get("sharpe")
        if sharpe is not None and (isinstance(sharpe, bool)
                                   or not (isinstance(sharpe, (int, float))
                                           and math.isfinite(sharpe))):
            errs.append(f"{tag}: sharpe inválido ({sharpe!r}) — None ou número finito")
        if not isinstance(t.get("notes", ""), str):
            errs.append(f"{tag}: notes precisa ser str")
        metric = t.get("metric")
        if metric is not None and not (isinstance(metric, str) and metric):
            errs.append(f"{tag}: metric inválida ({metric!r}) — str não-vazia quando presente")
        for key in ("train_period", "test_period"):
            per = t.get(key)
            if per is not None and not (isinstance(per, list) and len(per) == 2
                                        and all(isinstance(x, str) for x in per)):
                errs.append(f"{tag}: {key} inválido — [início, fim] ISO-8601")
        fu = t.get("features_used")
        if fu is not None and not (isinstance(fu, list)
                                   and all(isinstance(x, str) for x in fu)):
            errs.append(f"{tag}: features_used inválido — list[str]")
    return errs


class MetricMismatchError(PowerAttestationMissingError):
    """A trial declara uma métrica diferente da atestada pelo harness — o
    controle positivo que passou não cobre o veredito que será emitido
    (ex.: harness atestado com Brier, trial avaliada por RPS)."""


def register_trial(name: str, *, params: dict, sharpe: float | None = None,
                   notes: str = "", path: Path | str | None = None,
                   now: str | None = None,
                   power_attestation: Path | str | bool | None = None,
                    metric: str | None = None,
                    pipeline_fingerprint: str | None = None,
                   **extra) -> list[dict]:
    """Registra (ou atualiza) uma tentativa. `name` é a identidade da CONFIGURAÇÃO.

    Governança de identidade: reexecutar a MESMA configuração atualiza a entrada
    (sharpe/notes, preservando o registered_at original); tentar "atualizar" uma
    trial existente com `params` DIFERENTES é ValueError — variação de
    configuração é tentativa NOVA (N+1), e escondê-la num update fabricaria
    significância que o DSR não desconta.

    Trava de poder: criar trial NOVA exige o atestado do harness (arquivo irmão;
    ver docstring do módulo). `power_attestation`: None = procura o irmão;
    caminho = usa esse arquivo; False = bypass EXPLÍCITO (só para teste de
    mecânica do registro — nunca em pesquisa real).

    Punição global: para trial NOVA protegida, `metric` e
    `pipeline_fingerprint` são obrigatórios e devem casar com o atestado ainda
    válido e emitido pela mesma versão do core.

    `now` injetável para teste determinístico. `extra` aceita os campos
    opcionais do schema (features_used, train_period, test_period). Valida o
    schema ANTES de gravar. Retorna a lista completa após a escrita.

    Concorrência (auditoria hostil 2026-07-17): a seção read-modify-write
    inteira roda sob um lock de arquivo (`_acquire_trials_lock`) — sem ele,
    dois processos podiam ler o mesmo estado e a segunda escrita apagava
    silenciosamente a tentativa que a primeira tinha acabado de registrar."""
    p = Path(path or _DEFAULT_PATH)
    lock_path = _acquire_trials_lock(p)
    try:
        return _register_trial_locked(name, params=params, sharpe=sharpe, notes=notes,
                                       path=p, now=now, power_attestation=power_attestation,
                                       metric=metric, pipeline_fingerprint=pipeline_fingerprint,
                                       **extra)
    finally:
        _release_trials_lock(lock_path)


def _register_trial_locked(name: str, *, params: dict, sharpe: float | None,
                            notes: str, path: Path, now: str | None,
                            power_attestation: Path | str | bool | None,
                            metric: str | None, pipeline_fingerprint: str | None,
                            **extra) -> list[dict]:
    """Corpo de register_trial que roda DENTRO do lock — não chamar direto."""
    p = path
    bad_extra = set(extra) - _ALLOWED_EXTRA
    if bad_extra:
        raise ValueError(f"trial '{name}': campos extras não permitidos: {sorted(bad_extra)}")
    trials = load_trials(p)
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {"name": name, "registered_at": stamp, "params": params,
             "sharpe": sharpe, "notes": notes, **extra}
    if metric is not None:
        entry["metric"] = metric
    for i, t in enumerate(trials):
        if t.get("name") == name:
            if t.get("params") != params:
                raise ValueError(
                    f"trial '{name}' já existe com params DIFERENTES — variação de "
                    "configuração é tentativa nova: registre com um name novo (N+1). "
                    f"registrado={t.get('params')!r} vs proposto={params!r}")
            # A métrica é a RÉGUA do veredito — trocá-la num update é mudança de
            # tentativa tanto quanto mudar params (mesma governança N+1). Update
            # sem `metric` preserva a registrada (não a apaga em silêncio).
            registrada = t.get("metric")
            if metric is None:
                if registrada is not None:
                    entry["metric"] = registrada
            elif registrada is not None and metric != registrada:
                raise ValueError(
                    f"trial '{name}' já existe com metric={registrada!r} — avaliar a "
                    f"mesma configuração com outra régua ({metric!r}) é tentativa "
                    "nova: registre com um name novo (N+1).")
            entry["registered_at"] = t.get("registered_at", stamp)
            trials[i] = entry
            break
    else:
        if power_attestation is not False:
            att = Path(power_attestation) if power_attestation else attestation_path_for(p)
            attestation = _load_attestation(att)
            required = {"schema_version", "passed_at", "expires_at", "core_version",
                        "metric", "pipeline_fingerprint"}
            if not attestation or not required <= attestation.keys():
                raise PowerAttestationMissingError(
                    f"trial nova '{name}' sem atestado de controle positivo válido "
                    f"({att}) — rode testing.harness.attest_pipeline_power antes de registrar.")
            try:
                expires_at = datetime.fromisoformat(attestation["expires_at"].replace("Z", "+00:00"))
            except (TypeError, ValueError):
                raise PowerAttestationMissingError(f"atestado inválido ({att}): expires_at ausente ou inválido")
            if expires_at.tzinfo is None:
                raise PowerAttestationMissingError(f"atestado inválido ({att}): expires_at deve ter timezone")
            if expires_at <= datetime.now(timezone.utc):
                raise PowerAttestationMissingError(f"atestado expirado ({att}); reate o pipeline")
            current_core_version = (Path(__file__).resolve().parents[1] / "VERSION").read_text(
                encoding="utf-8").splitlines()[0]
            if attestation["core_version"] != current_core_version:
                raise PowerAttestationMissingError(
                    f"atestado ({att}) foi emitido para core {attestation['core_version']!r}, "
                    f"mas o core atual é {current_core_version!r}; reate o pipeline")
            if not isinstance(metric, str) or not metric:
                raise MetricMismatchError(f"trial nova '{name}' deve declarar metric para casar com o atestado")
            if attestation["metric"] != metric:
                raise MetricMismatchError(
                    f"trial nova '{name}' declara metric={metric!r} mas o atestado ({att}) "
                    f"foi emitido com metric={attestation['metric']!r}")
            if not isinstance(pipeline_fingerprint, str) or not pipeline_fingerprint:
                raise PowerAttestationMissingError(
                    f"trial nova '{name}' deve declarar pipeline_fingerprint do harness atestado")
            if attestation["pipeline_fingerprint"] != pipeline_fingerprint:
                raise PowerAttestationMissingError(
                    f"trial nova '{name}' usa pipeline_fingerprint diferente do atestado ({att})")
        trials.append(entry)
    errs = validate_trials(trials)
    if errs:
        # Auditoria hostil 2026-07-17: quando o arquivo já tinha uma entrada
        # LEGADA malformada (edição manual, schema antigo), validate_trials
        # roda sobre a lista inteira e bloqueia até o registro de uma trial
        # nova perfeitamente válida — sem deixar claro que a causa é OUTRA
        # entrada, não a que se está tentando registrar agora.
        own_tag_failed = any(e.startswith(f"trial[{name}]:") for e in errs)
        prefix = ("registro violaria o schema de trials — a trial que você está "
                 f"registrando ('{name}') está OK; o problema é em outra entrada já "
                 "presente no arquivo: " if not own_tag_failed else
                 "registro violaria o schema de trials: ")
        raise ValueError(prefix + "; ".join(errs))
    # Escrita atômica (tmp + replace): crash no meio do write não pode corromper
    # o registro inteiro — o denominador do DSR é a memória da governança.
    try:
        serialized = json.dumps(trials, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    except TypeError as exc:
        # Auditoria hostil 2026-07-17: um valor não-serializável em params
        # (datetime, instância de classe custom) vazava como TypeError cru
        # do json, sem apontar o name da trial nem o caminho do arquivo —
        # opaco para depurar em produção, inconsistente com o resto do
        # módulo (load_trials sempre inclui o caminho desde df575a9).
        raise ValueError(
            f"trial '{name}': params/metadata contém um valor não serializável em "
            f"JSON ({exc}) — use apenas tipos JSON nativos (str/int/float/bool/None/"
            f"list/dict) em params") from exc
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(serialized, encoding="utf-8")
    tmp.replace(p)
    return trials


# ---------- Deflated Sharpe Ratio ----------

def expected_max_sharpe(n_trials: int, var_trials_sr: float) -> float:
    """E[max SR] sob H0 (nenhuma tentativa tem skill) para N tentativas.

    Aproximação de máximo de gaussianas (López de Prado 2014):
    sqrt(V[SR]) * ((1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e))). Com 1 tentativa ou
    variância nula entre tentativas, não há seleção → benchmark 0."""
    if n_trials <= 1 or var_trials_sr <= 0:
        return 0.0
    nd = NormalDist()
    z1 = nd.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = nd.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_trials_sr) * ((1.0 - _EULER) * z1 + _EULER * z2)


def deflated_sharpe_ratio(returns: list, trial_sharpes: list) -> dict:
    """DSR = PSR(returns, SR0), SR0 = E[max SR] dado o nº de tentativas registradas.

    `trial_sharpes`: SRs por-período das tentativas (None/±inf são tolerados —
    contam no N, ficam fora da variância). Retorna {dsr, sr0, n_trials}; dsr é
    P(SR verdadeiro > máximo esperado por sorte)."""
    n = len(trial_sharpes)
    finite = [s for s in trial_sharpes if s is not None and math.isfinite(s)]
    var = variance(finite) if len(finite) >= 2 else 0.0
    sr0 = expected_max_sharpe(n, var)
    return {"dsr": probabilistic_sharpe_ratio(returns, benchmark_sharpe=sr0),
            "sr0": sr0, "n_trials": n}


# ---------- fachada orientada a objeto (interface do core) ----------

class TrialRegistry:
    """Fachada fina sobre o arquivo de tentativas — a interface pública do contrato.

    registry = TrialRegistry("trials.json")
    registry.register("v3-fr90", params={...}, sharpe=-0.002)
    registry.validate()                           # [] = schema conforme
    verdict = registry.deflated_sharpe(returns)   # desconta por todas as tentativas
    """
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or _DEFAULT_PATH)

    def register(self, name: str, *, params: dict, sharpe: float | None = None,
                 notes: str = "", now: str | None = None,
                 power_attestation: Path | str | bool | None = None,
                 metric: str | None = None,
                 pipeline_fingerprint: str | None = None,
                 **extra) -> list[dict]:
        return register_trial(name, params=params, sharpe=sharpe, notes=notes,
                               path=self.path, now=now,
                               power_attestation=power_attestation,
                               metric=metric, pipeline_fingerprint=pipeline_fingerprint,
                               **extra)

    def load(self) -> list[dict]:
        return load_trials(self.path)

    def validate(self) -> list[str]:
        return validate_trials(self.load())

    def sharpes(self) -> list:
        return [t.get("sharpe") for t in self.load()]

    def deflated_sharpe(self, returns: list) -> dict:
        """DSR de `returns` descontado por TODAS as tentativas registradas no arquivo."""
        return deflated_sharpe_ratio(returns, self.sharpes())
