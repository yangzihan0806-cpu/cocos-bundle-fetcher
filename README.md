# Cocos Bundle Fetcher

A small tool for studying how games built with **Cocos Creator** deliver their
assets at runtime. Given a build's `settings.js`, it reconstructs the remote
Asset Bundle layout, decodes the engine's compressed asset UUIDs, and downloads
each bundle's manifest, serialized asset data and raw files. It ships with a
command-line interface and a Streamlit web UI.

> **Educational use only.** Only use this on builds and servers you are
> authorized to access. This repository contains no game data, server
> addresses or downloaded assets.

## How Cocos Creator remote bundles are laid out

A Cocos Creator build lists its remote bundles in `settings.js`:

```js
server: "https://cdn.example.com/game/",
remoteBundles: ["main", "ui", ...],
bundleVers: { main: "a1b2c", ui: "d3e4f", ... },
```

Each bundle on the server looks like:

```
remote/{bundle}/config.{ver}.json          bundle manifest (UUIDs, paths, versions)
remote/{bundle}/index.{ver}.js             bundle scripts
remote/{bundle}/import/{uu}/{uuid}.{ver}.json   serialized asset data
remote/{bundle}/native/{uu}/{uuid}.{ver}{ext}   raw files: png, mp3, ttf, ...
```

`{uu}` is the first two characters of the asset UUID, and the version hash in
each file name gives cache busting and incremental updates.

Two details make this non-trivial:

1. **Compressed UUIDs.** Manifests store 128-bit UUIDs as 22 characters:
   2 hex digits kept as-is + 20 base64 characters. Each pair of base64
   characters (2 × 6 = 12 bits) expands to exactly 3 hex digits (3 × 4 bits),
   so 2 + 10 × 3 = 32 hex digits. See [`cocos_fetch/uuid_codec.py`](cocos_fetch/uuid_codec.py).

   ```
   fcmR3XADNLgJ1ByKhqcC5Z  ->  fc991dd7-0033-4b80-9d41-c8a86a702e59
   ```

2. **Unknown native extensions.** The manifest records a native file's UUID and
   version but not its extension, so the fetcher probes a candidate list
   (23 common types). `--ext-hint` narrows the list per bundle. Fonts use a
   folder layout (`{uuid}.{ver}/{FontName}.ttf`), which is handled separately.

Import keys that are not integers are **pack IDs**: several small JSON assets
merged into one file at build time. They are downloaded verbatim.

## Usage

```bash
pip install -r requirements.txt

# 1. bundle manifests from settings.js (also saves the server in _meta.json)
python -m cocos_fetch roots --settings settings.js --out output/

# 2. import/native assets for every manifest under output/
python -m cocos_fetch assets --root output/ --ext-hint sounds=.mp3

# or both steps at once
python -m cocos_fetch all --settings settings.js --out output/

# decode / encode a UUID
python -m cocos_fetch uuid fcmR3XADNLgJ1ByKhqcC5Z
```

Web UI:

```bash
streamlit run app.py
```

## Reliability

- Per-request timeouts (longer for audio) and retries with capped backoff
- Idempotent reruns: existing non-empty files are skipped, so an interrupted run
  can just be restarted
- Optional completeness pre-check skips bundles that are already fully downloaded
- `_download_report.txt` logs every request as `OK` / `SKIP` / `MISS`
- ZIP uploads in the web UI are checked for path traversal ("Zip Slip")

## Tests

```bash
pip install pytest
pytest
```

## Possible improvements

- Read asset types from the `import` JSON to request each native file's exact
  extension instead of probing (fewer requests per asset)
- Concurrent downloads with a rate limit (the work is I/O-bound)
- Diff two downloaded versions to list added / changed assets

## License

MIT
