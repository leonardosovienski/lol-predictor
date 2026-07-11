"""Calibração de probabilidades — Platt scaling (Fase 1, tentativa N+1).

Motivação (relatório da Fase 1): o Elo /400 é SOBRECONFIANTE nas pontas no
CS (previsto 0,93 → real 0,88; previsto 0,07 → real 0,19). O Platt reescala
sem tocar no rating subjacente:

    q = sigmoid(a·logit(p) + b)

a<1 achata (corrige sobreconfiança), a>1 afia, b desloca. Ajuste por
Newton-Raphson na log-verossimilhança (2 parâmetros, fechado em ~25
iterações) — stdlib puro, sem sklearn.

Uso prequential (backtest_calibracao.py): o calibrador só enxerga pares
(p, y) PASSADOS. Uso no serving: parâmetros materializados em
data/calibration_platt.json (ajustados no histórico completo) — model.py
aplica quando o arquivo existe.
"""
import json
import math
from pathlib import Path

_EPS = 1e-6


def _logit(p: float) -> float:
    p = min(max(p, _EPS), 1.0 - _EPS)
    return math.log(p / (1.0 - p))


def _sigmoid(z: float) -> float:
    if z >= 0:
        e = math.exp(-z)
        return 1.0 / (1.0 + e)
    e = math.exp(z)
    return e / (1.0 + e)


class PlattCalibrator:
    """q = sigmoid(a·logit(p) + b). Identidade até o fit (a=1, b=0)."""

    def __init__(self, a: float = 1.0, b: float = 0.0):
        self.a = float(a)
        self.b = float(b)

    def fit(self, probs: list[float], outcomes: list[int],
            iters: int = 25) -> "PlattCalibrator":
        """Newton-Raphson na NLL. outcomes: 1 = evento aconteceu."""
        if len(probs) != len(outcomes) or len(probs) < 10:
            raise ValueError("amostra insuficiente/inconsistente para o Platt")
        zs = [_logit(p) for p in probs]
        a, b = self.a, self.b
        for _ in range(iters):
            g_a = g_b = h_aa = h_ab = h_bb = 0.0
            for z, y in zip(zs, outcomes):
                q = _sigmoid(a * z + b)
                d = q - y
                w = max(q * (1.0 - q), 1e-9)
                g_a += d * z
                g_b += d
                h_aa += w * z * z
                h_ab += w * z
                h_bb += w
            det = h_aa * h_bb - h_ab * h_ab
            if abs(det) < 1e-12:
                break
            da = (g_a * h_bb - g_b * h_ab) / det
            db = (g_b * h_aa - g_a * h_ab) / det
            a -= da
            b -= db
            if abs(da) < 1e-9 and abs(db) < 1e-9:
                break
        self.a, self.b = a, b
        return self

    def apply(self, p: float) -> float:
        return _sigmoid(self.a * _logit(p) + self.b)

    # ---- persistência (serving) ----
    def save(self, path: Path | str, meta: dict | None = None) -> None:
        out = {"a": round(self.a, 6), "b": round(self.b, 6), **(meta or {})}
        Path(path).write_text(json.dumps(out, ensure_ascii=False, indent=2)
                              + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "PlattCalibrator | None":
        p = Path(path)
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        return cls(a=d["a"], b=d["b"])
