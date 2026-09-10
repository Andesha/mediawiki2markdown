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

def html_to_markdown(html):
    """Converts MediaWiki-rendered HTML to GitHub-Flavored Markdown."""
    try:
        return pypandoc.convert_text(
            html,
            'gfm',
            format='html-native_divs-native_spans',
        )
    except Exception as e:
        print(f" Pandoc conversion failed, saving rendered HTML fallback. Error: {e}")
        return html


def get_rendered_html(site, page_name):
    """Asks MediaWiki to render a page, including templates and extension tags."""
    response = site.api(
        'parse',
        page=page_name,
        prop='text',
        disableeditsection=True,
        disabletoc=True,
        formatversion=2,
    )
    return response['parse']['text']

def convert_internal_links(markdown_content, available_base_titles):
    """Rewrites MediaWiki style [[Links]] into relative local Markdown links if the target exists."""
    def replace_link(match):
        target = match.group(1).strip()
        display_text = match.group(2).strip() if match.group(2) else target

        if target.endswith('/en') or target.endswith('/fr'):
            base_target = target[:-3]
        else:
            base_target = target

        if base_target in available_base_titles:
            safe_file = sanitize_filename(base_target)
            return f"[{display_text}](./{safe_file}.md)"

        return display_text

    pattern = r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]'
    return re.sub(pattern, replace_link, markdown_content)

def should_exclude(page_name, exclude_patterns):
    """Checks if a page name matches any of the compiled regex exclusion patterns."""
    for pattern in exclude_patterns:
        if pattern.search(page_name):
            return True
    return False

def purge_deleted_local_files(output_dir, expected_files_by_lang):
    """Scans the local output directories and deletes files that no longer exist on the live wiki."""
    print("\nReconciling local workspace against live wiki to clean deleted pages...")
    purged_count = 0

    for lang in ["en", "fr"]:
        lang_dir = os.path.join(output_dir, lang)
        if not os.path.exists(lang_dir):
            continue

        valid_safe_names = expected_files_by_lang[lang]

        for filename in os.listdir(lang_dir):
            if filename == "index.md":
                continue

            if filename.endswith(".md"):
                base_name = filename[:-3]
            elif filename.endswith(".md.meta"):
                base_name = filename[:-8]
            else:
                continue

            if base_name not in valid_safe_names:
                target_path = os.path.join(lang_dir, filename)
                try:
                    os.remove(target_path)
                    purged_count += 1
                except Exception as e:
                    print(f" Failed to delete legacy file {target_path}: {e}")

    if purged_count > 0:
        print(f" Purged {purged_count} orphaned local files (.md and .meta) representing deleted wiki pages.")
    else:
        print(" Local directory completely in sync. No orphaned files found.")

def dump_wiki_to_markdown_incremental(site_url, site_path, output_dir, force_full=False, exclude_patterns=None, convert_links=False, generate_index=False, clean_deleted=False):
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
    exported_pages = {"en": [], "fr": []}
    expected_filenames_by_lang = {"en": set(), "fr": set()}

    for base_title, variants in pages_by_base.items():
        has_en = 'en' in variants
        has_fr = 'fr' in variants
        has_default = 'default' in variants
        safe_name = sanitize_filename(base_title)

        if has_en or has_fr:
            if has_en:
                display_title = process_page(site, variants['en'], 'en', base_title, output_dir, stats, force_full, convert_links, pages_by_base)
                exported_pages["en"].append((display_title, base_title))
                expected_filenames_by_lang["en"].add(safe_name)
            if has_fr:
                display_title = process_page(site, variants['fr'], 'fr', base_title, output_dir, stats, force_full, convert_links, pages_by_base)
                exported_pages["fr"].append((display_title, base_title))
                expected_filenames_by_lang["fr"].add(safe_name)
        elif has_default:
            display_title = process_page(site, variants['default'], 'en', base_title, output_dir, stats, force_full, convert_links, pages_by_base)
            exported_pages["en"].append((display_title, base_title))
            expected_filenames_by_lang["en"].add(safe_name)

    if generate_index:
        for lang in ["en", "fr"]:
            index_path = os.path.join(output_dir, lang, "index.md")
            print(f"Generating page directory index at: {index_path}")
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(f"# Documentation Index ({lang.upper()})\n\n")
                f.write("This is an automated structural index map of all available pages for this AI agent workspace.\n\n")
                for display_title, b_title in sorted(exported_pages[lang], key=lambda x: x):
                    safe_file = sanitize_filename(b_title)
                    f.write(f"* [{display_title}](./{safe_file}.md)\n")

    if clean_deleted:
        purge_deleted_local_files(output_dir, expected_filenames_by_lang)

    print(f"\nDump finished! New/Updated: {stats['downloaded']} | Skipped (up-to-date): {stats['skipped']} | Failed: {stats['failed']}")

def get_display_title(site, page_name, default_fallback):
    """Queries the MediaWiki API directly to fetch the real localized displaytitle metadata property."""
    try:
        res = site.api('query', prop='info', inprop='displaytitle', titles=page_name)
        pages = list(res.get('query', {}).get('pages', {}).values())
        if pages and 'displaytitle' in pages[0]:
            # Strip HTML tags like <i> if MediaWiki passes decorated title text strings
            return re.sub(r'<[^>]*>', '', pages[0]['displaytitle']).strip()
    except Exception:
        pass
    return default_fallback

def process_page(site, page_obj, lang, base_title, output_dir, stats, force_full, convert_links, all_valid_titles):
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
                    return cached_meta.get("displaytitle", base_title)
            except Exception:
                pass

        # Cache missed or outdated -> Fetch displaytitle from API only now
        display_title = get_display_title(site, page_obj.name, base_title)

        print(f"[{lang.upper()}] Downloading & converting: {base_title}")
        rendered_html = get_rendered_html(site, page_obj.name)

        if not rendered_html.strip():
            return base_title

        markdown_content = html_to_markdown(rendered_html)

        if convert_links:
            markdown_content = convert_internal_links(markdown_content, all_valid_titles)

        with open(file_path, "w", encoding="utf-8") as f:
            # Writes the API-retrieved translated display_title directly inside the content payload
            f.write(f"# {display_title}\n\n")
            f.write(markdown_content)

        meta_data = {
            "title": page_obj.name,
            "displaytitle": display_title,
            "revid": live_revid,
            "lang": lang
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, indent=2)

        stats["downloaded"] += 1
        return display_title

    except Exception as e:
        print(f"Error processing page '{page_obj.name}': {e}")
        stats["failed"] += 1
        return base_title

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dump any MediaWiki content instance into clean Markdown files.")

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
        '--convert-links',
        action='store_true',
        help='Convert MediaWiki [[Internal Links]] to relative Markdown link strings pointing to local files.'
    )
    parser.add_argument(
        '--generate-index',
        action='store_true',
        help='Generate an index.md table of contents within the language output subdirectories.'
    )
    parser.add_argument(
        '-x', '--exclude',
        action='append',
        default=[],
        help='Regex pattern to exclude pages.'
    )
    parser.add_argument(
        '--clean-deleted',
        action='store_true',
        help='Scan the local output directory and delete files belonging to pages that were removed from the live wiki.'
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
        exclude_patterns=patterns,
        convert_links=args.convert_links,
        generate_index=args.generate_index,
        clean_deleted=args.clean_deleted
    )

