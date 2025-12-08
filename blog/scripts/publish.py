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
import json
import re
import subprocess
import sys
import tempfile
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


def ensure_mmdc() -> str:
    """Ensure mmdc (mermaid-cli) is available, install if needed. Returns path to mmdc."""
    # Check if mmdc is already available
    result = subprocess.run(["which", "mmdc"], capture_output=True, check=False)
    if result.returncode == 0:
        return "mmdc"

    # Check if npx is available (preferred for auto-install)
    result = subprocess.run(["which", "npx"], capture_output=True, check=False)
    if result.returncode == 0:
        print("mmdc not found, will use npx to run it...")
        return "npx:mmdc"

    # Try to install globally
    print("mmdc not found, installing @mermaid-js/mermaid-cli...")
    result = subprocess.run(
        ["npm", "install", "-g", "@mermaid-js/mermaid-cli"],
        capture_output=True,
        check=False
    )
    if result.returncode != 0:
        raise SystemExit(
            f"Failed to install mermaid-cli: {result.stderr.decode()}\n"
            "Install manually with: npm install -g @mermaid-js/mermaid-cli"
        )
    return "mmdc"


# Mermaid config to fix text cutoff (use native SVG text instead of foreignObject)
MERMAID_CONFIG = {
    "htmlLabels": False,
    "flowchart": {
        "htmlLabels": False
    }
}


def render_mermaid_diagrams(markdown: str, mmdc_path: str = "mmdc") -> str:
    """Find mermaid code blocks and replace them with rendered SVGs."""
    pattern = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)

    # Build command prefix based on mmdc_path
    if mmdc_path == "npx:mmdc":
        cmd_prefix = ["npx", "-y", "@mermaid-js/mermaid-cli"]
    else:
        cmd_prefix = [mmdc_path]

    def replace_with_svg(match: re.Match[str]) -> str:
        mermaid_code = match.group(1)
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "diagram.mmd"
            output_path = Path(tmpdir) / "diagram.svg"
            config_path = Path(tmpdir) / "config.json"

            input_path.write_text(mermaid_code)
            config_path.write_text(json.dumps(MERMAID_CONFIG))

            cmd = cmd_prefix + [
                "-i", str(input_path),
                "-o", str(output_path),
                "-c", str(config_path),
                "-b", "transparent"
            ]
            result = subprocess.run(cmd, capture_output=True, check=False)
            if result.returncode != 0:
                print(f"Warning: mmdc failed: {result.stderr.decode()}", file=sys.stderr)
                # Return original block if rendering fails
                return match.group(0)

            svg_content = output_path.read_text()
            # Remove XML declaration if present
            svg_content = re.sub(r"<\?xml[^>]*\?>\s*", "", svg_content)
            return svg_content

    return pattern.sub(replace_with_svg, markdown)


def run_pandoc(markdown: str, pandoc_path: str = "pandoc") -> str:
    """Convert markdown to HTML fragment using pandoc."""
    cmd = [pandoc_path, "--from", "gfm", "--to", "html", "--wrap=none", "--no-highlight"]
    result = subprocess.run(cmd, input=markdown.encode(), capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"pandoc failed: {result.stderr.decode()}")
    return result.stdout.decode()


def wrap_in_template(content_html: str, title: str, date: datetime) -> str:
    """Wrap HTML content in a full page template with header/footer."""
    date_str = date.strftime("%B %-d, %Y")
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} - Noam Lewis</title>
  <link rel="stylesheet" href="/blog/assets/blog.css">
  <link rel="alternate" type="application/atom+xml" title="Noam Lewis - The Blog" href="/blog/feed.xml">
</head>
<body>

<header class="site-header">
  <div class="wrapper">
    <a class="site-title" href="/blog/">Noam Lewis - The Blog</a>
    <nav class="site-nav">
      <a class="page-link" href="/blog/about/">About</a>
    </nav>
  </div>
</header>

<main class="wrapper">
  <article>
    <p class="post-meta" style="color: var(--color-text-light); margin-bottom: 30px;">{date_str}</p>
{content_html}
  </article>

  <section class="comments">
    <script src="https://utteranc.es/client.js"
        repo="sinelaw/utterances"
        issue-term="pathname"
        theme="github-light"
        crossorigin="anonymous"
        async>
    </script>
  </section>
</main>

<footer class="site-footer">
  <div class="wrapper">
    <a href="/blog/">← Back to all posts</a>
    <div class="social-links">
      <a href="https://x.com/TheNoamLewis" title="Twitter/X" aria-label="Twitter">
        <img src="/blog/assets/icon-x.svg" alt="X/Twitter" width="24" height="24">
      </a>
      <a href="https://github.com/sinelaw" title="GitHub" aria-label="GitHub">
        <img src="/blog/assets/icon-github.svg" alt="GitHub" width="24" height="24">
      </a>
    </div>
  </div>
</footer>

</body>
</html>
'''


def slugify(title: str) -> str:
    """Convert title to URL-friendly slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def scan_posts(blog_dir: Path) -> list[tuple[datetime, str, str]]:
    """Scan blog directory for HTML posts, return list of (date, title, url)."""
    posts = []
    # Exclude non-post files
    exclude = {"index.html", "404.html"}

    for html_file in blog_dir.rglob("*.html"):
        if html_file.name in exclude:
            continue
        if html_file.parent.name == "about":
            continue

        try:
            content = html_file.read_text()

            # Extract title from <title>...</title>
            title_match = re.search(r"<title>(.+?)</title>", content)
            if not title_match:
                continue
            title = title_match.group(1)
            # Remove " - Noam Lewis" suffix if present
            title = re.sub(r"\s*-\s*Noam Lewis$", "", title)

            # Extract date from <p class="post-meta"...>DATE</p>
            date_match = re.search(r'<p class="post-meta"[^>]*>([^<]+)</p>', content)
            if not date_match:
                continue
            date_str = date_match.group(1).strip()

            # Parse date (e.g., "December 7, 2025")
            try:
                post_date = datetime.strptime(date_str, "%B %d, %Y")
            except ValueError:
                # Try alternate format
                try:
                    post_date = datetime.strptime(date_str, "%b %d, %Y")
                except ValueError:
                    continue

            # Compute URL relative to blog dir
            rel_path = html_file.relative_to(blog_dir)
            post_url = f"/blog/{rel_path}"

            posts.append((post_date, title, post_url))
        except Exception as e:
            print(f"Warning: Could not parse {html_file}: {e}", file=sys.stderr)

    # Sort by date descending
    posts.sort(key=lambda x: x[0], reverse=True)
    return posts


def rebuild_index(index_path: Path, blog_dir: Path) -> None:
    """Rebuild post list in index.html from actual HTML files."""
    posts = scan_posts(blog_dir)

    # Generate post list HTML
    entries = []
    for post_date, title, post_url in posts:
        date_str = post_date.strftime("%b %-d, %Y")  # e.g., "Dec 7, 2025"
        entry = f'''<li>
          <span class="post-meta">{date_str}</span>
          <h3>
            <a class="post-link" href="{post_url}">
              {html.escape(title)}
            </a>
          </h3>
        </li>'''
        entries.append(entry)

    post_list_html = "\n        ".join(entries)

    # Read index and replace post list
    content = index_path.read_text()

    # Find and replace the entire post list
    pattern = r'(<ul class="post-list">).*?(</ul>)'
    replacement = rf'\1\n        {post_list_html}\n      \2'
    new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

    if count == 0:
        print("Warning: Could not find post-list in index.html", file=sys.stderr)
        return

    index_path.write_text(new_content)
    print(f"Rebuilt {index_path} with {len(posts)} posts")


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

    # Render mermaid diagrams to SVG (if any)
    if "```mermaid" in md_content:
        mmdc_path = ensure_mmdc()
        md_content = render_mermaid_diagrams(md_content, mmdc_path)

    # Convert markdown to HTML
    content_html = run_pandoc(md_content)

    # Wrap in full page template
    full_html = wrap_in_template(content_html, title, date)

    # Write HTML file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_html)
    print(f"Created {output_path}")

    # Rebuild index from all posts
    index_path = blog_dir / "index.html"
    if index_path.exists():
        rebuild_index(index_path, blog_dir)

    # Update feed
    feed_path = blog_dir / "feed.xml"
    if feed_path.exists():
        update_feed(feed_path, post_url, title, date, content_html)

    print("\nDone! Don't forget to commit and push.")


if __name__ == "__main__":
    main()
