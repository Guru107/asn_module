from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCH_ROOT = ROOT.parent / "bench16"
EPHEMERAL_PREFIX = "asn-py-"


def _default_sites_root(bench_root: Path) -> Path:
	return bench_root / "sites"


def _is_ephemeral_site(path: Path) -> bool:
	return path.is_dir() and path.name.startswith(EPHEMERAL_PREFIX)


def _delete_site(
	site_name: str, *, bench_root: Path, db_root_username: str, db_root_password: str | None
) -> int:
	if not site_name.startswith(EPHEMERAL_PREFIX):
		raise ValueError(f"Refusing to delete non-ephemeral site: {site_name}")

	site_path = _default_sites_root(bench_root) / site_name
	if not site_path.exists():
		print(f"No site directory found for {site_name} under {_default_sites_root(bench_root)}")
		return 1

	command = [
		"bench",
		"drop-site",
		site_name,
		"--force",
		"--no-backup",
		"--db-root-username",
		db_root_username,
	]
	if db_root_password:
		command.extend(["--db-root-password", db_root_password])

	subprocess.run(command, check=True, cwd=bench_root)
	print(f"Deleted {site_name}")
	return 0


def _iter_stale_sites(sites_root: Path, minimum_age_seconds: int):
	now = time.time()
	for path in sorted(sites_root.iterdir()):
		if not _is_ephemeral_site(path):
			continue
		age_seconds = int(now - path.stat().st_mtime)
		if age_seconds < minimum_age_seconds:
			continue
		yield {
			"site_name": path.name,
			"age_seconds": age_seconds,
			"modified": int(path.stat().st_mtime),
			"path": str(path),
		}


def main() -> int:
	parser = argparse.ArgumentParser(description="List or delete stale ephemeral Frappe test sites.")
	parser.add_argument("--bench-root", type=Path, default=DEFAULT_BENCH_ROOT)
	parser.add_argument("--min-age-seconds", type=int, default=3600)
	parser.add_argument("--delete", dest="site_to_delete")
	parser.add_argument(
		"--force-rm", action="store_true", help="Delete site directory directly if bench drop-site fails."
	)
	args = parser.parse_args()

	if args.site_to_delete:
		try:
			return _delete_site(
				args.site_to_delete,
				bench_root=args.bench_root,
				db_root_username=os.environ.get("DB_ROOT_USERNAME", "root"),
				db_root_password=os.environ.get("DB_ROOT_PASSWORD"),
			)
		except Exception:
			if not args.force_rm:
				raise
			site_path = _default_sites_root(args.bench_root) / args.site_to_delete
			shutil.rmtree(site_path, ignore_errors=False)
			print(f"Deleted {args.site_to_delete} with force-rm")
			return 0

	for description in _iter_stale_sites(_default_sites_root(args.bench_root), args.min_age_seconds):
		print(
			f"{description['site_name']}\tage={description['age_seconds']}s\t"
			f"modified={description['modified']}\tpath={description['path']}"
		)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
