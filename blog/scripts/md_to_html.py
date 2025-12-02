#!/usr/bin/env python3
"""Convert a Markdown file into a blog-ready HTML fragment.

The script trims YAML front matter by default (so you can feed it Jekyll-style
posts) and then calls pandoc to emit simple HTML without a surrounding layout.
Example:

    python scripts/md_to_html.py path/to/post.md -o 2025/01/01/post.html

Pandoc must be installed and on PATH (or point to it with --pandoc).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def strip_front_matter(text: str) -> str:
    """Remove leading YAML front matter delimited by '---' lines."""
    if not text.startswith("---\n"):
        return text

    lines = text.splitlines()
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            rest = "\n".join(lines[idx + 1 :])
            # Preserve trailing newline if the original had one.
            return rest + ("\n" if text.endswith("\n") and rest and not rest.endswith("\n") else "")
    return text


def run_pandoc(markdown: str, *, from_format: str, pandoc_path: str) -> str:
    """Invoke pandoc to turn Markdown into an HTML fragment."""
    cmd = [
        pandoc_path,
        "--from",
        from_format,
        "--to",
        "html",
        "--wrap=none",
        "--no-highlight",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=markdown.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"pandoc not found at '{pandoc_path}': {exc}") from exc

    if result.returncode != 0:
        raise SystemExit(
            "pandoc failed with exit code {}:\n{}".format(
                result.returncode, result.stderr.decode("utf-8", errors="replace")
            )
        )
    return result.stdout.decode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path, help="Markdown file to convert")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Destination HTML file (default: stdout)",
    )
    parser.add_argument(
        "--from-format",
        default="gfm",
        help="Pandoc input format (default: gfm)",
    )
    parser.add_argument(
        "--keep-front-matter",
        action="store_true",
        help="Do not strip leading YAML front matter",
    )
    parser.add_argument(
        "--pandoc",
        default="pandoc",
        help="Path to the pandoc executable (default: pandoc on PATH)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    markdown_text = args.markdown.read_text(encoding="utf-8")
    if not args.keep_front_matter:
        markdown_text = strip_front_matter(markdown_text)

    html = run_pandoc(markdown_text, from_format=args.from_format, pandoc_path=args.pandoc)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(html, encoding="utf-8")
    else:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()
