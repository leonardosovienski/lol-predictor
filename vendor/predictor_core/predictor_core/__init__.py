"""Alias de importación para el paquete predictor_core.

El repositorio vive en la raíz del proyecto, pero las pruebas y la API esperan
importar el paquete con el nombre predictor_core. Este shim expone ese nombre
sin duplicar el código fuente real.
"""

from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parent.parent
__path__ = [str(ROOT)]

# Cargar el __init__.py real del repositorio como módulo de respaldo para
# preservar la API pública esperada por los consumidores.
REAL_INIT = ROOT / "__init__.py"
if REAL_INIT.exists():
    spec = importlib.util.spec_from_file_location("_predictor_core_real_init", REAL_INIT)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for name in getattr(module, "__all__", []):
            globals()[name] = getattr(module, name)
        globals()["__version__"] = getattr(module, "__version__", "0")
        globals()["__all__"] = getattr(module, "__all__", [])
