"""Download full Oz Gutenberg texts and re-ingest into Frank Baum workspace."""

from __future__ import annotations

import asyncio
import json
import urllib.request
from pathlib import Path

import httpx

UA = "VERA-oz-reingest/1.0 (educational; +https://www.gutenberg.org)"
API = "http://localhost:8080"
AGENT_NAME = "Frank Baum - Novel"
OUT = Path("/tmp/oz_fulltext")

BOOKS = [
    (55, "01-The-Wonderful-Wizard-of-Oz.txt"),
    (54, "02-The-Marvelous-Land-of-Oz.txt"),
    (486, "03-Ozma-of-Oz.txt"),
    (420, "04-Dorothy-and-the-Wizard-in-Oz.txt"),
    (485, "05-The-Road-to-Oz.txt"),
    (517, "06-The-Emerald-City-of-Oz.txt"),
    (955, "07-The-Patchwork-Girl-of-Oz.txt"),
    (52176, "08-Tik-Tok-of-Oz.txt"),
    (957, "09-The-Scarecrow-of-Oz.txt"),
    (25581, "10-Rinkitink-in-Oz.txt"),
    (24459, "11-The-Lost-Princess-of-Oz.txt"),
    (30852, "12-The-Tin-Woodman-of-Oz.txt"),
]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read()


def download_books() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for gid, name in BOOKS:
        dest = OUT / name
        if dest.exists() and dest.stat().st_size > 20_000:
            print(f"skip {name}")
            paths.append(dest)
            continue
        data = None
        for url in (
            f"https://www.gutenberg.org/files/{gid}/{gid}-0.txt",
            f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt",
            f"https://www.gutenberg.org/files/{gid}/{gid}.txt",
        ):
            try:
                data = fetch(url)
                if len(data) > 20_000:
                    break
            except Exception as exc:
                print(f"  fail {url}: {exc}")
                data = None
        if not data or len(data) < 20_000:
            print(f"FAIL {gid} {name}")
            continue
        dest.write_bytes(data)
        print(f"OK {name} ({len(data)} bytes)")
        paths.append(dest)
    return paths


async def purge_and_upload(paths: list[Path]) -> None:
    from app.stores.sql import WorkspaceStore
    from app.stores.vector import VectorStore

    async with WorkspaceStore() as store:
        agents = await store.list_agents()
        agent = next((a for a in agents if a.get("name") == AGENT_NAME), None)
        if not agent:
            raise SystemExit(f"Agent not found: {AGENT_NAME}")
        ws = agent["workspace_id"]
        print(f"Purging knowledge for workspace {ws}…")
        purge = await store.purge_knowledge(ws)
        print("purge", purge)
        try:
            vec = VectorStore()
            removed = await vec.delete_workspace(ws)
            print("chroma cleared", removed)
        except Exception as exc:  # noqa: BLE001
            print("chroma clear skipped:", exc)

    # Upload via public API
    files = []
    try:
        for p in paths:
            files.append(("files", (p.name, p.read_bytes(), "text/plain")))
        async with httpx.AsyncClient(base_url=API, timeout=120.0) as client:
            r = await client.post(
                "/api/sources/upload",
                data={"workspace_id": ws},
                files=files,
            )
            print("upload status", r.status_code, r.text[:500])
            r.raise_for_status()
            job = r.json()
            job_id = job["id"]
            print("job", job_id)
            for _ in range(180):
                await asyncio.sleep(5)
                st = await client.get(f"/api/sources/jobs/{ws}/{job_id}")
                body = st.json()
                print(
                    f"  status={body.get('status')} progress={body.get('progress')} "
                    f"{(body.get('message') or '')[:80]}"
                )
                if body.get("status") in {"completed", "failed", "error"}:
                    print(json.dumps(body, indent=2)[:1500])
                    break
    finally:
        pass


def main() -> None:
    paths = download_books()
    if len(paths) < 8:
        raise SystemExit(f"Only {len(paths)} books downloaded")
    asyncio.run(purge_and_upload(paths))


if __name__ == "__main__":
    main()
