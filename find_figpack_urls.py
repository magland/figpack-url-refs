#!/usr/bin/env python3
"""
find_figpack_urls.py

Search public GitHub repos for Markdown files containing
URLs that start with https://figures.figpack.org/, clone those repos,
scan their .md files exhaustively, and produce a JSON list of records:

{ "repo": "owner/name", "file": "relative/path/to/file.md", "url": "https://figures.figpack.org/..." }

Usage:
  python find_figpack_urls.py \
    --out figpack_refs.json \
    --workdir ./_repos \
    --max-pages 10 \
    --per-page 100
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Set, Tuple

import requests

SEARCH_ENDPOINT = "https://api.github.com/search/code"
REPO_ENDPOINT = "https://api.github.com/repos/{full_name}"
GITHUB_WEB_CLONE_URL = "https://github.com/{full_name}.git"

FIGPACK_PREFIX = "https://figures.figpack.org/"
FIGPACK_SUFFIX = "/index.html"


def print_flush(*args, **kwargs):
    print(*args, **kwargs)
    sys.stdout.flush()


def ensure_git_available():
    try:
        subprocess.run(
            ["git", "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        print_flush("ERROR: `git` is required but not found in PATH.")
        raise SystemExit(1)


def github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "figpack-search-script",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def handle_rate_limit(resp):
    if resp.status_code != 403:
        return
    remaining = resp.headers.get("X-RateLimit-Remaining")
    reset = resp.headers.get("X-RateLimit-Reset")
    if remaining == "0" and reset:
        reset_ts = int(reset)
        wait_s = max(0, reset_ts - int(time.time())) + 1
        print_flush(
            f"Hit GitHub rate limit. Sleeping for {wait_s} seconds until reset..."
        )
        time.sleep(wait_s)


def search_code(max_pages: int, per_page: int) -> List[Dict]:
    """
    Use GitHub code search to find Markdown files in public repos containing the figpack URL prefix.
    Returns the raw 'items' across pages (limited by GitHub to ~1000 total).
    """
    q = 'in:file extension:md "https://figures.figpack.org/"'
    headers = github_headers()
    all_items: List[Dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "q": q,
            "per_page": per_page,
            "page": page,
        }
        print_flush(f"[Search] Page {page}/{max_pages} …")
        resp = requests.get(SEARCH_ENDPOINT, headers=headers, params=params)
        if resp.status_code == 403:
            handle_rate_limit(resp)
            resp = requests.get(SEARCH_ENDPOINT, headers=headers, params=params)
        if resp.status_code != 200:
            print_flush(
                f"  ⚠️ GitHub search failed (status {resp.status_code}): {resp.text[:200]}"
            )
            break
        data = resp.json()
        items = data.get("items", [])
        print_flush(f"  Found {len(items)} items on this page.")
        if not items:
            break
        all_items.extend(items)
        # Stop early if results likely exhausted (GitHub caps search results ~1000)
        if len(items) < per_page:
            break
    print_flush(f"[Search] Total items collected: {len(all_items)}")
    return all_items


def collect_unique_repos(items: List[Dict]) -> List[str]:
    repos: Set[str] = set()
    for it in items:
        repo = it.get("repository", {})
        full_name = repo.get("full_name")
        if full_name:
            repos.add(full_name)
    repo_list = sorted(repos)
    print_flush(f"[Collect] Unique repositories: {len(repo_list)}")
    return repo_list


def clone_repo(full_name: str, workdir: Path) -> Tuple[str, Path, bool]:
    """
    Clone a repository's default branch (shallow, single-branch) into workdir.
    Returns (repo_full_name, clone_path, success).
    """
    target = workdir / full_name.replace("/", "__")
    if target.exists():
        print_flush(f"[Clone] Skipping (already exists): {full_name}")
        return full_name, target, True

    url = GITHUB_WEB_CLONE_URL.format(full_name=full_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    print_flush(f"[Clone] Cloning {full_name} …")
    try:
        # Shallow, single-branch clone pulls the default branch by default.
        subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                "--no-tags",
                "--single-branch",
                url,
                str(target),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print_flush(f"  ✓ Cloned {full_name}")
        return full_name, target, True
    except subprocess.CalledProcessError as e:
        print_flush(
            f"  ✗ Clone failed for {full_name}: {e.stderr.decode(errors='ignore')[:300]}"
        )
        return full_name, target, False


def read_text_file(path: Path) -> str:
    # Try UTF-8, then ISO-8859-1 fallback
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except Exception:
        try:
            return path.read_text(encoding="latin-1", errors="ignore")
        except Exception:
            return ""


def scan_repo_for_figpack(full_name: str, repo_dir: Path) -> List[Dict]:
    """
    Walk all .md files and extract FIGPACK URLs that end with /index.html.
    """
    results: List[Dict] = []
    for md_path in repo_dir.rglob("*.md"):
        rel = md_path.relative_to(repo_dir)
        text = read_text_file(md_path)
        if not text:
            continue

        pos = 0
        while True:
            # Find start of URL
            start_idx = text.find(FIGPACK_PREFIX, pos)
            if start_idx == -1:
                break

            # Find the next /index.html after this position
            end_idx = text.find(FIGPACK_SUFFIX, start_idx)
            if end_idx == -1:
                pos = start_idx + 1
                continue

            # Extract the complete URL
            url = text[start_idx : end_idx + len(FIGPACK_SUFFIX)]
            results.append(
                {
                    "repo": full_name,
                    "file": str(rel).replace(os.sep, "/"),
                    "url": url,
                }
            )
            pos = end_idx + 1

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Find https://figures.figpack.org/ URLs in public GitHub Markdown files."
    )
    parser.add_argument(
        "--out", default="figpack-url-refs.json", help="Output JSON file path"
    )
    parser.add_argument(
        "--workdir", default="./_repos", help="Working directory to clone repositories"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Max pages to fetch from GitHub code search (each per_page items)",
    )
    parser.add_argument(
        "--per-page", type=int, default=100, help="Items per search page (max 100)"
    )
    parser.add_argument(
        "--max-workers", type=int, default=8, help="Parallelism for cloning/scanning"
    )
    args = parser.parse_args()

    ensure_git_available()

    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    print_flush("=== Step 1: Searching GitHub Code Search ===")
    items = search_code(args.max_pages, args.per_page)

    print_flush("=== Step 2: Collecting unique repositories ===")
    repos = collect_unique_repos(items)
    if not repos:
        print_flush("No repositories found. Exiting.")
        Path(args.out).write_text("[]", encoding="utf-8")
        return

    print_flush("=== Step 3: Cloning repositories (default branch, shallow) ===")
    clone_results: Dict[str, Path] = {}
    with ThreadPoolExecutor(max_workers=args.max_workers) as exe:
        futs = {
            exe.submit(clone_repo, full_name, workdir): full_name for full_name in repos
        }
        for fut in as_completed(futs):
            full_name, repo_dir, ok = fut.result()
            if ok:
                clone_results[full_name] = repo_dir
    print_flush(f"Cloned OK: {len(clone_results)} / {len(repos)}")

    if not clone_results:
        print_flush("No repositories cloned successfully. Exiting.")
        Path(args.out).write_text("[]", encoding="utf-8")
        return

    print_flush(
        "=== Step 4: Scanning cloned repos for Markdown files and FIGPACK URLs ==="
    )
    all_records: List[Dict] = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as exe:
        futs = {
            exe.submit(scan_repo_for_figpack, full_name, repo_dir): full_name
            for full_name, repo_dir in clone_results.items()
        }
        for fut in as_completed(futs):
            full_name = futs[fut]
            try:
                records = fut.result()
                print_flush(f"[Scan] {full_name}: {len(records)} record(s) found")
                all_records.extend(records)
            except Exception as e:
                print_flush(f"[Scan] ERROR in {full_name}: {e}")

    # Optional: de-duplicate exact duplicates
    seen = set()
    deduped: List[Dict] = []
    for rec in all_records:
        key = (rec["repo"], rec["file"], rec["url"])
        if key not in seen:
            seen.add(key)
            deduped.append(rec)

    print_flush("=== Step 5: Writing JSON output ===")
    out_path = Path(args.out).resolve()
    out_path.write_text(
        json.dumps(deduped, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print_flush(f"Done. Wrote {len(deduped)} record(s) to {out_path}")


if __name__ == "__main__":
    main()
