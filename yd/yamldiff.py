#!/usr/bin/env python3
"""
YAML Diff Tool - A Python implementation of yamldiff with smart list sorting

This tool compares YAML files and shows structural differences with clarity.
Unlike yamldiff, this version intelligently sorts lists of dictionaries by common keys
(like 'name' for environment variables) to avoid false differences due to ordering.
"""

import argparse
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


class ChangeType(Enum):
    ADDED = "+"
    REMOVED = "-"
    MODIFIED = "~"


@dataclass
class DiffItem:
    change_type: ChangeType
    path: List[str]  # Now a list of path components
    old_value: Any = None
    new_value: Any = None

    def get_path_string(self) -> str:
        """Convert path list to string representation."""
        return ".".join(self.path)

    def format(self, use_color: bool = True) -> str:
        # For backward compatibility, convert path list to string if needed
        path_str = self.get_path_string() if isinstance(self.path, list) else self.path

        # Simple single-line format for basic usage
        symbol = self.change_type.value
        if self.change_type == ChangeType.MODIFIED:
            content = f"{symbol} {path_str}: {self.old_value} → {self.new_value}"
        elif self.change_type == ChangeType.ADDED:
            content = f"{symbol} {path_str}: {self.new_value}"
        else:  # REMOVED
            content = f"{symbol} {path_str}: {self.old_value}"

        if use_color:
            colors = {
                ChangeType.ADDED: "\033[32m",  # Green
                ChangeType.REMOVED: "\033[31m",  # Red
                ChangeType.MODIFIED: "\033[33m",  # Yellow
            }
            reset = "\033[0m"
            return f"{colors[self.change_type]}{content}{reset}"
        else:
            return content

    def _is_env_value_path(self, path: str) -> bool:
        """Check if this is an env variable path (either value or dict)."""
        return ".env[" in path

    def _format_env_change(self, use_color: bool = True) -> str:
        """Format env variable changes in the desired YAML-like structure."""
        # Extract env name from path
        env_start = self.path.find(".env[")
        if env_start == -1:
            return self.format(use_color)  # Fallback

        env_part = self.path[env_start + 5 :]  # Skip '.env['
        bracket_end = env_part.find("]")
        if bracket_end == -1:
            return self.format(use_color)  # Fallback

        env_name = env_part[:bracket_end]

        # Build the hierarchy up to env
        hierarchy_path = self.path[: env_start + 4]  # Include '.env'
        hierarchy_parts = self._parse_path_into_yaml_structure(hierarchy_path)

        lines = []
        for i, (indent, key, is_leaf, is_list_item) in enumerate(hierarchy_parts):
            prefix = "  " * indent
            if is_list_item:
                lines.append(f"{prefix}- {key}:")
            else:
                lines.append(f"{prefix}{key}:")

        # Add the env variable change
        indent = len(hierarchy_parts) * 2
        prefix = "  " * indent

        symbol = self.change_type.value

        # Extract the actual value from env dict if needed
        def get_env_value(value):
            if isinstance(value, dict) and "value" in value:
                return value["value"]
            return value

        if self.change_type == ChangeType.MODIFIED:
            old_val = get_env_value(self.old_value)
            new_val = get_env_value(self.new_value)
            value_str = f"{old_val} → {new_val}"
        elif self.change_type == ChangeType.ADDED:
            value_str = get_env_value(self.new_value)
        else:  # REMOVED
            value_str = get_env_value(self.old_value)

        change_line = f"{prefix}{symbol} - {env_name}: {value_str}"

        if use_color:
            colors = {
                ChangeType.ADDED: "\033[32m",  # Green
                ChangeType.REMOVED: "\033[31m",  # Red
                ChangeType.MODIFIED: "\033[33m",  # Yellow
            }
            reset = "\033[0m"
            change_line = f"{colors[self.change_type]}{change_line}{reset}"

        lines.append(change_line)

        return "\n".join(lines)

    def _parse_path_into_yaml_structure(
        self, path: str
    ) -> List[Tuple[int, str, bool, bool]]:
        """Parse path into (indent_level, key, is_leaf, is_list_item) tuples."""
        result = []

        # Split by dots first
        parts = path.split(".")

        current_indent = 0

        for i, part in enumerate(parts):
            is_leaf = i == len(parts) - 1
            is_list_item = False

            # Check if this part contains brackets
            if "[" in part and "]" in part:
                bracket_start = part.find("[")
                bracket_end = part.find("]")
                if bracket_start != -1 and bracket_end != -1:
                    key = part[:bracket_start]
                    list_key = part[bracket_start + 1 : bracket_end]

                    # Add the parent key
                    if key:
                        result.append((current_indent, key, False, False))
                        current_indent += 1

                    # Add the list item
                    is_list_item = True
                    part = list_key

            result.append((current_indent, part, is_leaf, is_list_item))

            if not is_leaf and not is_list_item:
                current_indent += 1

        return result


class YAMLDiff:
    def __init__(self):
        self.differences: List[DiffItem] = []
        self.path_stack: List[str] = []  # Track current path during comparison

    def compare(self, left: Any, right: Any, path: List[str] = None) -> None:
        """Recursively compare two data structures."""
        if path is None:
            path = []

        # Normalize both sides
        left_norm = self.normalize_data(left, ".".join(path))
        right_norm = self.normalize_data(right, ".".join(path))

        if type(left_norm) != type(right_norm):
            self.differences.append(
                DiffItem(ChangeType.MODIFIED, path, left_norm, right_norm)
            )
            return

        if isinstance(left_norm, dict):
            self._compare_dicts(left_norm, right_norm, path)
        elif isinstance(left_norm, list):
            self._compare_lists(left_norm, right_norm, path)
        else:
            if left_norm != right_norm:
                self.differences.append(
                    DiffItem(ChangeType.MODIFIED, path, left_norm, right_norm)
                )

    def format_as_tree(self, use_color: bool = True) -> List[str]:
        """Format all differences as a grouped tree structure."""
        if not self.differences:
            return []

        # Group differences by their path prefix
        grouped = self._group_differences_by_path()

        # Generate output lines from grouped differences
        lines = []
        self._grouped_diffs_to_lines(grouped, lines, use_color)
        return lines

    def _group_differences_by_path(self) -> Dict[str, List[DiffItem]]:
        """Group differences by their common path prefixes."""
        grouped = {}

        for diff in self.differences:
            # Find the best grouping level - we want to group by container or similar high-level entity
            group_key = self._find_group_key(diff.path)

            if group_key not in grouped:
                grouped[group_key] = []
            grouped[group_key].append(diff)

        return grouped

    def _find_group_key(self, path: List[str]) -> str:
        """Find the appropriate grouping key for a path."""
        # Group by top-level key (metadata, spec, etc.) to avoid duplicate sections
        if len(path) >= 1:
            return path[0]  # First element like 'metadata', 'spec', etc.

        return ""

    def _parse_path_into_components(self, path: str) -> List[str]:
        """Parse path into components, handling brackets and dots correctly."""
        if not path:
            return []

        parts = []
        current = ""
        i = 0

        while i < len(path):
            char = path[i]

            if char == "[":
                if current:
                    parts.append(current)
                    current = ""
                # Find the closing bracket
                bracket_end = path.find("]", i)
                if bracket_end != -1:
                    bracket_content = path[i + 1 : bracket_end]
                    parts.append(bracket_content)
                    i = bracket_end
                else:
                    current += char
            elif char == ".":
                if current:
                    parts.append(current)
                    current = ""
            else:
                current += char

            i += 1

        if current:
            parts.append(current)

        return parts

    def _grouped_diffs_to_lines(
        self, grouped: Dict[str, List[DiffItem]], lines: List[str], use_color: bool
    ):
        """Convert grouped differences to formatted lines."""
        # Sort groups by path for consistent output
        for group_path in sorted(grouped.keys()):
            diffs = grouped[group_path]

            if not group_path:
                # Root level differences
                for diff in diffs:
                    self._add_diff_line(diff, lines, 0, use_color)
            else:
                # Build the hierarchy for this group
                path_parts = group_path.split(".") if group_path else []

                # Add hierarchy lines (with symbol column space for unchanged lines)
                for i, part in enumerate(path_parts):
                    indent = i * 2  # YAML indentation is 2 spaces per level
                    lines.append(" " + " " * indent + f"{part}:")

                # Add all the actual differences under this group
                base_indent = len(path_parts)
                self._add_grouped_diffs(diffs, lines, base_indent, use_color)

    def _add_grouped_diffs(
        self, diffs: List[DiffItem], lines: List[str], base_indent: int, use_color: bool
    ):
        """Add a group of diffs, building the nested structure within the group."""
        # Build a nested tree structure for all diffs in this group
        tree = {}

        for diff in diffs:
            # Find remaining path after the group prefix
            remaining_path = self._get_remaining_path(diff.path, base_indent)
            self._insert_diff_into_tree(tree, diff, remaining_path)

        # Convert the tree to lines
        self._tree_to_diff_lines(tree, lines, base_indent, use_color)

    def _insert_diff_into_tree(
        self, tree: Dict, diff: DiffItem, remaining_path: List[str]
    ):
        """Insert a diff into the tree structure."""
        current = tree

        # Navigate/create the path in the tree
        for part in remaining_path[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        # Add the diff at the leaf
        last_part = remaining_path[-1] if remaining_path else ""
        if last_part not in current:
            current[last_part] = []
        current[last_part].append(diff)

    def _tree_to_diff_lines(
        self,
        tree: Dict,
        lines: List[str],
        indent: int,
        use_color: bool,
        parent_key: str = "",
    ):
        """Convert tree structure to diff lines."""
        for key in sorted(tree.keys()):
            value = tree[key]

            if isinstance(value, dict):
                # Check if this is an env variable branch that should be flattened
                if parent_key == "env" and key.startswith("[") and key.endswith("]"):
                    # For env variables, collect all diffs within this variable's subtree
                    # and format them as env diff lines
                    env_diffs = []

                    def collect_env_diffs(d, path_parts):
                        for k, v in d.items():
                            if isinstance(v, dict):
                                collect_env_diffs(v, path_parts + [k])
                            elif isinstance(v, list):
                                env_diffs.extend(v)

                    collect_env_diffs(value, [])

                    # Check for complementary value/valueFrom changes that should be combined
                    combined_diffs = self._combine_complementary_env_diffs(env_diffs)

                    # Format all diffs for this env variable
                    for diff in combined_diffs:
                        if hasattr(diff, "path"):  # Ensure it's a DiffItem
                            self._add_env_diff_lines(diff, lines, indent, use_color)
                else:
                    # This is a normal branch (with symbol column space for unchanged lines)
                    yaml_indent = indent * 2  # YAML indentation is 2 spaces per level
                    lines.append(" " + " " * yaml_indent + f"{key}:")
                    self._tree_to_diff_lines(value, lines, indent + 1, use_color, key)
            else:
                # This is a leaf with diff items - diffs should be indented under their parent key
                for diff in value:
                    self._add_diff_line(diff, lines, indent, use_color)

    def _get_remaining_path(
        self, full_path: List[str], prefix_length: int
    ) -> List[str]:
        """Get the path parts after the prefix."""
        return full_path[prefix_length:] if prefix_length < len(full_path) else []

    def _add_diff_line(
        self, diff: DiffItem, lines: List[str], indent: int, use_color: bool
    ):
        """Add a single diff line with proper formatting."""
        path_str = diff.get_path_string()

        # Check if this is an env variable (either full env dict or value field)
        is_env = False
        for i, part in enumerate(diff.path):
            if part == "env":
                # Check if next part is a bracketed env name
                next_part = diff.path[i + 1] if i + 1 < len(diff.path) else ""
                if next_part.startswith("[") and next_part.endswith("]"):
                    is_env = True
                    break

        if is_env:
            self._add_env_diff_lines(diff, lines, indent, use_color)
        else:
            # Simple formatting for non-env diffs
            last_part = diff.path[-1] if diff.path else ""

            symbol = diff.change_type.value

            # Check if we need multiline formatting
            needs_multiline = (
                (
                    diff.change_type == ChangeType.MODIFIED
                    and (
                        _is_complex_value(diff.old_value)
                        or _is_complex_value(diff.new_value)
                    )
                )
                or (
                    diff.change_type == ChangeType.ADDED
                    and _is_complex_value(diff.new_value)
                )
                or (
                    diff.change_type == ChangeType.REMOVED
                    and _is_complex_value(diff.old_value)
                )
            )

            if needs_multiline:
                try:
                    # For complex objects, generate YAML with key name included
                    value = (
                        diff.new_value
                        if diff.change_type == ChangeType.ADDED
                        else diff.old_value
                    )
                    if isinstance(value, (dict, list)):
                        # Create YAML content that includes the key name
                        key_value_dict = {last_part: value}
                        yaml_content = format_value(
                            key_value_dict, multiline=True, indent_level=indent
                        )
                    else:
                        yaml_content = format_value(
                            value, multiline=True, indent_level=indent
                        )
                    # For debugging: check if yaml_content is valid
                    if not yaml_content or len(yaml_content.strip()) == 0:
                        yaml_indent = indent * 2
                        line = f"{symbol}{' ' * yaml_indent}{last_part}: <empty yaml content>"
                    else:
                        # Add symbol column: for added objects, all lines get symbol; for removed, all lines get symbol; for modified, first gets symbol, rest get space
                        yaml_lines = yaml_content.split("\n")
                        if (
                            yaml_lines and yaml_lines[-1] == ""
                        ):  # Remove trailing empty line
                            yaml_lines = yaml_lines[:-1]
                        if not yaml_lines:  # If no lines after cleaning
                            yaml_indent = indent * 2
                            line = f"{symbol}{' ' * yaml_indent}{last_part}: <no yaml lines>"
                        else:
                            yaml_lines_with_symbols = []
                            for i, yaml_line in enumerate(yaml_lines):
                                if diff.change_type == ChangeType.MODIFIED and i > 0:
                                    # For modified, only first line gets symbol
                                    yaml_lines_with_symbols.append(f" {yaml_line}")
                                else:
                                    # For added/removed, or first line of modified, use symbol
                                    yaml_lines_with_symbols.append(
                                        f"{symbol}{yaml_line}"
                                    )

                            line = "\n".join(yaml_lines_with_symbols)
                except Exception as e:
                    # Fallback if multiline processing fails
                    yaml_indent = indent * 2
                    line = f"{symbol}{' ' * yaml_indent}{last_part}: <multiline error: {str(e)}>"
            else:
                # For simple values, keep the compact format
                if diff.change_type == ChangeType.MODIFIED:
                    old_val = diff.old_value
                    new_val = diff.new_value
                    # Check if both are YAML-like strings for detailed diff
                    if _is_yaml_like_string(old_val) and _is_yaml_like_string(new_val):
                        value_str = _format_yaml_string_diff(
                            old_val, new_val, indent, use_color
                        )
                        yaml_indent = indent * 2
                        line = f"{symbol}{' ' * yaml_indent}{last_part}: |\n{value_str}"
                    else:
                        if isinstance(old_val, str) and "\n" in old_val:
                            old_formatted = format_literal_block(old_val, 0)
                        else:
                            old_formatted = str(old_val)
                        if isinstance(new_val, str) and "\n" in new_val:
                            new_formatted = format_literal_block(new_val, 0)
                        else:
                            new_formatted = str(new_val)
                        value_str = f"{old_formatted} → {new_formatted}"
                        yaml_indent = (
                            indent * 2
                        )  # YAML indentation is 2 spaces per level
                        line = f"{symbol}{' ' * yaml_indent}{last_part}: {value_str}"
                elif diff.change_type == ChangeType.ADDED:
                    val = diff.new_value
                    if isinstance(val, str) and "\n" in val:
                        value_str = format_literal_block(val, 0)
                    else:
                        value_str = str(val)
                    yaml_indent = indent * 2  # YAML indentation is 2 spaces per level
                    line = f"{symbol}{' ' * yaml_indent}{last_part}: {value_str}"
                else:  # REMOVED
                    val = diff.old_value
                    if isinstance(val, str) and "\n" in val:
                        value_str = format_literal_block(val, 0)
                    else:
                        value_str = str(val)
                    yaml_indent = indent * 2  # YAML indentation is 2 spaces per level
                    line = f"{symbol}{' ' * yaml_indent}{last_part}: {value_str}"
                if use_color:
                    colors = {
                        ChangeType.ADDED: "\033[32m",  # Green
                        ChangeType.REMOVED: "\033[31m",  # Red
                        ChangeType.MODIFIED: "\033[33m",  # Yellow
                    }
                    reset = "\033[0m"

                    if diff.change_type == ChangeType.MODIFIED and " → " in line:
                        # Special coloring for modified lines: yellow for symbol/name, red for old value, green for new value
                        parts = line.split(" → ", 1)
                        if len(parts) == 2:
                            old_part, new_part = parts
                            # Find the colon that separates field name from value
                            # Look for the colon after the dash (for env vars) or the rightmost colon (for other fields)
                            dash_index = old_part.find("- ")
                            if dash_index != -1:
                                # For lines with "- ", find the first colon after the dash
                                colon_search_start = dash_index + 2
                                colon_index = old_part.find(": ", colon_search_start)
                            else:
                                # Fallback to rightmost colon
                                colon_index = old_part.rfind(": ")

                            if colon_index != -1:
                                symbol_name_part = old_part[
                                    : colon_index + 2
                                ]  # Include ": "
                                old_value_part = old_part[
                                    colon_index + 2 :
                                ]  # Everything after ": "
                                # Color: yellow for symbol and name, red for old value and arrow, green for new value
                                line = f"{colors[ChangeType.MODIFIED]}{symbol_name_part}{colors[ChangeType.REMOVED]}{old_value_part} → {colors[ChangeType.ADDED]}{new_part}{reset}"
                            else:
                                # Fallback if no colon found
                                line = f"{colors[ChangeType.MODIFIED]}{old_part}{colors[ChangeType.REMOVED]} → {colors[ChangeType.ADDED]}{new_part}{reset}"
                        else:
                            # Fallback to regular coloring
                            line = f"{colors[diff.change_type]}{line}{reset}"
                    else:
                        # Regular coloring for added/removed lines
                        line = f"{colors[diff.change_type]}{line}{reset}"

            if needs_multiline and not use_color:
                # For multiline without color, we've already handled the symbols
                pass
            elif needs_multiline and use_color:
                # For multiline with color, color all lines for added/removed, first line only for modified
                colors = {
                    ChangeType.ADDED: "\033[32m",
                    ChangeType.REMOVED: "\033[31m",
                    ChangeType.MODIFIED: "\033[33m",
                }
                reset = "\033[0m"
                lines_with_color = []
                for i, line_part in enumerate(line.split("\n")):
                    if (
                        diff.change_type in (ChangeType.ADDED, ChangeType.REMOVED)
                        or i == 0
                    ):
                        lines_with_color.append(
                            f"{colors[diff.change_type]}{line_part}{reset}"
                        )
                    else:
                        lines_with_color.append(line_part)
                line = "\n".join(lines_with_color)

            lines.append(line)

    def _tree_to_lines(
        self, tree: Dict, lines: List[str], indent: int, use_color: bool
    ):
        """Convert tree structure to formatted lines."""
        for key in sorted(tree.keys()):
            value = tree[key]

            if isinstance(value, dict):
                # This is a branch
                lines.append("  " * indent + f"{key}:")
                self._tree_to_lines(value, lines, indent + 1, use_color)
            else:
                # This is a leaf with diff items
                for diff in value:
                    self._add_diff_lines(diff, lines, indent, use_color)

    def _add_diff_lines(
        self, diff: DiffItem, lines: List[str], base_indent: int, use_color: bool
    ):
        """Add formatted diff lines to the output."""
        # For env variables, use special formatting
        if diff._is_env_value_path(diff.path):
            self._add_env_diff_lines(diff, lines, base_indent, use_color)
        else:
            # For simple diffs, just add the formatted line
            formatted = diff.format(use_color)
            # Split into lines and add proper indentation
            for line in formatted.split("\n"):
                if line.strip():
                    lines.append("  " * base_indent + line)

    def _add_env_diff_lines(
        self, diff: DiffItem, lines: List[str], base_indent: int, use_color: bool
    ):
        """Add env variable diff lines with proper formatting."""
        # Debug: print indentation
        # print(f"DEBUG: base_indent={base_indent}, path={diff.path}")

        # Find the env name in the path list
        env_name = None
        for i, part in enumerate(diff.path):
            if part == "env" and i < len(diff.path) - 1:
                next_part = diff.path[i + 1]
                if next_part.startswith("[") and next_part.endswith("]"):
                    env_name = next_part[1:-1]  # Remove brackets
                    break

        if not env_name:
            # Fallback to simple formatting
            last_part = diff.path[-1] if diff.path else ""
            symbol = diff.change_type.value
            if diff.change_type == ChangeType.MODIFIED:
                old_str = format_value(diff.old_value, multiline=True)
                new_str = format_value(diff.new_value, multiline=True)
                value_str = f"{old_str} → {new_str}"
            elif diff.change_type == ChangeType.ADDED:
                value_str = format_value(diff.new_value, multiline=True)
            else:  # REMOVED
                value_str = format_value(diff.old_value, multiline=True)
            yaml_indent = base_indent * 2  # YAML indentation is 2 spaces per level
            line = f"{symbol}{' ' * yaml_indent}{last_part}: {value_str}"
            if use_color:
                colors = {
                    ChangeType.ADDED: "\033[32m",
                    ChangeType.REMOVED: "\033[31m",
                    ChangeType.MODIFIED: "\033[33m",
                }
                reset = "\033[0m"
                line = f"{colors[diff.change_type]}{line}{reset}"
            lines.append(line)
            return

        # Extract the actual value
        def get_env_value(value):
            if isinstance(value, dict) and "value" in value:
                return value["value"]
            return value

        symbol = diff.change_type.value

        # Check if we need multiline formatting for env values
        env_value = get_env_value(
            diff.old_value if diff.change_type == ChangeType.REMOVED else diff.new_value
        )
        needs_multiline = _is_complex_value(env_value)

        if needs_multiline:
            # For multiline env values, format as inline YAML
            if diff.change_type == ChangeType.MODIFIED:
                old_val = get_env_value(diff.old_value)
                new_val = get_env_value(diff.new_value)
                # Format complex values inline
                if isinstance(old_val, dict):
                    old_str = yaml.dump(old_val, default_flow_style=True).strip()
                else:
                    old_str = str(old_val)
                if isinstance(new_val, dict):
                    new_str = yaml.dump(new_val, default_flow_style=True).strip()
                else:
                    new_str = str(new_val)
                value_str = f"{old_str} → {new_str}"
            elif diff.change_type == ChangeType.ADDED:
                val = get_env_value(diff.new_value)
                if isinstance(val, dict):
                    value_str = yaml.dump(val, default_flow_style=True).strip()
                else:
                    value_str = str(val)
            else:  # REMOVED
                val = get_env_value(diff.old_value)
                if isinstance(val, dict):
                    value_str = yaml.dump(val, default_flow_style=True).strip()
                else:
                    value_str = str(val)

            yaml_indent = base_indent * 2  # YAML indentation is 2 spaces per level
            change_line = f"{symbol}{' ' * yaml_indent}- {env_name}: {value_str}"
        else:
            # For simple env values, keep compact format
            if diff.change_type == ChangeType.MODIFIED:
                old_val = get_env_value(diff.old_value)
                new_val = get_env_value(diff.new_value)
                value_str = f"{old_val} → {new_val}"
            elif diff.change_type == ChangeType.ADDED:
                value_str = get_env_value(diff.new_value)
            else:  # REMOVED
                value_str = get_env_value(diff.old_value)

            yaml_indent = base_indent * 2  # YAML indentation is 2 spaces per level
            change_line = f"{symbol}{' ' * yaml_indent}- {env_name}: {value_str}"

        if use_color:
            colors = {
                ChangeType.ADDED: "\033[32m",  # Green
                ChangeType.REMOVED: "\033[31m",  # Red
                ChangeType.MODIFIED: "\033[33m",  # Yellow
            }
            reset = "\033[0m"

            if diff.change_type == ChangeType.MODIFIED and " → " in change_line:
                # Special coloring for modified lines: yellow for symbol/name, red for old value, green for new value
                parts = change_line.split(" → ", 1)
                if len(parts) == 2:
                    old_part, new_part = parts
                    # Find the colon that separates field name from value
                    # Look for the colon after the dash (for env vars) or the rightmost colon (for other fields)
                    dash_index = old_part.find("- ")
                    if dash_index != -1:
                        # For lines with "- ", find the first colon after the dash
                        colon_search_start = dash_index + 2
                        colon_index = old_part.find(": ", colon_search_start)
                    else:
                        # Fallback to rightmost colon
                        colon_index = old_part.rfind(": ")

                    if colon_index != -1:
                        symbol_name_part = old_part[: colon_index + 2]  # Include ": "
                        old_value_part = old_part[
                            colon_index + 2 :
                        ]  # Everything after ": "
                        # Color: yellow for symbol and name, red for old value and arrow, green for new value
                        colored_line = f"{colors[ChangeType.MODIFIED]}{symbol_name_part}{colors[ChangeType.REMOVED]}{old_value_part} → {colors[ChangeType.ADDED]}{new_part}{reset}"
                        change_line = colored_line
                    else:
                        # Fallback if no colon found
                        colored_line = f"{colors[ChangeType.MODIFIED]}{old_part}{colors[ChangeType.REMOVED]} → {colors[ChangeType.ADDED]}{new_part}{reset}"
                        change_line = colored_line
                else:
                    # Fallback to regular coloring
                    change_line = f"{colors[diff.change_type]}{change_line}{reset}"
            else:
                # Regular coloring for added/removed lines
                change_line = f"{colors[diff.change_type]}{change_line}{reset}"

        lines.append(change_line)

    def _combine_complementary_env_diffs(
        self, env_diffs: List["DiffItem"]
    ) -> List["DiffItem"]:
        """Combine complementary env diffs (value + valueFrom changes) into single modified diffs."""
        if not env_diffs:
            return env_diffs

        # Group diffs by their field (value or valueFrom)
        value_diffs = {}
        value_from_diffs = {}

        for diff in env_diffs:
            # Get the last part of the path (should be 'value' or 'valueFrom')
            last_part = diff.path[-1] if diff.path else ""
            if last_part == "value":
                # Use the parent path (without the last element) as key
                parent_path = tuple(diff.path[:-1])
                value_diffs[parent_path] = diff
            elif last_part == "valueFrom":
                parent_path = tuple(diff.path[:-1])
                value_from_diffs[parent_path] = diff

        # Find complementary pairs and combine them
        combined_diffs = []
        processed_paths = set()

        # Check for value added + valueFrom removed (changing from secret to plain value)
        for parent_path in value_diffs:
            if parent_path in processed_paths:
                continue

            value_diff = value_diffs[parent_path]
            value_from_diff = value_from_diffs.get(parent_path)

            if (
                value_from_diff
                and value_diff.change_type == ChangeType.ADDED
                and value_from_diff.change_type == ChangeType.REMOVED
            ):
                # Combine into a single MODIFIED diff
                combined_diff = DiffItem(
                    change_type=ChangeType.MODIFIED,
                    path=value_diff.path[:-1],  # Remove the 'value' part
                    old_value=value_from_diff.old_value,
                    new_value=value_diff.new_value,
                )
                combined_diffs.append(combined_diff)
                processed_paths.add(parent_path)
            else:
                # Add the value diff if not combined
                if parent_path not in processed_paths:
                    combined_diffs.append(value_diff)

        # Check for valueFrom added + value removed (changing from plain value to secret)
        for parent_path in value_from_diffs:
            if parent_path in processed_paths:
                continue

            value_from_diff = value_from_diffs[parent_path]
            value_diff = value_diffs.get(parent_path)

            if (
                value_diff
                and value_from_diff.change_type == ChangeType.ADDED
                and value_diff.change_type == ChangeType.REMOVED
            ):
                # Combine into a single MODIFIED diff
                combined_diff = DiffItem(
                    change_type=ChangeType.MODIFIED,
                    path=value_from_diff.path[:-1],  # Remove the 'valueFrom' part
                    old_value=value_diff.old_value,
                    new_value=value_from_diff.new_value,
                )
                combined_diffs.append(combined_diff)
                processed_paths.add(parent_path)
            else:
                # Add the valueFrom diff if not combined
                if parent_path not in processed_paths:
                    combined_diffs.append(value_from_diff)

        return combined_diffs

    def normalize_data(self, data: Any, path: str = "") -> Any:
        """
        Recursively normalize data for comparison.
        Sorts lists of dictionaries by common keys to avoid order-dependent diffs.
        """
        if isinstance(data, dict):
            normalized = {}
            for key, value in data.items():
                new_path = f"{path}.{key}" if path else key
                normalized[key] = self.normalize_data(value, new_path)
            return normalized
        elif isinstance(data, list):
            # Check if this is a list of dictionaries with a common key
            if self._should_sort_list(data):
                sorted_data = sorted(data, key=self._get_sort_key)
                return [
                    self.normalize_data(item, f"{path}[{i}]")
                    for i, item in enumerate(sorted_data)
                ]
            else:
                return [
                    self.normalize_data(item, f"{path}[{i}]")
                    for i, item in enumerate(data)
                ]
        else:
            return data

    def _should_sort_list(self, data: List[Any]) -> bool:
        """Determine if a list should be sorted based on its contents."""
        if not data or not isinstance(data[0], dict):
            return False

        # Check if all items are dicts and have at least one common key
        first_keys = set(data[0].keys())
        if not first_keys:
            return False

        # For environment variables and similar named objects, sort by 'name'
        if "name" in first_keys:
            return True

        # For other cases, check if all dicts have the same keys
        # and at least one key that makes sense to sort by
        for item in data[1:]:
            if not isinstance(item, dict) or set(item.keys()) != first_keys:
                return False

        # Sort by the first key if all dicts are consistent
        return True

    def _get_sort_key(self, item: Dict[str, Any]) -> str:
        """Get the sort key for a dictionary item."""
        if isinstance(item, dict) and "name" in item:
            return str(item["name"])
        elif isinstance(item, dict):
            # Sort by the first key's value
            first_key = next(iter(item.keys()))
            return str(item[first_key])
        else:
            return str(item)

    def compare(self, left: Any, right: Any, path: str = "") -> None:
        """Recursively compare two data structures."""
        # Normalize both sides
        left_norm = self.normalize_data(left, path)
        right_norm = self.normalize_data(right, path)

        if type(left_norm) != type(right_norm):
            self.differences.append(
                DiffItem(ChangeType.MODIFIED, path, left_norm, right_norm)
            )
            return

        if isinstance(left_norm, dict):
            self._compare_dicts(left_norm, right_norm, path)
        elif isinstance(left_norm, list):
            self._compare_lists(left_norm, right_norm, path)
        else:
            if left_norm != right_norm:
                self.differences.append(
                    DiffItem(ChangeType.MODIFIED, path, left_norm, right_norm)
                )

    def _compare_dicts(
        self, left: Dict[str, Any], right: Dict[str, Any], path: List[str]
    ) -> None:
        """Compare two dictionaries."""
        left_keys = set(left.keys())
        right_keys = set(right.keys())

        # Added keys
        for key in right_keys - left_keys:
            full_path = path + [key]
            self.differences.append(
                DiffItem(ChangeType.ADDED, full_path, None, right[key])
            )

        # Removed keys
        for key in left_keys - right_keys:
            full_path = path + [key]
            self.differences.append(
                DiffItem(ChangeType.REMOVED, full_path, left[key], None)
            )

        # Modified keys
        for key in left_keys & right_keys:
            full_path = path + [key]
            self.compare(left[key], right[key], full_path)

    def _compare_lists(
        self, left: List[Any], right: List[Any], path: List[str]
    ) -> None:
        """Compare two lists."""
        # For lists of dictionaries with common keys, compare by content rather than order
        if self._should_sort_list(left) and self._should_sort_list(right):
            self._compare_sorted_lists(left, right, path)
        else:
            self._compare_ordered_lists(left, right, path)

    def _compare_sorted_lists(
        self, left: List[Any], right: List[Any], path: List[str]
    ) -> None:
        """Compare lists that should be sorted by content."""
        # Create maps keyed by sort key for comparison
        left_map = {self._get_sort_key(item): item for item in left}
        right_map = {self._get_sort_key(item): item for item in right}

        left_keys = set(left_map.keys())
        right_keys = set(right_map.keys())

        # Added items
        for key in right_keys - left_keys:
            item = right_map[key]
            self.differences.append(
                DiffItem(ChangeType.ADDED, path + [f"[{key}]"], None, item)
            )

        # Removed items
        for key in left_keys - right_keys:
            item = left_map[key]
            self.differences.append(
                DiffItem(ChangeType.REMOVED, path + [f"[{key}]"], item, None)
            )

        # Modified items
        for key in left_keys & right_keys:
            left_item = left_map[key]
            right_item = right_map[key]
            self.compare(left_item, right_item, path + [f"[{key}]"])

    def _compare_ordered_lists(
        self, left: List[Any], right: List[Any], path: List[str]
    ) -> None:
        """Compare lists that should maintain order."""
        left_len = len(left)
        right_len = len(right)

        # Compare common elements
        min_len = min(left_len, right_len)
        for i in range(min_len):
            item_path = path + [f"[{i}]"]
            self.compare(left[i], right[i], item_path)

        # Handle extra elements
        if right_len > left_len:
            for i in range(left_len, right_len):
                self.differences.append(
                    DiffItem(ChangeType.ADDED, path + [f"[{i}]"], None, right[i])
                )
        elif left_len > right_len:
            for i in range(right_len, left_len):
                self.differences.append(
                    DiffItem(ChangeType.REMOVED, path + [f"[{i}]"], left[i], None)
                )


def format_literal_block(value: str, indent_level: int) -> str:
    """Format a multiline string as a YAML literal block."""
    yaml_indent = "  " * indent_level
    lines = value.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    indented_lines = [yaml_indent + "  " + line for line in lines]
    return f"|\n" + "\n".join(indented_lines)


def format_value(
    value: Any,
    multiline: bool = False,
    indent_level: int = 0,
    symbol_column: bool = False,
) -> str:
    """Format a value, using multiline YAML for complex objects if requested."""
    if isinstance(value, str) and "\n" in value:
        # Format multiline strings as literal blocks
        return format_literal_block(value, indent_level)
    elif multiline and (isinstance(value, (dict, list)) and _is_complex_value(value)):
        # Format as multiline YAML
        try:
            yaml_str = yaml.dump(value, default_flow_style=False, indent=2, width=1000)
            # Remove the trailing newline and adjust indentation
            lines = yaml_str.rstrip("\n").split("\n")
            # The YAML content needs to be indented by indent_level * 2 spaces for proper YAML structure
            yaml_indent = "  " * indent_level
            indented_lines = [yaml_indent + line for line in lines]
            return "\n".join(indented_lines)
        except Exception:
            # Fallback to string representation
            yaml_indent = "  " * indent_level
            return yaml_indent + str(value)
    else:
        # Simple string representation
        return str(value)


def _is_yaml_like_string(value: Any) -> bool:
    """Check if a string value looks like YAML content."""
    if not isinstance(value, str):
        return False
    if "\n" not in value:
        return False
    # Simple heuristic: contains : and is multiline
    return ":" in value


def _format_yaml_string_diff(
    old_str: str, new_str: str, indent: int, use_color: bool
) -> str:
    """Format a diff between two YAML strings with detailed line-by-line comparison."""
    try:
        # Parse the YAML strings
        old_yaml = yaml.safe_load(old_str) if old_str.strip() else {}
        new_yaml = yaml.safe_load(new_str) if new_str.strip() else {}

        # Format both as YAML strings
        old_yaml_str = yaml.dump(
            old_yaml, default_flow_style=False, indent=2, width=1000
        ).rstrip("\n")
        new_yaml_str = yaml.dump(
            new_yaml, default_flow_style=False, indent=2, width=1000
        ).rstrip("\n")

        # Create a temporary differ to get the detailed diffs
        temp_differ = YAMLDiff()
        temp_differ.compare(old_yaml, new_yaml, [])

        # Create a merged view with change indicators
        return _create_side_by_side_yaml_view(
            old_yaml_str, new_yaml_str, temp_differ.differences, indent, use_color
        )

    except Exception:
        # Fallback to simple diff
        return (
            f"{format_literal_block(old_str, 0)} → {format_literal_block(new_str, 0)}"
        )


def _create_side_by_side_yaml_view(
    old_yaml_str: str,
    new_yaml_str: str,
    differences: List["DiffItem"],
    indent: int,
    use_color: bool,
) -> str:
    """Create a side-by-side YAML diff view with color indicators."""
    # For simplicity, just format the YAML strings with basic color coding
    # This is a simplified version - in a full implementation we'd need more sophisticated
    # line-by-line analysis

    result_lines = []

    # Add indentation
    indent_str = "  " * (indent + 1)

    # Create value to string mapping using YAML representation
    def value_to_yaml_str(val):
        if isinstance(val, bool):
            return "true" if val else "false"
        return str(val)

    # ANSI color codes
    colors = {
        "unchanged": "\033[37m",  # White
        "modified": "\033[33m",  # Yellow
        "added": "\033[32m",  # Green
        "removed": "\033[31m",  # Red
    }
    reset = "\033[0m"

    # Build path to change type mapping
    path_changes = {}
    for diff in differences:
        path_str = diff.get_path_string()
        if diff.change_type == ChangeType.MODIFIED:
            path_changes[path_str] = "modified"
        elif diff.change_type == ChangeType.ADDED:
            path_changes[path_str] = "added"
        elif diff.change_type == ChangeType.REMOVED:
            path_changes[path_str] = "removed"

    # Helper to determine change type for a path
    def get_change_type(path):
        return path_changes.get(path, "unchanged")

    # Add old content with colors
    if old_yaml_str:
        current_path = []
        for line in old_yaml_str.split("\n"):
            # Calculate indentation level to determine path
            stripped = line.lstrip()
            indent_level = len(line) - len(stripped)
            # Assuming 2 spaces per indent level
            path_depth = indent_level // 2

            # Adjust current path
            current_path = current_path[:path_depth]
            if ":" in stripped:
                key = stripped.split(":", 1)[0]
                current_path.append(key)

            # Check if this path has changes
            path_str = ".".join(current_path)
            change_type = get_change_type(path_str)

            if change_type == "removed":
                change_type = "removed"
            elif change_type == "modified":
                change_type = "modified"
            else:
                change_type = "unchanged"

            if use_color:
                colored_line = f"{colors[change_type]}{indent_str}{line}{reset}"
            else:
                colored_line = f"{indent_str}{line}"

            result_lines.append(colored_line)

    # Add arrow
    result_lines.append(f"{'  ' * indent}→")

    # Add new content with colors
    if new_yaml_str:
        current_path = []
        for line in new_yaml_str.split("\n"):
            # Calculate indentation level to determine path
            stripped = line.lstrip()
            indent_level = len(line) - len(stripped)
            # Assuming 2 spaces per indent level
            path_depth = indent_level // 2

            # Adjust current path
            current_path = current_path[:path_depth]
            if ":" in stripped:
                key = stripped.split(":", 1)[0]
                current_path.append(key)

            # Check if this path has changes
            path_str = ".".join(current_path)
            change_type = get_change_type(path_str)

            if change_type == "added":
                change_type = "added"
            elif change_type == "modified":
                change_type = "modified"
            else:
                change_type = "unchanged"

            if use_color:
                colored_line = f"{colors[change_type]}{indent_str}{line}{reset}"
            else:
                colored_line = f"{indent_str}{line}"

            result_lines.append(colored_line)

    return "\n".join(result_lines)


def _is_complex_value(value: Any) -> bool:
    """Check if a value is complex enough to warrant multiline formatting."""
    if isinstance(value, dict):
        return len(value) > 0
    elif isinstance(value, list):
        return len(value) > 0 and any(isinstance(item, (dict, list)) for item in value)
    return False


def load_yaml_file(file_path: str) -> Any:
    """Load a YAML file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading {file_path}: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    # Import version to avoid circular import
    from . import __version__

    parser = argparse.ArgumentParser(
        description="Compare YAML files with intelligent list sorting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  yd file1.yaml file2.yaml
  yd --counts --exit-code old.yaml new.yaml
  yd --color=never --paths-only file1.yaml file2.yaml
  yd --version
        """,
    )

    parser.add_argument("left_file", help="Path to the left YAML file")
    parser.add_argument("right_file", help="Path to the right YAML file")
    parser.add_argument(
        "--color",
        choices=["always", "never", "auto"],
        default="auto",
        help="When to use color output (default: auto)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"yd {__version__}",
        help="Show version number and exit",
    )
    parser.add_argument(
        "-c",
        "--counts",
        action="store_true",
        help="Display summary count of differences",
    )
    parser.add_argument(
        "-e",
        "--exit-code",
        action="store_true",
        help="Exit with non-zero status when differences are found",
    )
    parser.add_argument(
        "-p",
        "--paths-only",
        action="store_true",
        help="Show only paths of differences without values",
    )

    args = parser.parse_args()

    # Check if files exist
    left_path = Path(args.left_file)
    right_path = Path(args.right_file)

    if not left_path.exists():
        print(f"Error: Left file '{args.left_file}' does not exist", file=sys.stderr)
        sys.exit(1)

    if not right_path.exists():
        print(f"Error: Right file '{args.right_file}' does not exist", file=sys.stderr)
        sys.exit(1)

    # Load YAML files
    left_data = load_yaml_file(args.left_file)
    right_data = load_yaml_file(args.right_file)

    # Perform diff
    differ = YAMLDiff()
    differ.compare(left_data, right_data, [])

    # Determine if we should use color
    use_color = args.color == "always" or (args.color == "auto" and sys.stdout.isatty())

    # Output results
    if args.counts:
        added = sum(1 for d in differ.differences if d.change_type == ChangeType.ADDED)
        removed = sum(
            1 for d in differ.differences if d.change_type == ChangeType.REMOVED
        )
        modified = sum(
            1 for d in differ.differences if d.change_type == ChangeType.MODIFIED
        )
        print(f"Added: {added}, Removed: {removed}, Modified: {modified}")
    elif args.paths_only:
        for diff in differ.differences:
            path_str = (
                diff.get_path_string() if isinstance(diff.path, list) else diff.path
            )
            print(f"{diff.change_type.value} {path_str}")
    else:
        # Format as grouped tree
        output_lines = differ.format_as_tree(use_color)
        for line in output_lines:
            print(line)

    # Exit with appropriate code
    if args.exit_code and differ.differences:
        sys.exit(1)


if __name__ == "__main__":
    main()
