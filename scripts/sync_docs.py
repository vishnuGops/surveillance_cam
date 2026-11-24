"""Synchronize docs/DOCUMENTATION.md -> docs/DOCUMENTATION.html.

Single-source-of-truth documentation generator:
- Converts docs/DOCUMENTATION.md to a sleek, standalone, offline-friendly HTML
  document with a sticky sidebar Table of Contents, theme toggle (Dark/Light),
  responsive tables, and copy buttons on code blocks.
- Embeds a deterministic SHA-256 hash of the Markdown source so `--check` can
  verify that Markdown and HTML docs are strictly in sync.

Usage:
    python scripts/sync_docs.py          # Generate/update docs/DOCUMENTATION.html
    python scripts/sync_docs.py --check  # Exit 0 if in sync, 1 if stale
"""

from __future__ import annotations

import argparse
import hashlib
import html
from pathlib import Path
import sys

import markdown

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MD = REPO_ROOT / "docs" / "DOCUMENTATION.md"
DEFAULT_HTML = REPO_ROOT / "docs" / "DOCUMENTATION.html"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="doc-source-sha256" content="{source_hash}" />
    <title>{title}</title>
    <style>
      :root {{
        color-scheme: dark;
        --bg: #080c14;
        --surface: #101724;
        --surface-2: #172033;
        --border: rgb(148 163 184 / 16%);
        --border-strong: rgb(148 163 184 / 30%);
        --text: #edf2f7;
        --muted: #94a3b8;
        --accent: #60a5fa;
        --accent-soft: rgb(59 130 246 / 14%);
        --code-bg: #0b111d;
        --radius: 12px;
      }}

      :root[data-theme="light"] {{
        color-scheme: light;
        --bg: #f8fafc;
        --surface: #ffffff;
        --surface-2: #f1f5f9;
        --border: rgb(15 23 42 / 12%);
        --border-strong: rgb(15 23 42 / 24%);
        --text: #0f172a;
        --muted: #475569;
        --accent: #2563eb;
        --accent-soft: rgb(37 99 235 / 10%);
        --code-bg: #0f172a;
      }}

      *,
      *::before,
      *::after {{
        box-sizing: border-box;
      }}

      html {{
        scroll-behavior: smooth;
      }}

      body {{
        margin: 0;
        min-block-size: 100dvb;
        background: var(--bg);
        color: var(--text);
        font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
        line-height: 1.65;
      }}

      .doc-shell {{
        inline-size: min(1320px, 100%);
        margin-inline: auto;
        padding: clamp(1rem, 2vw, 2rem);
        display: grid;
        grid-template-columns: 270px minmax(0, 1fr);
        gap: 2rem;
        align-items: start;
      }}

      /* Sidebar */
      .sidebar {{
        position: sticky;
        inset-block-start: 1.25rem;
        max-block-size: calc(100dvb - 2.5rem);
        overflow-y: auto;
        scrollbar-gutter: stable;
        overscroll-behavior: contain;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 1rem 1.05rem;
        display: flex;
        flex-direction: column;
        gap: 0.9rem;
      }}

      .sidebar-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.5rem;
        padding-block-end: 0.7rem;
        border-block-end: 1px solid var(--border);
      }}

      .sidebar-brand {{
        font-weight: 700;
        font-size: 0.92rem;
        letter-spacing: -0.01em;
      }}

      .theme-btn {{
        appearance: none;
        border: 1px solid var(--border);
        background: var(--surface-2);
        color: var(--text);
        font: inherit;
        font-size: 0.76rem;
        font-weight: 500;
        padding: 0.3rem 0.6rem;
        border-radius: 8px;
        cursor: pointer;
      }}

      .theme-btn:hover {{
        border-color: var(--border-strong);
      }}

      .toc-title {{
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
        font-weight: 600;
        margin: 0;
      }}

      .toc ul {{
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
      }}

      .toc ul ul {{
        padding-inline-start: 0.85rem;
        margin-block-start: 0.15rem;
      }}

      .toc a {{
        display: block;
        color: var(--muted);
        text-decoration: none;
        font-size: 0.83rem;
        padding: 0.24rem 0.48rem;
        border-radius: 6px;
        transition: background-color 120ms ease, color 120ms ease;
      }}

      .toc a:hover {{
        color: var(--text);
        background: var(--accent-soft);
      }}

      .sync-meta {{
        margin-block-start: auto;
        padding-block-start: 0.75rem;
        border-block-start: 1px solid var(--border);
        font-size: 0.72rem;
        color: var(--muted);
        font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        word-break: break-all;
      }}

      /* Main Content */
      .content {{
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: clamp(1.35rem, 3vw, 2.5rem);
        min-inline-size: 0;
      }}

      .content h1 {{
        margin-block: 0 1rem;
        font-size: clamp(1.55rem, 1.3rem + 1vw, 2.1rem);
        letter-spacing: -0.025em;
        line-height: 1.25;
      }}

      .content h2 {{
        margin-block: 2.2rem 0.85rem;
        padding-block-end: 0.45rem;
        border-block-end: 1px solid var(--border);
        font-size: clamp(1.2rem, 1.05rem + 0.5vw, 1.45rem);
        letter-spacing: -0.015em;
      }}

      .content h3 {{
        margin-block: 1.5rem 0.55rem;
        font-size: 1.05rem;
      }}

      .content p {{
        margin-block: 0.75rem;
      }}

      .content a {{
        color: var(--accent);
      }}

      .content blockquote {{
        margin: 1rem 0;
        padding: 0.8rem 1rem;
        border-inline-start: 3px solid var(--accent);
        background: var(--accent-soft);
        border-radius: 0 8px 8px 0;
      }}

      .content blockquote p {{
        margin: 0;
      }}

      .content hr {{
        border: 0;
        border-block-start: 1px solid var(--border);
        margin-block: 1.75rem;
      }}

      .content ul,
      .content ol {{
        padding-inline-start: 1.4rem;
      }}

      .content li {{
        margin-block: 0.32rem;
      }}

      .content code {{
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.86em;
        padding: 0.14rem 0.38rem;
        border-radius: 6px;
        background: var(--surface-2);
        border: 1px solid var(--border);
      }}

      .code-wrap {{
        position: relative;
        margin-block: 1rem;
      }}

      .content pre {{
        margin: 0;
        padding: 1rem 1.1rem;
        border-radius: 10px;
        background: var(--code-bg);
        color: #e2e8f0;
        border: 1px solid var(--border);
        overflow-x: auto;
        line-height: 1.5;
        font-size: 0.84rem;
      }}

      .content pre code {{
        background: transparent;
        border: 0;
        padding: 0;
        color: inherit;
        font-size: inherit;
      }}

      .copy-btn {{
        position: absolute;
        inset-block-start: 0.55rem;
        inset-inline-end: 0.55rem;
        appearance: none;
        border: 1px solid rgb(255 255 255 / 16%);
        background: rgb(15 23 42 / 85%);
        color: #e2e8f0;
        font: inherit;
        font-size: 0.72rem;
        padding: 0.25rem 0.55rem;
        border-radius: 6px;
        cursor: pointer;
      }}

      .copy-btn:hover {{
        background: rgb(30 41 59 / 95%);
      }}

      /* Responsive Tables */
      .table-wrap {{
        overflow-x: auto;
        margin-block: 1rem;
        border: 1px solid var(--border);
        border-radius: 10px;
      }}

      .content table {{
        inline-size: 100%;
        border-collapse: collapse;
        font-size: 0.88rem;
      }}

      .content th,
      .content td {{
        text-align: start;
        padding: 0.65rem 0.85rem;
        border-block-end: 1px solid var(--border);
        vertical-align: top;
      }}

      .content th {{
        background: var(--surface-2);
        font-weight: 600;
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--muted);
      }}

      .content tr:last-child td {{
        border-block-end: 0;
      }}

      @media (max-width: 960px) {{
        .doc-shell {{
          grid-template-columns: 1fr;
        }}

        .sidebar {{
          position: static;
          max-block-size: none;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="doc-shell">
      <aside class="sidebar" aria-label="Document navigation">
        <div class="sidebar-header">
          <span class="sidebar-brand">HomeWatch NVR Docs</span>
          <button type="button" class="theme-btn" id="btn-theme">Light</button>
        </div>
        <p class="toc-title">On This Page</p>
        <nav class="toc">{toc_html}</nav>
        <div class="sync-meta">
          Synced from DOCUMENTATION.md<br />
          SHA-256: {short_hash}
        </div>
      </aside>

      <main class="content">
        {body_html}
      </main>
    </div>

    <script>
      (() => {{
        const root = document.documentElement;
        const themeBtn = document.getElementById("btn-theme");
        const saved = localStorage.getItem("homewatch-doc-theme");
        if (saved === "light" || saved === "dark") {{
          root.dataset.theme = saved;
        }}
        function syncLabel() {{
          themeBtn.textContent = root.dataset.theme === "dark" ? "Light" : "Dark";
        }}
        syncLabel();
        themeBtn.addEventListener("click", () => {{
          root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
          localStorage.setItem("homewatch-doc-theme", root.dataset.theme);
          syncLabel();
        }});

        // Wrap tables for horizontal overflow stability
        document.querySelectorAll(".content table").forEach((table) => {{
          const wrap = document.createElement("div");
          wrap.className = "table-wrap";
          table.parentNode.insertBefore(wrap, table);
          wrap.appendChild(table);
        }});

        // Add copy buttons to fenced code blocks
        document.querySelectorAll(".content pre").forEach((pre) => {{
          const wrap = document.createElement("div");
          wrap.className = "code-wrap";
          pre.parentNode.insertBefore(wrap, pre);
          wrap.appendChild(pre);

          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "copy-btn";
          btn.textContent = "Copy";
          btn.addEventListener("click", async () => {{
            try {{
              await navigator.clipboard.writeText(pre.textContent || "");
              btn.textContent = "Copied";
              setTimeout(() => (btn.textContent = "Copy"), 1500);
            }} catch {{
              btn.textContent = "Failed";
            }}
          }});
          wrap.appendChild(btn);
        }});
      }})();
    </script>
  </body>
</html>
"""


def render_html(md_text: str) -> str:
    normalized = md_text.replace("\r\n", "\n")
    source_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    md = markdown.Markdown(
        extensions=[
            "tables",
            "fenced_code",
            "toc",
            "sane_lists",
            "admonition",
        ],
        extension_configs={
            "toc": {
                "toc_depth": "2-3",
                "permalink": False,
            }
        },
    )
    body_html = md.convert(normalized)
    toc_html = md.toc or ""

    title = "HomeWatch NVR — Documentation"
    for line in normalized.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    return HTML_TEMPLATE.format(
        source_hash=source_hash,
        short_hash=source_hash[:12],
        title=html.escape(title),
        toc_html=toc_html,
        body_html=body_html,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync docs/DOCUMENTATION.md into standalone docs/DOCUMENTATION.html."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_MD)
    parser.add_argument("--output", type=Path, default=DEFAULT_HTML)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify HTML matches Markdown without modifying files.",
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"ERROR: Source Markdown not found: {args.source}", file=sys.stderr)
        return 2

    md_text = args.source.read_text(encoding="utf-8")
    expected_html = render_html(md_text)

    if args.check:
        if not args.output.exists():
            print(f"OUT OF SYNC: {args.output} does not exist.", file=sys.stderr)
            return 1
        current_html = args.output.read_text(encoding="utf-8").replace("\r\n", "\n")
        if current_html != expected_html:
            print(
                f"OUT OF SYNC: {args.output} differs from {args.source}. "
                "Run `python scripts/sync_docs.py`.",
                file=sys.stderr,
            )
            return 1
        print(f"IN SYNC: {args.output} matches {args.source}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected_html, encoding="utf-8", newline="\n")
    print(f"Synced {args.source} -> {args.output} ({len(expected_html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
