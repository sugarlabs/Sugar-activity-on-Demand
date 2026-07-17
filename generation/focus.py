# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Focus the repair prompt on the failing region of an activity.py.

The repair loop otherwise resends the whole file on every attempt.  When the
failure diagnostics point at a specific place -- a runtime traceback frame
(``File "<activity>/activity.py", line 42, in _on_click``) or a syntax error
line -- this module returns just that region plus the code that wires it (for
example the ``__init__`` that runs ``button.connect('clicked',
self._on_click)`` beside the failing ``_on_click`` handler).  That is faster
and gives the model tighter anchors to copy SEARCH blocks from.

This is a *presentation-only* helper.  It never changes what is verified: the
repair loop still applies patches, checks uniqueness, and re-runs every gate
against the full source.  Because SEARCH/REPLACE matches line-based against the
whole file (see :mod:`generation.refine`), a block copied verbatim from a slice
still applies to the complete file.

The one hard contract the loop relies on: :func:`build_focused_view` never
raises.  On any doubt -- disabled, tiny file, no location signal, unparseable
source, or a region that is not meaningfully smaller than the whole -- it
returns ``None`` and the caller sends the full source.
"""

import ast
import os
import re


# Runtime traceback frames and validator syntax errors are the only diagnostics
# that carry a source location.  Keep the frame filter anchored to activity.py
# so library frames (which point at other files) never mislocate the region.
_FRAME_RE = re.compile(r'File "([^"]*)", line (\d+), in (\S+)')
_SYNTAX_RE = re.compile(r'syntax error on line (\d+)', re.IGNORECASE)


def build_focused_view(source, diagnostics,
                       min_source_lines=None, max_focus_ratio=None):
    """Return a rendered focused view of ``source``, or ``None``.

    ``None`` means "use the full source".  It is returned when focus is
    disabled by env, the file is smaller than ``min_source_lines``, no location
    signal can be parsed from ``diagnostics``, the source cannot be parsed and
    no syntax line-window applies, or the focused view is not meaningfully
    smaller than the whole (covered / total > ``max_focus_ratio``).

    Never raises: every failure yields ``None``.
    """
    try:
        return _build_focused_view(
            source, diagnostics, min_source_lines, max_focus_ratio)
    except Exception:
        # Focus is an optimisation; any failure must degrade to full source.
        return None


def _build_focused_view(source, diagnostics,
                        min_source_lines, max_focus_ratio):
    if not _focus_enabled():
        return None
    if not isinstance(source, str) or not source.strip():
        return None

    if min_source_lines is None:
        min_source_lines = _env_int('AOD_REPAIR_FOCUS_MIN_LINES', 60)
    if max_focus_ratio is None:
        max_focus_ratio = _env_int('AOD_REPAIR_FOCUS_MAX_PCT', 70) / 100.0

    # Match refine.apply_patches' own split so a rendered slice is a
    # byte-for-byte substring of what patch matching sees.
    source_lines = source.split('\n')
    total_lines = len(source_lines)
    if total_lines < min_source_lines:
        return None

    target_lines, target_funcs = extract_targets(diagnostics)
    if not target_lines and not target_funcs:
        return None

    tree = None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None

    spans = []
    if tree is not None:
        defs = _build_definition_index(tree)
        for line in target_lines:
            span = enclosing_span_for_line(defs, line)
            spans.append(span or line_window(source_lines, line))
        for func in target_funcs:
            own = _span_for_def_name(defs, func)
            if own:
                spans.append(own)
            spans.extend(defs_referencing_name(defs, func))
    else:
        # Syntax error: ast.parse failed, so there is no definition index.
        # Fall back to a line window around each reported line.
        for line in target_lines:
            spans.append(line_window(source_lines, line))

    spans = [span for span in spans if span]
    if not spans:
        return None

    merged = merge_spans(spans)
    covered = sum(end - start + 1 for start, end in merged)
    if covered <= 0 or covered / total_lines > max_focus_ratio:
        return None

    return render_view(source_lines, merged, total_lines)


def extract_targets(diagnostics):
    """Return ``([line_numbers], [function_names])`` parsed from diagnostics.

    Scans the diagnostics text for runtime traceback frames whose filename ends
    in ``activity.py`` (collecting each in-file line and function name) and for
    ``Python syntax error on line N`` messages (line only; AST is unavailable
    downstream).  Both lists are de-duplicated and order-preserving.
    """
    text = _diagnostics_to_text(diagnostics)
    lines = []
    funcs = []
    for match in _FRAME_RE.finditer(text):
        filename, lineno, func = match.group(1), match.group(2), match.group(3)
        if not filename.endswith('activity.py'):
            continue
        number = int(lineno)
        if number not in lines:
            lines.append(number)
        if func not in funcs:
            funcs.append(func)
    for match in _SYNTAX_RE.finditer(text):
        number = int(match.group(1))
        if number not in lines:
            lines.append(number)
    return lines, funcs


def _build_definition_index(tree):
    """Return a record per FunctionDef/AsyncFunctionDef/ClassDef.

    Each record is ``{'name', 'start', 'end', 'node'}`` with 1-based inclusive
    line bounds.  ``start`` includes any decorator lines so the span is a valid
    contiguous block, and always covers the ``def``/``class`` header.
    """
    records = []
    for node in ast.walk(tree):
        if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno
        for decorator in getattr(node, 'decorator_list', ()) or ():
            start = min(start, decorator.lineno)
        end = getattr(node, 'end_lineno', None) or node.lineno
        records.append(
            {'name': node.name, 'start': start, 'end': end, 'node': node})
    return records


def enclosing_span_for_line(defs, line):
    """Return ``(start, end)`` of the tightest definition holding ``line``.

    Tightest = the most deeply nested definition (largest start line), so a
    method wins over its enclosing class.  Returns ``None`` when ``line`` falls
    outside every definition (a module-level line).
    """
    best = None
    for record in defs:
        if record['start'] <= line <= record['end']:
            if best is None or record['start'] > best['start']:
                best = record
    if best is None:
        return None
    return (best['start'], best['end'])


def defs_referencing_name(defs, target_name):
    """Return spans of every function whose body references ``target_name``.

    This pulls the widget-creation / connect site (e.g. ``__init__`` running
    ``button.connect('clicked', self._on_click)``) in alongside the failing
    handler, so the model sees the control and its logic together.  The
    target's own definition is excluded, and classes are skipped so a single
    referencing method never drags in the whole class body.
    """
    spans = []
    for record in defs:
        if record['name'] == target_name:
            continue
        if isinstance(record['node'], ast.ClassDef):
            continue
        if _node_references_name(record['node'], target_name):
            spans.append((record['start'], record['end']))
    return spans


def line_window(source_lines, line, context=8):
    """Return a ``(start, end)`` window centred on ``line``, clamped to file.

    Used only when ``ast.parse`` fails (a syntax error) so no definition index
    exists.  Bounds are 1-based inclusive.
    """
    total = len(source_lines)
    if total == 0:
        return None
    line = max(1, min(line, total))
    start = max(1, line - context)
    end = min(total, line + context)
    return (start, end)


def merge_spans(spans, gap=2):
    """Sort and merge overlapping or near-adjacent ``(start, end)`` spans.

    Spans separated by at most ``gap`` lines are merged so the rendered view
    does not show a sliver of elision between them.
    """
    clean = sorted(
        (start, end) for start, end in spans
        if start and end and start <= end
    )
    if not clean:
        return []
    merged = [list(clean[0])]
    for start, end in clean[1:]:
        last = merged[-1]
        if start <= last[1] + gap + 1:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def render_view(source_lines, spans, total_lines):
    """Render merged spans as a header plus verbatim slices.

    Line numbers appear only in the header and in the elision markers between
    non-contiguous spans.  Body lines are the raw source lines
    with no gutter so the model can copy them straight into SEARCH blocks.
    """
    shown = ', '.join(
        '%d-%d' % (start, end) if start != end else '%d' % start
        for start, end in spans
    )
    parts = [
        '# Focused view of activity.py (%d lines total). Showing lines %s; '
        'other regions are elided and unchanged.' % (total_lines, shown)
    ]
    previous_end = None
    for start, end in spans:
        if previous_end is not None:
            gap_start = previous_end + 1
            gap_end = start - 1
            if gap_end >= gap_start:
                parts.append(
                    '# ... lines %d-%d elided ...' % (gap_start, gap_end))
            else:
                parts.append('# ...')
        parts.extend(source_lines[start - 1:end])
        previous_end = end
    return '\n'.join(parts)


def _node_references_name(node, target_name):
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr == target_name:
            return True
        if isinstance(child, ast.Name) and child.id == target_name:
            return True
    return False


def _span_for_def_name(defs, name):
    for record in defs:
        if record['name'] == name:
            return (record['start'], record['end'])
    return None


def _diagnostics_to_text(diagnostics):
    if isinstance(diagnostics, str):
        return diagnostics
    if isinstance(diagnostics, dict):
        parts = []
        errors = diagnostics.get('errors')
        if isinstance(errors, (list, tuple)):
            parts.extend(str(error) for error in errors)
        detail = diagnostics.get('runtime_detail')
        if isinstance(detail, str):
            parts.append(detail)
        return '\n'.join(parts)
    if isinstance(diagnostics, (list, tuple)):
        return '\n'.join(str(item) for item in diagnostics)
    return str(diagnostics)


def _focus_enabled():
    return os.environ.get('AOD_REPAIR_FOCUS', 'on').lower() not in (
        'off', '0', 'no', 'false')


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
