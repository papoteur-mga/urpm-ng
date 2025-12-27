"""
RPM utilities for urpm.

Provides version comparison and other RPM-related functions.
"""

import re
from typing import Any, Dict, List, Tuple


def split_version(v: str) -> List[Tuple[int, Any]]:
    """Split version into comparable parts (numeric vs alpha).

    Returns tuples (type, value) where type=0 for int, 1 for str.
    This ensures consistent ordering: numbers < strings.

    Args:
        v: Version string (e.g., "1.2.3", "1.0rc1")

    Returns:
        List of (type, value) tuples for comparison
    """
    parts = re.findall(r'(\d+|[a-zA-Z]+)', v or '0')
    return [(0, int(p)) if p.isdigit() else (1, p) for p in parts]


def evr_key(pkg: Dict) -> Tuple:
    """Return a sortable key for epoch-version-release comparison.

    This implements a simplified rpmvercmp for comparing package versions.
    Can be used as a sort key or for direct comparison.

    Args:
        pkg: Package dict with 'epoch', 'version', 'release' keys

    Returns:
        Tuple suitable for comparison (higher = newer)

    Example:
        packages.sort(key=evr_key, reverse=True)  # newest first
        if evr_key(pkg1) > evr_key(pkg2): ...
    """
    epoch = pkg.get('epoch', 0) or 0
    return (epoch,
            split_version(pkg.get('version', '0')),
            split_version(pkg.get('release', '0')))


def filter_latest_versions(packages: List[Dict]) -> List[Dict]:
    """Filter a list of packages to keep only the latest version of each name.

    Args:
        packages: List of package dicts with 'name', 'epoch', 'version', 'release'

    Returns:
        List with only the latest version of each package name
    """
    latest_by_name = {}
    for pkg in packages:
        name = pkg.get('name')
        if not name:
            continue
        if name not in latest_by_name or evr_key(pkg) > evr_key(latest_by_name[name]):
            latest_by_name[name] = pkg
    return list(latest_by_name.values())
