"""Hash every file under a folder and print a {relative_path: sha256} mapping.

Usage:
    python hash_task_files.py task_files/summarize_file
    python hash_task_files.py task_files/summarize_file --out hashes.json
    python hash_task_files.py task_files/summarize_file --check hashes.json

Import hash_file / hash_folder from the harness so the run-time hashes use
exactly the same normalization as the pinned manifest hashes.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def hash_file(path: Path) -> str:
    """SHA-256 of a file. Text files have CRLF normalized to LF first, so the
    hash does not change when git or an editor converts line endings."""
    data = Path(path).read_bytes()
    if b"\0" not in data:          # looks like text, not binary
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def hash_folder(folder: Path) -> dict[str, str]:
    """Map each file's path (relative to folder, forward slashes) to its hash."""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"not a folder: {folder}")
    return {
        p.relative_to(folder).as_posix(): hash_file(p)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def compare(expected: dict[str, str], actual: dict[str, str]) -> list[str]:
    """Return a list of human-readable differences (empty list = identical)."""
    problems = []
    for name in sorted(expected.keys() - actual.keys()):
        problems.append(f"missing: {name}")
    for name in sorted(actual.keys() - expected.keys()):
        problems.append(f"unexpected: {name}")
    for name in sorted(expected.keys() & actual.keys()):
        if expected[name] != actual[name]:
            problems.append(f"changed: {name}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Hash a task's starting files.")
    parser.add_argument("folder", type=Path, help="folder of starting files")
    parser.add_argument("--out", type=Path, help="write the hashes to this JSON file")
    parser.add_argument("--check", type=Path, help="compare against a previously saved JSON file")
    args = parser.parse_args()

    actual = hash_folder(args.folder)

    if args.check:
        expected = json.loads(args.check.read_text(encoding="utf-8"))
        problems = compare(expected, actual)
        if problems:
            print("MISMATCH")
            for line in problems:
                print(f"  {line}")
            return 1
        print(f"OK: {len(actual)} file(s) match {args.check}")
        return 0

    text = json.dumps(actual, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {len(actual)} hash(es) to {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())