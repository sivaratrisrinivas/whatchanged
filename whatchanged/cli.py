"""whatchanged FROM TO [-o FILE]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .diff import diff
from .envs import DEFAULT_CACHE, snapshot
from .guides import GUIDES
from .report import render


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="whatchanged",
                                 description="Report what changed between two elevenlabs SDK versions.")
    ap.add_argument("from_version")
    ap.add_argument("to_version")
    ap.add_argument("-o", "--output", help="write the Markdown report here (default: stdout)")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE),
                    help=f"cache directory (default: {DEFAULT_CACHE})")
    ap.add_argument("--refresh", action="store_true", help="re-run capture even if a snapshot is cached")
    ap.add_argument("--guide", choices=sorted(GUIDES),
                    help="flag changes the named upgrade guide does not mention as possible additions")
    args = ap.parse_args(argv)

    cache = Path(args.cache)
    old = snapshot(args.from_version, cache, args.refresh)
    new = snapshot(args.to_version, cache, args.refresh)
    md = render(diff(old, new, args.from_version, args.to_version),
                GUIDES.get(args.guide))
    if args.output:
        Path(args.output).write_text(md)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
