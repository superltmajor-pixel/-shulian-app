from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maintenance import write_source_manifest  # noqa: E402


if __name__ == "__main__":
    result = write_source_manifest(ROOT, ROOT / "maintenance-manifest.json")
    print(result["sourceFingerprint"])
