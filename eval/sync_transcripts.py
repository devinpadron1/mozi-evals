"""Download a pinned Ask Hormozi transcript snapshot before classification."""
from __future__ import annotations

import argparse
import json
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / 'data' / 'ask-hormozi'
REPOSITORY = 'poseljacob/ask-hormozi'
METADATA = {'catalog.json', 'transcript-manifest.json', 'NOTICE.md'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='main', help='Upstream commit SHA or branch.')
    args = parser.parse_args()
    if DESTINATION.exists():
        parser.error(f'{DESTINATION} already exists; reuse the installed snapshot.')
    request = Request(
        f'https://api.github.com/repos/{REPOSITORY}/commits/{args.ref}',
        headers={'User-Agent': 'mozi-evals/1.0'},
    )
    with urlopen(request, timeout=30) as response:
        commit = json.load(response)['sha']
    archive_url = f'https://codeload.github.com/{REPOSITORY}/tar.gz/{commit}'
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DESTINATION.parent) as temporary:
        snapshot = Path(temporary) / 'snapshot'
        snapshot.mkdir()
        count = 0
        total_bytes = 0
        print(f'Downloading transcript snapshot {commit}…', flush=True)
        with urlopen(Request(archive_url, headers={'User-Agent': 'mozi-evals/1.0'}), timeout=120) as response:
            with tarfile.open(fileobj=response, mode='r|gz') as archive:
                for member in archive:
                    parts = PurePosixPath(member.name).parts
                    if not member.isfile() or len(parts) < 3 or parts[1] != 'corpus':
                        continue
                    is_transcript = len(parts) == 4 and parts[2] == 'transcripts' and parts[3].endswith('.md')
                    is_metadata = len(parts) == 3 and parts[2] in METADATA
                    if not (is_transcript or is_metadata) or any(part in ('.', '..') for part in parts):
                        continue
                    target = snapshot.joinpath(*parts[2:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, target.open('wb') as destination:
                        shutil.copyfileobj(source, destination)
                    if is_transcript:
                        count += 1
                        total_bytes += member.size
        if not count or any(not (snapshot / name).is_file() for name in METADATA):
            raise RuntimeError('The upstream archive is missing transcripts or source metadata.')
        snapshot_info = {
            'repository': f'https://github.com/{REPOSITORY}',
            'commit': commit,
            'archive_url': archive_url,
            'downloaded_at': datetime.now(timezone.utc).isoformat(),
            'transcript_count': count,
            'transcript_bytes': total_bytes,
        }
        (snapshot / 'snapshot.json').write_text(json.dumps(snapshot_info, indent=2) + '\n')
        snapshot.rename(DESTINATION)
    print(f'Saved {count:,} transcripts ({total_bytes / 1_000_000:.1f} MB) to {DESTINATION}', flush=True)


if __name__ == '__main__':
    main()
