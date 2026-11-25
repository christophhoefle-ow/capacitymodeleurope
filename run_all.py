"""Mini-Testläufer ohne pytest:  python tests/run_all.py   (mit pytest: einfach `pytest`)"""
import importlib
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import conftest  # noqa: F401  (setzt die Pfade)

failed = passed = 0
for f in sorted(HERE.glob("test_*.py")):
    mod = importlib.import_module(f.stem)
    for name in dir(mod):
        if name.startswith("test_") and callable(getattr(mod, name)):
            try:
                getattr(mod, name)()
                passed += 1
                print(f"  ok    {f.stem}::{name}")
            except Exception:
                failed += 1
                print(f"  FAIL  {f.stem}::{name}")
                traceback.print_exc()
print(f"\n{passed} bestanden, {failed} fehlgeschlagen")
sys.exit(1 if failed else 0)
