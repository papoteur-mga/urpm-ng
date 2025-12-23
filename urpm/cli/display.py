"""Display utilities for urpm CLI.

Provides flexible package list display with multiple output modes:
- columns: Multi-column layout (default, human-friendly)
- flat: One item per line (parsable by scripts)
- json: JSON output (programmatic consumption)
"""

import json
import shutil
from enum import Enum
from typing import List, Optional, Callable, Any, Dict


class DisplayMode(Enum):
    """Output display mode."""
    COLUMNS = "columns"  # Multi-column, human-friendly (default)
    FLAT = "flat"        # One per line, parsable
    JSON = "json"        # JSON output


# Global display settings
_display_mode = DisplayMode.COLUMNS
_show_all = False


def init(mode: str = "columns", show_all: bool = False):
    """Initialize display settings.

    Args:
        mode: Display mode ("columns", "flat", "json")
        show_all: If True, never truncate output
    """
    global _display_mode, _show_all
    _display_mode = DisplayMode(mode) if mode else DisplayMode.COLUMNS
    _show_all = show_all


def get_mode() -> DisplayMode:
    """Get current display mode."""
    return _display_mode


def get_show_all() -> bool:
    """Get current show_all setting."""
    return _show_all


def get_terminal_width() -> int:
    """Get terminal width, with fallback to 80 columns."""
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


def format_package_list(
    packages: List[str],
    max_lines: int = 10,
    show_all: Optional[bool] = None,
    indent: int = 2,
    column_gap: int = 2,
    color_func: Optional[Callable[[str], str]] = None,
    mode: Optional[DisplayMode] = None,
    terminal_width: Optional[int] = None
) -> List[str]:
    """Format a list of packages according to display mode.

    Args:
        packages: List of package names to display
        max_lines: Maximum lines before truncation (default: 10, columns mode only)
        show_all: Override global show_all setting
        indent: Spaces to indent (default: 2, columns mode only)
        column_gap: Gap between columns (default: 2, columns mode only)
        color_func: Optional colorize function (columns mode only)
        mode: Override global display mode
        terminal_width: Override terminal width (for testing)

    Returns:
        List of formatted lines ready to print
    """
    if not packages:
        return []

    # Use global settings if not overridden
    effective_mode = mode if mode is not None else _display_mode
    effective_show_all = show_all if show_all is not None else _show_all

    if effective_mode == DisplayMode.JSON:
        return [json.dumps(packages, ensure_ascii=False)]

    if effective_mode == DisplayMode.FLAT:
        return list(packages)

    # COLUMNS mode (default)
    return _format_columns(
        packages,
        max_lines=max_lines,
        show_all=effective_show_all,
        indent=indent,
        column_gap=column_gap,
        color_func=color_func,
        terminal_width=terminal_width
    )


def _format_columns(
    packages: List[str],
    max_lines: int,
    show_all: bool,
    indent: int,
    column_gap: int,
    color_func: Optional[Callable[[str], str]],
    terminal_width: Optional[int]
) -> List[str]:
    """Format packages in multi-column layout."""
    # Get terminal width
    width = terminal_width or get_terminal_width()
    usable_width = width - indent

    # Find longest package name
    max_pkg_len = max(len(p) for p in packages)

    # Calculate column width and number of columns
    col_width = max_pkg_len + column_gap
    num_cols = max(1, usable_width // col_width)

    # Calculate how many lines we need for all packages
    total_packages = len(packages)
    total_lines_needed = (total_packages + num_cols - 1) // num_cols

    # Determine how many lines to actually display
    if show_all:
        lines_to_show = total_lines_needed
        hidden_count = 0
    else:
        lines_to_show = min(max_lines, total_lines_needed)
        # Calculate how many packages we can show
        packages_shown = lines_to_show * num_cols
        hidden_count = max(0, total_packages - packages_shown)

    # Build output lines
    result = []
    prefix = " " * indent

    for line_idx in range(lines_to_show):
        cols = []
        for col_idx in range(num_cols):
            pkg_idx = line_idx * num_cols + col_idx
            if pkg_idx < total_packages:
                pkg = packages[pkg_idx]
                # Apply color if provided
                if color_func:
                    display_pkg = color_func(pkg)
                    # Pad based on raw length, not colored length
                    padding = " " * (col_width - len(pkg))
                    cols.append(display_pkg + padding)
                else:
                    cols.append(pkg.ljust(col_width))
        if cols:
            result.append(prefix + "".join(cols).rstrip())

    # Add "and X more" message if truncated
    if hidden_count > 0:
        result.append(prefix + f"... and {hidden_count} more")

    return result


def print_package_list(
    packages: List[str],
    max_lines: int = 10,
    show_all: Optional[bool] = None,
    indent: int = 2,
    column_gap: int = 2,
    color_func: Optional[Callable[[str], str]] = None,
    mode: Optional[DisplayMode] = None
) -> None:
    """Print a list of packages according to display mode.

    Args:
        packages: List of package names to display
        max_lines: Maximum lines before truncation (default: 10)
        show_all: Override global show_all setting
        indent: Spaces to indent (default: 2)
        column_gap: Gap between columns (default: 2)
        color_func: Optional colorize function (columns mode only)
        mode: Override global display mode
    """
    lines = format_package_list(
        packages,
        max_lines=max_lines,
        show_all=show_all,
        indent=indent,
        column_gap=column_gap,
        color_func=color_func,
        mode=mode
    )
    for line in lines:
        print(line)


def format_inline(
    packages: List[str],
    max_count: int = 5,
    show_all: Optional[bool] = None,
    separator: str = ", ",
    color_func: Optional[Callable[[str], str]] = None,
    mode: Optional[DisplayMode] = None
) -> str:
    """Format packages as inline list (for summaries, history, etc.).

    Args:
        packages: List of package names
        max_count: Max packages before truncation (columns mode)
        show_all: Override global show_all setting
        separator: Separator between packages
        color_func: Optional colorize function
        mode: Override global display mode

    Returns:
        Formatted string like "pkg1, pkg2, pkg3 (+5 more)"
    """
    if not packages:
        return ""

    effective_mode = mode if mode is not None else _display_mode
    effective_show_all = show_all if show_all is not None else _show_all

    if effective_mode == DisplayMode.JSON:
        return json.dumps(packages, ensure_ascii=False)

    if effective_mode == DisplayMode.FLAT:
        return "\n".join(packages)

    # COLUMNS mode - inline comma-separated
    total = len(packages)

    if effective_show_all or total <= max_count:
        display_pkgs = packages
        suffix = ""
    else:
        display_pkgs = packages[:max_count]
        hidden = total - max_count
        suffix = f" (+{hidden} more)"

    if color_func:
        formatted = separator.join(color_func(p) for p in display_pkgs)
    else:
        formatted = separator.join(display_pkgs)

    return formatted + suffix


def format_dict_as_json(data: Dict[str, Any]) -> str:
    """Format a dictionary as JSON (for --json mode complex output)."""
    return json.dumps(data, ensure_ascii=False, indent=2)


def print_json(data: Any) -> None:
    """Print data as JSON."""
    print(json.dumps(data, ensure_ascii=False, indent=2))
