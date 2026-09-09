import os
import re
import json
import argparse
import mwclient
import pypandoc

def sanitize_filename(title):
    """Removes or replaces characters that are illegal in Windows/macOS/Linux filenames."""
    cleaned = re.sub(r'[\\/:*?"<>|]', '-', title)
    return cleaned.strip()[:250]

def clean_translation_tags(wikitext):
    """Removes translation system markers from the MediaWiki code before conversion."""
    # 1. Strip <languages /> and <languages>...</languages> blocks completely
    text = re.sub(r'<languages\s*/?>.*?(</languages>)?', '', wikitext, flags=re.IGNORECASE | re.DOTALL)

    # 2. Strip opening and closing <translate> tags, but KEEP the actual human content inside them
    text = re.sub(r'</?translate\s*>', '', text, flags=re.IGNORECASE)

    # 3. Strip individual unit tracking comment markers like <!--T:12-->
    text = re.sub(r'<!--T:\d+-->', '', text)

    return text

def mediawiki_to_markdown(wikitext):
    """Cleans up translation tags and converts MediaWiki markup to clean Markdown using Pandoc."""
    try:
        cleaned_wikitext = clean_translation_tags(wikitext)
        markdown = pypandoc.convert_text(cleaned_wikitext, 'gfm', format='mediawiki')
        return markdown
    except Exception as e:
        print(f" Pandoc conversion failed, saving raw text fallback. Error: {e}")
        return wikitext

def should_exclude(page_name, exclude_patterns):
    """Checks if a page name matches any of the compiled regex exclusion patterns."""
    for pattern in exclude_patterns:
        if pattern.search(page_name):
            return True
    return False

def dump_wiki_to_markdown_incremental(site_url, site_path, output_dir, force_full=False, exclude_patterns=None):
    if exclude_patterns is None:
        exclude_patterns = []

    compiled_patterns = []
    for p in exclude_patterns:
        try:
            compiled_patterns.append(re.compile(p))
        except re.error as e:
            print(f"[!] Error: '{p}' is not a valid Regular Expression pattern.")
            print(f"    Details: {e}")
            print("    Hint: Use '^Prefix' instead of 'Prefix*' and 'keyword' instead of '*keyword*'.\n")
            return

    print(f"Connecting to {site_url} (path: {site_path})...")
    try:
        site = mwclient.Site(site_url, path=site_path)
    except Exception as e:
        print(f"[!] Connection failed: {e}")
        return

    print("Scanning wiki structure, metadata, and language variants...")
    pages_by_base = {}

    try:
        all_pages = site.allpages(namespace=0, filterredir='nonredirects')
    except Exception as e:
        print(f"[!] Failed to fetch page index. Verify your path/credentials: {e}")
        return

    skipped_by_filter = 0
    for page in all_pages:
        title = page.name

        if should_exclude(title, compiled_patterns):
            skipped_by_filter += 1
            continue

        if title.endswith('/en'):
            base_title = title[:-3]
            lang = 'en'
        elif title.endswith('/fr'):
            base_title = title[:-3]
            lang = 'fr'
        else:
            base_title = title
            lang = 'default'

        if base_title not in pages_by_base:
            pages_by_base[base_title] = {}
        pages_by_base[base_title][lang] = page

    if skipped_by_filter > 0:
        print(f" Filtered out {skipped_by_filter} pages matching your exclusion patterns.")

    if force_full:
        print(f"\n[!] Bypassing incremental cache. Forcing a full dump of all pages to: {output_dir}")
    else:
        print(f"\nStarting intelligent incremental Markdown conversion to: {output_dir}")

    os.makedirs(f"{output_dir}/en", exist_ok=True)
    os.makedirs(f"{output_dir}/fr", exist_ok=True)

    stats = {"downloaded": 0, "skipped": 0, "failed": 0}

    for base_title, variants in pages_by_base.items():
        has_en = 'en' in variants
        has_fr = 'fr' in variants
        has_default = 'default' in variants

        if has_en or has_fr:
            if has_en:
                process_page(variants['en'], 'en', base_title, output_dir, stats, force_full)
            if has_fr:
                process_page(variants['fr'], 'fr', base_title, output_dir, stats, force_full)
        elif has_default:
            process_page(variants['default'], 'en', base_title, output_dir, stats, force_full)

    print(f"\nDump finished! New/Updated: {stats['downloaded']} | Skipped (up-to-date): {stats['skipped']} | Failed: {stats['failed']}")

def process_page(page_obj, lang, base_title, output_dir, stats, force_full):
    """Checks metadata first, skips if unchanged, otherwise downloads, cleans, and converts."""
    try:
        safe_title = sanitize_filename(base_title)
        file_path = os.path.join(output_dir, lang, f"{safe_title}.md")
        meta_path = f"{file_path}.meta"

        live_revid = page_obj.revision

        if not force_full and os.path.exists(file_path) and os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    cached_meta = json.load(f)

                if cached_meta.get("revid") == live_revid:
                    print(f"[{lang.upper()}] Skipped (No changes): {base_title}")
                    stats["skipped"] += 1
                    return
            except Exception:
                pass

        print(f"[{lang.upper()}] Downloading & converting: {base_title}")
        wikitext = page_obj.text()

        if not wikitext.strip():
            return

        markdown_content = mediawiki_to_markdown(wikitext)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# {base_title}\n\n")
            f.write(markdown_content)

        meta_data = {
            "title": page_obj.name,
            "revid": live_revid,
            "lang": lang
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, indent=2)

        stats["downloaded"] += 1

    except Exception as e:
        print(f"Error processing page '{page_obj.name}': {e}")
        stats["failed"] += 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dump any MediaWiki content instance into clean Markdown files.")

    # Required Site Configuration Arguments (No defaults)
    parser.add_argument(
        '-s', '--site',
        type=str,
        required=True,
        help='REQUIRED: The core domain of the MediaWiki server (e.g., wiki.example.org).'
    )
    parser.add_argument(
        '-p', '--path',
        type=str,
        required=True,
        help='REQUIRED: The sub-path portion of the wiki API endpoint (e.g., /w/ or /wiki_api/).'
    )

    parser.add_argument(
        '-o', '--output-dir',
        type=str,
        default='wiki_markdown_dump',
        help='The root directory where the "en" and "fr" subfolders should be created (default: wiki_markdown_dump).'
    )

    parser.add_argument(
        '--force-full',
        action='store_true',
        help='Bypass the cache check and force a complete download/conversion of all pages.'
    )

    parser.add_argument(
        '-x', '--exclude',
        action='append',
        default=[],
        help='Regex pattern to exclude pages.'
    )

    parser.add_argument(
        '--exclude-file',
        type=str,
        help='Path to a text file containing regex exclusion patterns, one per line.'
    )

    args = parser.parse_args()

    patterns = args.exclude
    if args.exclude_file and os.path.exists(args.exclude_file):
        with open(args.exclude_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    patterns.append(line)

    dump_wiki_to_markdown_incremental(
        site_url=args.site,
        site_path=args.path,
        output_dir=args.output_dir,
        force_full=args.force_full,
        exclude_patterns=patterns
    )

