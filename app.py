"""Streamlit web UI.  Run locally with:  streamlit run app.py"""

import shutil
import tempfile
from pathlib import Path
from typing import List

import streamlit as st

from cocos_fetch.archive import make_zip_bytes, safe_extract_zip
from cocos_fetch.bundles import FetchOptions, download_bundle_roots, process_root_dir
from cocos_fetch.settings_parser import parse_settings_js

st.set_page_config(page_title="Cocos Bundle Fetcher", layout="wide")
st.title("Cocos Bundle Fetcher")
st.caption("Study tool for Cocos Creator remote Asset Bundles. "
           "Only use it on resources you are authorized to access.")


def workspace() -> Path:
    if "workspace" not in st.session_state:
        st.session_state.workspace = tempfile.mkdtemp(prefix="cocos_fetch_")
    return Path(st.session_state.workspace)


def reset_workspace() -> None:
    shutil.rmtree(st.session_state.get("workspace", ""), ignore_errors=True)
    st.session_state.pop("workspace", None)


ws = workspace()

with st.sidebar:
    st.subheader("Workspace")
    st.code(str(ws), language="text")
    if st.button("Clear workspace"):
        reset_workspace()
        st.rerun()

    st.subheader("Settings")
    server_input = st.text_input("Asset server URL", value=st.session_state.get("server", ""),
                                 placeholder="https://example.com")
    st.session_state.server = server_input.rstrip("/")
    opts = FetchOptions(
        skip_existing=st.checkbox("Skip existing non-empty files", value=True),
        check_complete_first=st.checkbox("Check bundle completeness first", value=True),
    )

MODES = [
    "1. settings.js → bundle roots (config / index)",
    "2. ZIP of bundle configs → import / native assets",
    "3. One click: settings.js → roots → assets",
    "4. Local folder (only when running locally)",
]
mode = st.radio("Mode", MODES)

logs: List[str] = []
log_box = st.empty()


def ui_log(msg: str) -> None:
    logs.append(msg)
    log_box.code("\n".join(logs[-160:]), language="text")  # tail only, keeps the page responsive


def upload_settings():
    f = st.file_uploader("settings.js", type=["js", "txt"])
    if not f:
        return None
    try:
        s = parse_settings_js(f.read().decode("utf-8", errors="ignore"))
    except ValueError as e:
        st.error(str(e))
        st.stop()
    st.session_state.server = s.server
    st.success(f"Parsed: server = {s.server}, remote bundles = {len(s.remote_bundles)}")
    with st.expander("Parsed bundles"):
        st.json({"server": s.server, "remoteBundles": s.remote_bundles, "bundleVers": s.bundle_vers})
    return s


def require_server() -> str:
    if not st.session_state.server:
        st.error("Set the asset server URL in the sidebar first.")
        st.stop()
    return st.session_state.server


if mode == MODES[0]:
    s = upload_settings()
    out_dir = ws / "bundle_roots"
    if s and st.button("Download bundle roots"):
        summary = download_bundle_roots(s.server, s.remote_bundles, s.bundle_vers, out_dir, ui_log)
        st.success("Done")
        st.dataframe(summary, use_container_width=True)
        st.download_button("Download ZIP", make_zip_bytes(out_dir), file_name="bundle_roots.zip")

elif mode == MODES[1]:
    st.write("Upload a ZIP containing bundle folders with `config.*.json` (e.g. the output of mode 1).")
    zip_file = st.file_uploader("ZIP", type=["zip"])
    root_dir = ws / "uploaded_roots"
    if zip_file and st.button("Extract and fetch assets"):
        server = require_server()
        shutil.rmtree(root_dir, ignore_errors=True)
        try:
            safe_extract_zip(zip_file, root_dir)
        except ValueError as e:
            st.error(str(e))
            st.stop()
        results, _ = process_root_dir(server, root_dir, opts, ui_log)
        st.success("Done")
        st.dataframe(results, use_container_width=True)
        st.download_button("Download ZIP", make_zip_bytes(root_dir), file_name="assets.zip")

elif mode == MODES[2]:
    s = upload_settings()
    out_dir = ws / "one_click_output"
    if s and st.button("Run all"):
        shutil.rmtree(out_dir, ignore_errors=True)
        ui_log("Step 1: bundle roots")
        download_bundle_roots(s.server, s.remote_bundles, s.bundle_vers, out_dir, ui_log)
        ui_log("\nStep 2: import / native assets")
        results, _ = process_root_dir(s.server, out_dir, opts, ui_log)
        st.success("Done")
        st.dataframe(results, use_container_width=True)
        st.download_button("Download ZIP", make_zip_bytes(out_dir), file_name="assets.zip")

else:
    st.warning("This mode reads a folder on the machine running Streamlit, "
               "so it only makes sense when you run the app locally.")
    local_root = st.text_input("Folder containing bundle configs", placeholder="/path/to/bundle_roots")
    if st.button("Process folder"):
        server = require_server()
        root = Path(local_root).expanduser()
        if not root.is_dir():
            st.error(f"Folder not found: {root}")
            st.stop()
        results, report_path = process_root_dir(server, root, opts, ui_log)
        st.success("Done")
        st.dataframe(results, use_container_width=True)
        st.info(f"Report: {report_path}")
