"""Parse the build ``settings.js`` emitted by Cocos Creator."""

import re
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class BuildSettings:
    server: str
    remote_bundles: List[str]
    bundle_vers: Dict[str, str] = field(default_factory=dict)


def parse_settings_js(text: str) -> BuildSettings:
    """Extract the remote server, remote bundle list and bundle versions.

    ``settings.js`` is a JS object literal rather than strict JSON, so the
    fields are pulled out with targeted regular expressions.
    """
    m = re.search(r'server:\s*"([^"]+)"', text)
    if not m:
        raise ValueError("settings.js: 'server' field not found")
    server = m.group(1).rstrip("/")

    m = re.search(r'remoteBundles:\s*\[(.*?)\]\s*,\s*subpackages:', text, re.S)
    if not m:  # some builds have no 'subpackages' right after it
        m = re.search(r'remoteBundles:\s*\[(.*?)\]', text, re.S)
    if not m:
        raise ValueError("settings.js: 'remoteBundles' array not found")
    remote_bundles = re.findall(r'"([^"]+)"', m.group(1))

    m = re.search(r'bundleVers:\s*\{(.*?)\}\s*[,}]', text, re.S)
    if not m:
        raise ValueError("settings.js: 'bundleVers' object not found")
    bundle_vers = dict(re.findall(r'([A-Za-z0-9_]+)\s*:\s*"([^"]+)"', m.group(1)))

    return BuildSettings(server, remote_bundles, bundle_vers)
