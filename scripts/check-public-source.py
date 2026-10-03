"""Reject private runtime data in a working tree or staged public-source snapshot."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from public_source import private_path, public_web_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Check every file in the proposed Git index")
    args = parser.parse_args()
    command = ["git", "ls-files", "-z"]
    if not args.staged:
        command += ["--cached", "--others", "--exclude-standard"]
    raw = subprocess.check_output(command, cwd=ROOT)
    paths = [p for p in raw.decode("utf-8").split("\0") if p and (args.staged or (ROOT / p).is_file())]
    bad = [p for p in paths if private_path(p) or (p.startswith("web/") and not public_web_file(p))]
    if bad:
        print("Private/unapproved files must not be committed:\n" + "\n".join(bad))
        return 1
    print(f"Public source boundary OK: {len(paths)} files checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
