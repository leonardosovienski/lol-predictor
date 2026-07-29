"""Modelo Elo de LoL — Fase 0 (esqueleto).

LoL é um MOBA com draft, matchups e objetivos, mas a força relativa das
equipes é o preditor mais robusto para começar:

    P(A vence um MAPA) = 1 / (1 + 10^((elo_B − elo_A)/400))

Rating por MAPA; série (BO1/BO3/BO5) pela combinatória exata com mapas
i.i.d. — simplificação declarada da Fase 0 (draft, early game e patch são
extensões da Fase 1+). K por formato: BO1=32, BO3=40, BO5=48.

Totais de abates: H2 por time foi refutada. O caminho legado usa somente o
baseline agregado declarado no config e nunca consome stats por time.
"""
import json
import math
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from statistics import NormalDist

from .config import ROOT, load_config, load_teams, resolve_team

K_FACTORS = {"bo1": 32, "bo3": 40, "bo5": 48}
# duração típica de parede de relógio por formato (matures_at do serving)
FORMAT_HOURS = {"bo1": 1.0, "bo3": 2.5, "bo5": 4.0}
_RATINGS_LOCK = threading.Lock()


def _kills_calibration(league: str | None) -> tuple[float, float, str | None, str]:
    """Load the H2-approved league baseline without using team statistics."""
    cfg = load_config()
    path = ROOT / cfg.get("calibration_file", "data/calibration.json")
    if not path.exists():
        model = cfg["model"]
        return (float(model["league_avg_total_kills"]),
                float(model["kills_std"]), None, "legacy-global-baseline")
    try:
        calibrations = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"kills calibration unreadable: {path}") from exc
    if not isinstance(calibrations, dict) or not league:
        raise ValueError("--kills-league is required with league calibration")
    entry = calibrations.get(league)
    if not isinstance(entry, dict):
        raise ValueError(f"league has no published calibration: {league!r}")
    try:
        total, std = float(entry["media_total_kills"]), float(entry["sigma"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid calibration for league {league!r}") from exc
    if not math.isfinite(total) or not math.isfinite(std) or total <= 0 or std <= 0:
        raise ValueError(f"non-finite/invalid calibration for league {league!r}")
    return total, std, league, "league-baseline-fase1"


@contextmanager
def _file_lock(path: Path):
    """Serializa writers locais também entre processos (Windows/POSIX)."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock:
        lock.seek(0)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _atomic_json_write(path: Path, payload: dict[str, float]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2,
                         allow_nan=False) + "\n"
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                   dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def win_probability(elo_a: float, elo_b: float) -> float:
    """P(A vence um mapa) — logística clássica do Elo."""
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def series_probs(p: float, fmt: str) -> dict:
    """Distribuição exata do placar da série dado p = P(A vence um mapa)."""
    q = 1.0 - p
    if fmt == "bo1":
        return {"1-0": p, "0-1": q}
    if fmt == "bo3":
        return {"2-0": p * p, "2-1": 2 * p * p * q,
                "1-2": 2 * q * q * p, "0-2": q * q}
    if fmt == "bo5":
        return {"3-0": p ** 3, "3-1": 3 * p ** 3 * q,
                "3-2": 6 * p ** 3 * q * q,
                "2-3": 6 * q ** 3 * p * p, "1-3": 3 * q ** 3 * p,
                "0-3": q ** 3}
    raise ValueError(f"formato desconhecido: {fmt!r} (use bo1/bo3/bo5)")


class EloModel:
    """Ratings Elo dos times Tier 1 (semente = bandas por liga do GPR).

    `ratings_file` (data/ratings.json), quando existir, sobrepõe as sementes —
    é onde update_ratings persiste a evolução após partidas reais."""

    def __init__(self, ratings_file: Path | str | None = None):
        cfg = load_config()
        teams = load_teams()
        self.ratings = {t["name"]: float(t["initial_elo"]) for t in teams}
        seeded_names = {t["name"].casefold(): t["name"] for t in teams}
        self.path = Path(ratings_file) if ratings_file else (
            ROOT / cfg.get("ratings_file", "data/ratings.json"))
        # só nomes vividos (ou atualizados nesta sessão) voltam pro disco;
        # sementes nunca jogadas não contaminam o snapshot de identidades
        self._persistable: set[str] = set()
        if self.path.exists():
            lived = json.loads(self.path.read_text(encoding="utf-8"))
            for name, value in lived.items():
                canonical = seeded_names.get(name.casefold(), name)
                rating = float(value)
                if not math.isfinite(rating):
                    raise ValueError(
                        f"rating não finito para {name!r} em {self.path}: "
                        f"{value!r}")
                self.ratings[canonical] = rating
                self._persistable.add(canonical)
        # Platt H3 foi refutada: serving canônico permanece Elo cru.
        self.platt = None

    def _elo(self, name: str) -> tuple[str, float]:
        try:
            official = resolve_team(name)["name"]
        except ValueError:
            matches = [rated for rated in self.ratings
                       if rated.strip().casefold() == name.strip().casefold()]
            if len(matches) != 1:
                raise
            official = matches[0]
        if official not in self.ratings:
            # resolve_team enxerga o ratings.json default; com ratings_file
            # customizado o nome pode não existir AQUI — erro de contrato,
            # nunca KeyError cru
            raise ValueError(
                f"time {official!r} sem rating em {self.path}")
        return official, self.ratings[official]

    def predict_match(self, team_a: str, team_b: str, format: str = "bo3") -> dict:
        fmt = format.lower()
        if fmt not in K_FACTORS:
            raise ValueError(f"formato desconhecido: {format!r} (use bo1/bo3/bo5)")
        a, elo_a = self._elo(team_a)
        b, elo_b = self._elo(team_b)
        if a == b:
            raise ValueError("um time não joga contra si mesmo")
        p_map_raw = win_probability(elo_a, elo_b)
        # Platt calibra a prob de MAPA (a unidade medida no prequential);
        # a combinatória de série herda a prob calibrada
        p_map = self.platt.apply(p_map_raw) if self.platt else p_map_raw
        dist = series_probs(p_map, fmt)
        prob_a = sum(pr for placar, pr in dist.items()
                     if int(placar.split("-")[0]) > int(placar.split("-")[1]))
        mapas = sum((int(s.split("-")[0]) + int(s.split("-")[1])) * pr
                    for s, pr in dist.items())
        return {"team_a": a, "team_b": b, "format": fmt,
                "elo_a": round(elo_a, 1), "elo_b": round(elo_b, 1),
                "p_map_a": round(p_map, 4),
                "p_map_a_raw": round(p_map_raw, 4),
                "prob_team_a": round(prob_a, 4),
                "prob_team_b": round(1.0 - prob_a, 4),
                # zebra explícita: o lado de menor probabilidade (aposta de valor
                # em odds infladas é hipótese da Fase 1, aqui é só leitura)
                "prob_underdog": round(min(prob_a, 1.0 - prob_a), 4),
                "underdog": b if prob_a >= 0.5 else a,
                "mapas_esperados": round(mapas, 2),
                "score_probs": {s: round(pr, 4) for s, pr in dist.items()},
                "model": "elo-platt-fase1" if self.platt else "elo-fase0"}

    def predict_kills_total(self, team_a: str, team_b: str,
                            line: float | None = None,
                            *, league: str | None = None) -> dict:
        """Total de abates de UM MAPA ≈ Normal(kpg_a + kpg_b, kills_std).

        Cada time contribui metade do baseline agregado. Stats por time são
        deliberadamente ignoradas porque H2 foi refutada."""
        cfg = load_config()
        line = float(cfg["default_kills_line"]) if line is None else float(line)
        total, std, resolved_league, model_name = _kills_calibration(league)
        half = total / 2.0
        a = resolve_team(team_a)["name"]
        b = resolve_team(team_b)["name"]
        kpg_a = kpg_b = half
        total = kpg_a + kpg_b
        p_over = 1.0 - NormalDist(mu=total, sigma=std).cdf(line)
        return {"team_a": a, "team_b": b, "line": line,
                "total_projetado": round(total, 1),
                "kpg_a": round(kpg_a, 1), "kpg_b": round(kpg_b, 1),
                "over_prob": round(p_over, 4),
                "under_prob": round(1.0 - p_over, 4),
                "kills_std": std, "league": resolved_league,
                "model": model_name}

    def update_ratings(self, team_a: str, team_b: str,
                       result_a: int, result_b: int,
                       format: str | None = None) -> dict:
        """Atualiza o Elo após partida real. `format` explícito quando
        conhecido (um 3-0 pode ser BO5); sem ele, K é inferido do placar
        (soma ≤1 → BO1; ≤3 → BO3; senão BO5). Persiste em ratings_file
        apenas ratings vividos/atualizados — nunca sementes intactas."""
        for label, res in (("result_a", result_a), ("result_b", result_b)):
            if not isinstance(res, int) or isinstance(res, bool) or res < 0:
                raise ValueError(
                    f"{label} deve ser inteiro >= 0, veio {res!r}")
        if result_a == result_b:
            raise ValueError(
                f"placar {result_a}-{result_b} sem vencedor — série de LoL "
                "não termina empatada")
        a, elo_a = self._elo(team_a)
        b, elo_b = self._elo(team_b)
        if a == b:
            raise ValueError("um time não joga contra si mesmo")
        if format is not None:
            fmt = format.lower()
            if fmt not in K_FACTORS:
                raise ValueError(
                    f"formato desconhecido: {format!r} (use bo1/bo3/bo5)")
            wins = max(result_a, result_b)
            required_wins = {"bo1": 1, "bo3": 2, "bo5": 3}[fmt]
            if wins != required_wins or min(result_a, result_b) >= required_wins:
                raise ValueError(
                    f"placar {result_a}-{result_b} incompatível com {fmt}")
        else:
            total = result_a + result_b
            fmt = "bo1" if total <= 1 else ("bo3" if total <= 3 else "bo5")
        k = K_FACTORS[fmt]
        s_a = 1.0 if result_a > result_b else 0.0
        e_a = win_probability(elo_a, elo_b)
        delta = k * (s_a - e_a)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _RATINGS_LOCK, _file_lock(self.path):
            # Outra instância pode ter atualizado o snapshot desde __init__.
            # Rebaseia somente os participantes sobre o estado mais recente.
            if self.path.exists():
                latest = json.loads(self.path.read_text(encoding="utf-8"))
                for name, value in latest.items():
                    rating = float(value)
                    if not math.isfinite(rating):
                        raise ValueError(f"rating não finito para {name!r}")
                    self.ratings[name] = rating
                    self._persistable.add(name)
                elo_a, elo_b = self.ratings[a], self.ratings[b]
                e_a = win_probability(elo_a, elo_b)
                delta = k * (s_a - e_a)
            self.ratings[a] = elo_a + delta
            self.ratings[b] = elo_b - delta
            self._persistable.update((a, b))
            persisted = {n: self.ratings[n] for n in sorted(self._persistable)}
            _atomic_json_write(self.path, persisted)
        return {"team_a": a, "team_b": b, "format": fmt, "k": k,
                "delta": round(delta, 2),
                "elo_a": round(self.ratings[a], 1),
                "elo_b": round(self.ratings[b], 1)}
