"""Download Cocos Creator remote Asset Bundles.

Remote bundle layout on the asset server::

    {server}/remote/{bundle}/config.{ver}.json   <- bundle manifest
    {server}/remote/{bundle}/index.{ver}.js      <- bundle scripts
    {server}/remote/{bundle}/import/{uu}/{uuid}.{ver}.json    <- serialized asset data
    {server}/remote/{bundle}/native/{uu}/{uuid}.{ver}{ext}    <- raw files (png, mp3, ...)

where ``{uu}`` is the first two characters of the (decoded) UUID.

The manifest lists every asset's UUID and version but not the file
extension of native files, so native URLs are found by probing a list
of candidate extensions.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .net import download_if_needed, file_ok
from .uuid_codec import decode_uuid

Log = Callable[[str], None]

DEFAULT_NATIVE_EXTS = [
    ".png", ".jpg", ".jpeg", ".webp", ".psd",
    ".mp3", ".ogg", ".wav", ".m4a",
    ".ttf", ".ttc", ".otf", ".fnt",
    ".plist", ".atlas",
    ".json", ".skel", ".bytes", ".bin", ".txt",
    ".pvr", ".pkm", ".astc",
]

# TTF-style fonts are stored in a folder named after the UUID, keeping the
# original file name: native/{uu}/{uuid}.{ver}/{FontName}.ttf
FONT_EXTS = {".ttf", ".ttc", ".otf"}
AUDIO_EXTS = {".mp3", ".ogg", ".wav", ".m4a"}


@dataclass
class FetchOptions:
    timeout: float = 60
    retries: int = 3
    audio_timeout: float = 120
    audio_retries: int = 5
    skip_existing: bool = True
    check_complete_first: bool = True
    # Optional per-bundle extension hints. Restricting the candidate list for
    # bundles whose content type is known cuts the number of probe requests.
    # Example: {"sounds": [".mp3"], "icons": [".png", ".jpg"]}
    ext_hints: Dict[str, List[str]] = field(default_factory=dict)

    def exts_for(self, bundle_name: str) -> List[str]:
        return self.ext_hints.get(bundle_name, DEFAULT_NATIVE_EXTS)


def _noop(_: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Step 1: bundle roots (config + index) from settings.js
# ---------------------------------------------------------------------------

def download_bundle_roots(
    server: str,
    remote_bundles: Iterable[str],
    bundle_vers: Dict[str, str],
    out_dir: Path,
    log: Log = _noop,
) -> List[dict]:
    """Download ``config`` and ``index`` for every remote bundle.

    Versioned file names are tried first, then unversioned ones.
    Writes ``_summary.json`` and ``_meta.json`` (records the server so the
    asset step can run later without re-entering it).
    """
    server = server.rstrip("/")
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []

    for bundle in remote_bundles:
        ver = bundle_vers.get(bundle, "")
        bundle_dir = out_dir / bundle
        root = f"{server}/remote/{bundle}"

        candidates = []
        if ver:
            candidates += [
                (f"{root}/config.{ver}.json", bundle_dir / f"config.{ver}.json"),
                (f"{root}/index.{ver}.js", bundle_dir / f"index.{ver}.js"),
            ]
        candidates += [
            (f"{root}/config.json", bundle_dir / "config.json"),
            (f"{root}/index.js", bundle_dir / "index.js"),
        ]

        ok_count = 0
        for url, path in candidates:
            status, size, err = download_if_needed(url, path, timeout=20, retries=1)
            if status in ("OK", "SKIP"):
                ok_count += 1
                log(f"OK   {url}  ({size} bytes)")
            else:
                log(f"FAIL {url} | {err}")

        summary.append({"bundle": bundle, "version": ver, "downloaded_files": ok_count})

    (out_dir / "_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "_meta.json").write_text(json.dumps({"server": server}, indent=2), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Step 2: import / native assets from each bundle's config
# ---------------------------------------------------------------------------

def pair_dict(arr: list) -> dict:
    """Manifests store maps as flat [key1, val1, key2, val2, ...] arrays."""
    return {arr[i]: arr[i + 1] for i in range(0, len(arr) - 1, 2)}


@dataclass
class BundleManifest:
    name: str
    import_base: str
    native_base: str
    uuids: List[str]
    paths: dict
    import_versions: dict
    native_versions: dict

    @classmethod
    def load(cls, config_path: Path) -> "BundleManifest":
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        versions = cfg.get("versions", {})
        return cls(
            name=cfg.get("name", config_path.parent.name),
            import_base=cfg.get("importBase", "import"),
            native_base=cfg.get("nativeBase", "native"),
            uuids=cfg.get("uuids", []),
            paths=cfg.get("paths", {}),
            import_versions=pair_dict(versions.get("import", [])),
            native_versions=pair_dict(versions.get("native", [])),
        )

    def import_name(self, key) -> str:
        # Integer keys index into `uuids`; string keys are pack IDs
        # (several JSON assets merged into one file), used verbatim.
        return decode_uuid(self.uuids[key]) if isinstance(key, int) else str(key)

    def native_entry(self, key) -> Tuple[str, str]:
        idx = int(key) if isinstance(key, str) and key.isdigit() else key
        real_uuid = decode_uuid(self.uuids[idx])
        asset_name = self.paths[str(idx)][0] if str(idx) in self.paths else f"asset_{idx}"
        return real_uuid, asset_name


def import_rel_path(m: BundleManifest, name: str, ver: str) -> Path:
    return Path(m.import_base) / name[:2] / f"{name}.{ver}.json"


def native_candidates(m: BundleManifest, real_uuid: str, ver: str,
                      asset_name: str, ext: str) -> List[Path]:
    """Relative paths where a native file may live, most likely first."""
    sub = Path(m.native_base) / real_uuid[:2]
    flat = [sub / f"{real_uuid}.{ver}{ext}", sub / f"{real_uuid}{ext}"]
    if ext in FONT_EXTS:
        base = Path(asset_name).name
        return [sub / f"{real_uuid}.{ver}" / f"{base}{ext}", sub / real_uuid / f"{base}{ext}"] + flat
    return flat


def bundle_is_complete(bundle_dir: Path, m: BundleManifest, opts: FetchOptions) -> Tuple[bool, str]:
    for key, ver in m.import_versions.items():
        rel = import_rel_path(m, m.import_name(key), ver)
        if not file_ok(bundle_dir / rel):
            return False, f"missing import: {rel}"

    for key, ver in m.native_versions.items():
        real_uuid, asset_name = m.native_entry(key)
        if not any(
            file_ok(bundle_dir / rel)
            for ext in opts.exts_for(m.name)
            for rel in native_candidates(m, real_uuid, ver, asset_name, ext)
        ):
            return False, f"missing native: {asset_name} -> {real_uuid}.{ver}"
    return True, "complete"


def process_bundle(
    server: str,
    config_path: Path,
    report: List[str],
    opts: FetchOptions,
    log: Log = _noop,
) -> dict:
    bundle_dir = config_path.parent
    try:
        m = BundleManifest.load(config_path)
    except Exception as e:
        msg = f"[BAD_CONFIG] {config_path} | {e}"
        log(msg)
        report.append(msg)
        return {"bundle": bundle_dir.name, "status": "BAD_CONFIG"}

    remote = f"{server}/remote/{m.name}"
    log(f"\n===== bundle: {m.name} =====")
    report += [f"\n===== {m.name} =====", f"[CONFIG]\t{config_path.name}"]

    if opts.check_complete_first:
        complete, reason = bundle_is_complete(bundle_dir, m, opts)
        if complete:
            log(f"[SKIP_COMPLETE] {m.name}")
            report.append(f"[SKIP_COMPLETE]\t{m.name}\t{reason}")
            return {"bundle": m.name, "status": "SKIP_COMPLETE"}
        log(f"[INCOMPLETE] {m.name} | {reason}")
        report.append(f"[INCOMPLETE]\t{m.name}\t{reason}")

    # --- import (serialized JSON) ---
    import_ok = 0
    n_import = len(m.import_versions)
    for i, (key, ver) in enumerate(m.import_versions.items(), 1):
        rel = import_rel_path(m, m.import_name(key), ver)
        url = f"{remote}/{rel.as_posix()}"
        status, size, err = download_if_needed(
            url, bundle_dir / rel, opts.timeout, opts.retries, opts.skip_existing)
        import_ok += status in ("OK", "SKIP")
        if i % 20 == 0 or status == "MISS":
            log(f"[IMPORT] {m.name}: {i}/{n_import}  {status}  {rel.name}")
        report.append(f"[IMPORT_{status}]\t{rel.name}\t{size}\t{url}\t{err}")

    # --- native (raw files; extension unknown, so probe candidates) ---
    native_ok = 0
    n_native = len(m.native_versions)
    for i, (key, ver) in enumerate(m.native_versions.items(), 1):
        real_uuid, asset_name = m.native_entry(key)
        hit: Optional[Path] = None
        for ext in opts.exts_for(m.name):
            is_audio = ext in AUDIO_EXTS
            timeout = opts.audio_timeout if is_audio else opts.timeout
            retries = opts.audio_retries if is_audio else opts.retries
            for rel in native_candidates(m, real_uuid, ver, asset_name, ext):
                url = f"{remote}/{rel.as_posix()}"
                status, size, err = download_if_needed(
                    url, bundle_dir / rel, timeout, retries, opts.skip_existing)
                if status in ("OK", "SKIP"):
                    hit = rel
                    report.append(f"[NATIVE_{status}]\t{rel.as_posix()}\t{size}\t{url}\t{err}")
                    break
            if hit:
                break

        if hit:
            native_ok += 1
            if i % 20 == 0:
                log(f"[NATIVE] {m.name}: {i}/{n_native}  {hit.as_posix()}")
        else:
            log(f"[NATIVE_MISS] {m.name}: {i}/{n_native}  {asset_name}  {real_uuid}.{ver}")
            report.append(f"[NATIVE_MISS]\t{asset_name}\t{real_uuid}.{ver}\t(no known pattern hit)")

    log(f"[SUMMARY] {m.name}  IMPORT {import_ok}/{n_import}  NATIVE {native_ok}/{n_native}")
    report.append(f"[SUMMARY]\t{m.name}\tIMPORT {import_ok}/{n_import}\tNATIVE {native_ok}/{n_native}")
    return {
        "bundle": m.name, "status": "DONE",
        "import_ok": import_ok, "import_total": n_import,
        "native_ok": native_ok, "native_total": n_native,
    }


def find_configs(root_dir: Path) -> List[Path]:
    seen, configs = set(), []
    for p in sorted(root_dir.rglob("config*.json")):
        if (p.name == "config.json" or p.name.startswith("config.")) and p not in seen:
            seen.add(p)
            configs.append(p)
    return configs


def process_root_dir(
    server: str,
    root_dir: Path,
    opts: Optional[FetchOptions] = None,
    log: Log = _noop,
) -> Tuple[List[dict], Path]:
    """Process every bundle config under ``root_dir``; writes ``_download_report.txt``."""
    opts = opts or FetchOptions()
    server = server.rstrip("/")
    configs = find_configs(root_dir)
    if not configs:
        raise ValueError(f"no config.*.json found under {root_dir}")

    log(f"Found {len(configs)} bundle config(s)")
    report = [f"ROOT_DIR = {root_dir}", f"FOUND_CONFIGS = {len(configs)}"]
    results = []
    for i, cfg in enumerate(configs, 1):
        log(f"\n########## [{i}/{len(configs)}] {cfg.parent.name} ##########")
        results.append(process_bundle(server, cfg, report, opts, log))

    report_path = root_dir / "_download_report.txt"
    report_path.write_text("\n".join(report), encoding="utf-8")
    log(f"\nDone. Report: {report_path}")
    return results, report_path


def read_saved_server(root_dir: Path) -> Optional[str]:
    meta = root_dir / "_meta.json"
    if meta.is_file():
        return json.loads(meta.read_text(encoding="utf-8")).get("server")
    return None
