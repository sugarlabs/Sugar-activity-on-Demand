# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the focused-region repair helper.

These cover the pure extraction/rendering functions and the load-bearing
invariant that a SEARCH block copied verbatim from a focused slice still
applies against the full source.
"""

import ast
import os
import unittest

from generation.focus import build_focused_view
from generation.focus import defs_referencing_name
from generation.focus import enclosing_span_for_line
from generation.focus import extract_targets
from generation.focus import line_window
from generation.focus import merge_spans
from generation.focus import _build_definition_index
from generation.refine import apply_patches


_HANDLER_LINE = '        self.score.increment()'
_CONNECT_LINE = "        button.connect('clicked', self._on_click)"


def _make_source(handler_line=_HANDLER_LINE, filler=14, break_on_click=False):
    """Return a >60-line activity where __init__ wires a button to _on_click,
    with filler methods between them so the two regions are non-adjacent."""
    on_click_header = (
        '    def _on_click(self, button)' if break_on_click
        else '    def _on_click(self, button):')
    lines = [
        'from sugar3.activity import activity',
        '',
        '',
        'class GeneratedActivity(activity.Activity):',
        '    def __init__(self, handle):',
        '        activity.Activity.__init__(self, handle)',
        "        button = ToolButton('go')",
        _CONNECT_LINE,
        '        self.button = button',
    ]
    for index in range(filler):
        lines += [
            '',
            '    def _filler_%d(self, widget):' % index,
            '        value = %d' % index,
            '        return value',
        ]
    lines += [
        '',
        on_click_header,
        handler_line,
        '        return None',
        '',
    ]
    return '\n'.join(lines) + '\n'


def _runtime_diagnostics(source, func='_on_click', match=_HANDLER_LINE):
    line_no = source.split('\n').index(match) + 1
    frame = (
        'Traceback (most recent call last):\n'
        '  File "<activity>/activity.py", line %d, in %s\n'
        '    %s\n'
        "AttributeError: 'NoneType' object has no attribute 'increment'"
        % (line_no, func, match.strip()))
    return {'stage': 'runtime_check', 'errors': [frame],
            'runtime_detail': frame}, line_no


class TestExtractTargets(unittest.TestCase):

    def test_runtime_frame_yields_line_and_function(self):
        diagnostics = {
            'stage': 'runtime_check',
            'errors': [
                '  File "<activity>/activity.py", line 42, in _on_click\n'
                '    boom()'],
        }
        lines, funcs = extract_targets(diagnostics)
        self.assertEqual([42], lines)
        self.assertEqual(['_on_click'], funcs)

    def test_library_frames_are_ignored(self):
        diagnostics = {
            'errors': [
                '  File "/usr/lib/python3/site.py", line 99, in run\n'
                '  File "<activity>/activity.py", line 7, in _draw'],
        }
        lines, funcs = extract_targets(diagnostics)
        self.assertEqual([7], lines)
        self.assertEqual(['_draw'], funcs)

    def test_multiple_in_file_frames_dedupe_and_keep_order(self):
        diagnostics = {
            'errors': [
                '  File "<activity>/activity.py", line 5, in __init__\n'
                '  File "<activity>/activity.py", line 40, in _on_click\n'
                '  File "<activity>/activity.py", line 40, in _on_click'],
        }
        lines, funcs = extract_targets(diagnostics)
        self.assertEqual([5, 40], lines)
        self.assertEqual(['__init__', '_on_click'], funcs)

    def test_syntax_error_yields_line_only(self):
        diagnostics = {
            'stage': 'static_validation',
            'errors': ['Python syntax error on line 7: invalid syntax'],
        }
        lines, funcs = extract_targets(diagnostics)
        self.assertEqual([7], lines)
        self.assertEqual([], funcs)

    def test_safety_diagnostics_have_no_signal(self):
        diagnostics = {'errors': ['Forbidden import: subprocess',
                                  'Missing required method: write_file']}
        self.assertEqual(([], []), extract_targets(diagnostics))


class TestAstMapping(unittest.TestCase):

    def setUp(self):
        self.source = _make_source()
        self.defs = _build_definition_index(ast.parse(self.source))

    def test_enclosing_span_is_tightest_method_and_includes_header(self):
        source_lines = self.source.split('\n')
        handler_line = source_lines.index(_HANDLER_LINE) + 1
        span = enclosing_span_for_line(self.defs, handler_line)
        self.assertIsNotNone(span)
        start, end = span
        self.assertLessEqual(start, handler_line)
        self.assertGreaterEqual(end, handler_line)
        # The span starts at the method header, not the class.
        self.assertEqual(
            '    def _on_click(self, button):', source_lines[start - 1])

    def test_defs_referencing_name_pulls_in_wiring_not_self(self):
        spans = defs_referencing_name(self.defs, '_on_click')
        source_lines = self.source.split('\n')
        rendered = set()
        for start, end in spans:
            rendered.update(source_lines[start - 1:end])
        # __init__ (which connects the button) is pulled in...
        self.assertIn(_CONNECT_LINE, rendered)
        # ...but _on_click's own body is not returned as a "reference".
        self.assertNotIn(_HANDLER_LINE, rendered)


class TestSpanHelpers(unittest.TestCase):

    def test_merge_overlapping_and_near_adjacent(self):
        # (1,3) and (4,5) are within the 2-line gap -> merge; (20,22) is far.
        self.assertEqual(
            [(1, 5), (20, 22)],
            merge_spans([(4, 5), (1, 3), (20, 22)]))

    def test_distant_spans_stay_separate(self):
        self.assertEqual([(1, 2), (10, 11)], merge_spans([(1, 2), (10, 11)]))

    def test_line_window_centres_and_clamps(self):
        source_lines = ['x'] * 100
        self.assertEqual((42, 58), line_window(source_lines, 50, context=8))
        self.assertEqual((1, 9), line_window(source_lines, 1, context=8))
        self.assertEqual((92, 100), line_window(source_lines, 100, context=8))


class TestBuildFocusedView(unittest.TestCase):

    def test_small_file_returns_none(self):
        source = 'class GeneratedActivity:\n    pass\n'
        diagnostics = {'errors': [
            '  File "<activity>/activity.py", line 2, in x']}
        self.assertIsNone(
            build_focused_view(source, diagnostics, min_source_lines=60))

    def test_no_signal_returns_none(self):
        source = _make_source()
        diagnostics = {'errors': ['Forbidden import: subprocess']}
        self.assertIsNone(
            build_focused_view(source, diagnostics, min_source_lines=10))

    def test_over_ratio_returns_none(self):
        source = _make_source()
        diagnostics, _line = _runtime_diagnostics(source)
        self.assertIsNone(build_focused_view(
            source, diagnostics, min_source_lines=10, max_focus_ratio=0.01))

    def test_happy_path_shows_region_and_wiring_without_gutter(self):
        source = _make_source()
        diagnostics, _line = _runtime_diagnostics(source)
        view = build_focused_view(source, diagnostics, min_source_lines=10)
        self.assertIsNotNone(view)
        view_lines = view.split('\n')
        # Failing handler and the connect site that wires it are both shown,
        # verbatim (exact line, so no numbered gutter was prepended).
        self.assertIn(_HANDLER_LINE, view_lines)
        self.assertIn(_CONNECT_LINE, view_lines)
        # The filler methods between them are elided.
        self.assertNotIn('    def _filler_7(self, widget):', view_lines)
        self.assertTrue(any('elided' in line for line in view_lines))
        self.assertTrue(view.startswith('# Focused view of activity.py'))
        self.assertIn('lines total', view)

    def test_syntax_error_uses_line_window(self):
        source = _make_source(break_on_click=True)
        broken = '    def _on_click(self, button)'
        line_no = source.split('\n').index(broken) + 1
        diagnostics = {
            'stage': 'static_validation',
            'errors': ['Python syntax error on line %d: invalid syntax'
                       % line_no],
        }
        view = build_focused_view(source, diagnostics, min_source_lines=10)
        self.assertIsNotNone(view)
        self.assertIn(broken, view.split('\n'))

    def test_disabled_by_env_returns_none(self):
        source = _make_source()
        diagnostics, _line = _runtime_diagnostics(source)
        previous = os.environ.get('AOD_REPAIR_FOCUS')
        os.environ['AOD_REPAIR_FOCUS'] = 'off'
        try:
            self.assertIsNone(
                build_focused_view(source, diagnostics, min_source_lines=10))
        finally:
            if previous is None:
                del os.environ['AOD_REPAIR_FOCUS']
            else:
                os.environ['AOD_REPAIR_FOCUS'] = previous

    def test_never_raises_on_junk_input(self):
        for source, diagnostics in (
                (None, {}),
                (123, {'errors': ['File "activity.py", line 5, in x']}),
                ('short', 'garbage'),
                ('def broken(\n',
                 {'errors': ['Python syntax error on line 1']}),
                (_make_source(), None),
                (_make_source(), ['line', 42]),
        ):
            try:
                result = build_focused_view(source, diagnostics)
            except Exception as error:  # noqa: BLE001 - the whole point
                self.fail('build_focused_view raised: %s' % error)
            self.assertTrue(result is None or isinstance(result, str))


class TestSliceDerivedPatchAppliesToFullSource(unittest.TestCase):
    """The invariant that justifies the feature: a block copied from the
    focused slice applies cleanly against the whole file."""

    def test_patch_from_focused_view_applies_to_full_source(self):
        source = _make_source()
        diagnostics, _line = _runtime_diagnostics(source)
        view = build_focused_view(source, diagnostics, min_source_lines=10)
        self.assertIsNotNone(view)

        search = _HANDLER_LINE
        self.assertIn(search, view.split('\n'))
        replace = '        self.score.add(1)'

        patched, applied, failed = apply_patches(source, [(search, replace)])
        self.assertEqual(1, applied)
        self.assertEqual(0, failed)
        self.assertIn('self.score.add(1)', patched)


if __name__ == '__main__':
    unittest.main()
