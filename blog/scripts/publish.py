#!/usr/bin/env python3
"""Publish a blog post: convert markdown to HTML, update index and RSS feed.

Usage:
    python scripts/publish.py md/my-post.md --title "My Post Title"

This will:
1. Convert the markdown to HTML in blog/YYYY/MM/DD/my-post.html
2. Add the post to index.html
3. Add the post to feed.xml (Atom feed)

Run from the blog/ directory.
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def strip_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Remove leading YAML front matter, return metadata dict and remaining text."""
    metadata: dict[str, str] = {}
    if not text.startswith("---\n"):
        return metadata, text

    lines = text.splitlines()
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            # Parse simple key: value pairs from front matter
            for line in lines[1:idx]:
                if ":" in line:
                    key, _, value = line.partition(":")
                    metadata[key.strip()] = value.strip().strip('"').strip("'")
            rest = "\n".join(lines[idx + 1:])
            return metadata, rest + ("\n" if text.endswith("\n") else "")
    return metadata, text


def extract_title_from_markdown(text: str) -> str | None:
    """Extract title from first H1 heading."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def run_pandoc(markdown: str, pandoc_path: str = "pandoc") -> str:
    """Convert markdown to HTML fragment using pandoc."""
    cmd = [pandoc_path, "--from", "gfm", "--to", "html", "--wrap=none", "--no-highlight"]
    result = subprocess.run(cmd, input=markdown.encode(), capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"pandoc failed: {result.stderr.decode()}")
    return result.stdout.decode()


def slugify(title: str) -> str:
    """Convert title to URL-friendly slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def update_index(index_path: Path, post_url: str, title: str, date: datetime) -> None:
    """Insert new post at top of the post list in index.html."""
    content = index_path.read_text()

    date_str = date.strftime("%b %-d, %Y")  # e.g., "Dec 7, 2025"

    new_entry = f'''<li><span class="post-meta">{date_str}</span>
        <h3>
          <a class="post-link" href="{post_url}">
            {html.escape(title)}
          </a>
        </h3></li>'''

    # Find the post list and insert after opening tag
    marker = '<ul class="post-list">'
    if marker not in content:
        print(f"Warning: Could not find '{marker}' in index.html", file=sys.stderr)
        return

    content = content.replace(marker, marker + new_entry, 1)
    index_path.write_text(content)
    print(f"Updated {index_path}")


def update_feed(feed_path: Path, post_url: str, title: str, date: datetime,
                content_html: str, base_url: str = "/blog") -> None:
    """Add new entry to Atom feed."""
    feed_content = feed_path.read_text()

    # Format date for Atom
    date_str = date.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    post_id = f"{base_url}{post_url}" if not post_url.startswith("/") else post_url

    # Escape HTML content for CDATA
    escaped_content = content_html.replace("]]>", "]]]]><![CDATA[>")

    new_entry = f'''<entry><title type="html">{html.escape(title)}</title><link href="{post_url}" rel="alternate" type="text/html" title="{html.escape(title)}" /><published>{date_str}</published><updated>{date_str}</updated><id>{post_id}</id><content type="html" xml:base="{post_url}"><![CDATA[{escaped_content}]]></content><author><name></name></author></entry>'''

    # Update the feed's <updated> timestamp
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    feed_content = re.sub(
        r"<updated>[^<]+</updated>",
        f"<updated>{now_str}</updated>",
        feed_content,
        count=1
    )

    # Insert new entry after the <id> element (before first existing entry)
    # Find position after </id>...<entry>
    match = re.search(r"</id><title[^>]*>[^<]*</title>", feed_content)
    if match:
        insert_pos = match.end()
        feed_content = feed_content[:insert_pos] + new_entry + feed_content[insert_pos:]
    else:
        # Fallback: insert before first <entry>
        feed_content = feed_content.replace("<entry>", new_entry + "<entry>", 1)

    feed_path.write_text(feed_content)
    print(f"Updated {feed_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("markdown", type=Path, help="Markdown file to publish")
    parser.add_argument("--title", "-t", help="Post title (default: extracted from first H1)")
    parser.add_argument("--date", "-d", help="Post date YYYY-MM-DD (default: today)")
    parser.add_argument("--slug", "-s", help="URL slug (default: derived from title)")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    # Determine blog root (script is in blog/scripts/)
    script_dir = Path(__file__).parent
    blog_dir = script_dir.parent

    # Read and parse markdown
    md_text = args.markdown.read_text()
    metadata, md_content = strip_front_matter(md_text)

    # Determine title
    title = args.title or metadata.get("title") or extract_title_from_markdown(md_content)
    if not title:
        raise SystemExit("Could not determine title. Use --title or add an H1 heading.")

    # Determine date
    if args.date:
        date = datetime.strptime(args.date, "%Y-%m-%d")
    elif "date" in metadata:
        date = datetime.strptime(metadata["date"][:10], "%Y-%m-%d")
    else:
        date = datetime.now()

    # Determine slug and output path
    slug = args.slug or slugify(title)
    date_path = date.strftime("%Y/%m/%d")
    output_path = blog_dir / date_path / f"{slug}.html"
    post_url = f"/blog/{date_path}/{slug}.html"

    print(f"Title: {title}")
    print(f"Date: {date.strftime('%Y-%m-%d')}")
    print(f"Output: {output_path}")
    print(f"URL: {post_url}")

    if args.dry_run:
        print("\n[Dry run - no files modified]")
        return

    # Convert markdown to HTML
    content_html = run_pandoc(md_content)

    # Write HTML file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content_html)
    print(f"Created {output_path}")

    # Update index
    index_path = blog_dir / "index.html"
    if index_path.exists():
        update_index(index_path, post_url, title, date)

    # Update feed
    feed_path = blog_dir / "feed.xml"
    if feed_path.exists():
        update_feed(feed_path, post_url, title, date, content_html)

    print("\nDone! Don't forget to commit and push.")


if __name__ == "__main__":
    main()
