"""Command-line interface.

    python -m cocos_fetch roots  --settings settings.js --out output/
    python -m cocos_fetch assets --root output/ [--server URL]
    python -m cocos_fetch all    --settings settings.js --out output/
    python -m cocos_fetch uuid   fcmR3XADNLgJ1ByKhqcC5Z
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List

from .bundles import FetchOptions, download_bundle_roots, process_root_dir, read_saved_server
from .settings_parser import parse_settings_js
from .uuid_codec import decode_uuid, encode_uuid


def _parse_ext_hints(items: List[str]) -> Dict[str, List[str]]:
    hints = {}
    for item in items or []:
        bundle, _, exts = item.partition("=")
        if not bundle or not exts:
            raise SystemExit(f"bad --ext-hint {item!r}; expected BUNDLE=.ext1,.ext2")
        hints[bundle] = [e if e.startswith(".") else "." + e for e in exts.split(",")]
    return hints


def _options(args) -> FetchOptions:
    return FetchOptions(
        timeout=args.timeout,
        retries=args.retries,
        skip_existing=not args.no_skip,
        check_complete_first=not args.no_check,
        ext_hints=_parse_ext_hints(args.ext_hint),
    )


def _add_asset_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--timeout", type=float, default=60, help="per-request timeout in seconds")
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--no-skip", action="store_true", help="re-download files that already exist")
    p.add_argument("--no-check", action="store_true", help="skip the bundle-completeness pre-check")
    p.add_argument("--ext-hint", action="append", metavar="BUNDLE=.ext,...",
                   help="limit probed native extensions for a bundle, e.g. sounds=.mp3")


def cmd_roots(args) -> None:
    s = parse_settings_js(Path(args.settings).read_text(encoding="utf-8", errors="ignore"))
    server = args.server or s.server
    print(f"server = {server}, remote bundles = {len(s.remote_bundles)}")
    download_bundle_roots(server, s.remote_bundles, s.bundle_vers, Path(args.out), print)


def cmd_assets(args) -> None:
    root = Path(args.root)
    server = args.server or read_saved_server(root)
    if not server:
        raise SystemExit("no server known: pass --server or run 'roots' first (it saves _meta.json)")
    process_root_dir(server, root, _options(args), print)


def cmd_all(args) -> None:
    cmd_roots(args)
    args.root = args.out
    cmd_assets(args)


def cmd_uuid(args) -> None:
    for value in args.values:
        print(encode_uuid(value) if "-" in value else decode_uuid(value))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="cocos_fetch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("roots", help="download each bundle's config/index from settings.js")
    p.add_argument("--settings", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--server", help="override the server found in settings.js")
    p.set_defaults(func=cmd_roots)

    p = sub.add_parser("assets", help="download import/native assets for configs under --root")
    p.add_argument("--root", required=True)
    p.add_argument("--server", help="defaults to the server saved by 'roots'")
    _add_asset_flags(p)
    p.set_defaults(func=cmd_assets)

    p = sub.add_parser("all", help="roots + assets in one go")
    p.add_argument("--settings", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--server", help="override the server found in settings.js")
    _add_asset_flags(p)
    p.set_defaults(func=cmd_all)

    p = sub.add_parser("uuid", help="decode a compressed UUID (or encode a standard one)")
    p.add_argument("values", nargs="+")
    p.set_defaults(func=cmd_uuid)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
