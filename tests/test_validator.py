# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
from unittest import mock

from core.spec import ActivitySpec
from generation.templates import render_activity_source
from generation.generator import enrich_plan
from generation.validator import validate_activity_source_for_request
from generation.validator import validate_source


class TestAodValidator(unittest.TestCase):

    def test_rejects_syntax_errors(self):
        report = validate_source('class Broken(:\n    pass\n')
        self.assertFalse(report.valid)
        self.assertIn('Python syntax error', report.errors[0])

    def test_rejects_dangerous_imports_and_calls(self):
        report = validate_source(
            'import subprocess\n'
            'eval("1 + 1")\n'
        )
        self.assertFalse(report.valid)
        self.assertIn('Forbidden import: subprocess', report.errors)
        self.assertIn('Forbidden call: eval', report.errors)

    def test_rejects_optional_modules_missing_at_runtime(self):
        with mock.patch(
                'generation.validator._module_available',
                return_value=False):
            report = validate_source('import sugargame\n')
        self.assertTrue(any(
            "'sugargame' library is not installed" in error
            for error in report.errors), report.errors)

    def test_accepts_optional_modules_present_at_runtime(self):
        with mock.patch(
                'generation.validator._module_available',
                return_value=True):
            report = validate_source('import sugargame\nimport pygame\n')
        self.assertFalse(any(
            'is not installed' in error for error in report.errors),
            report.errors)

    def test_codegen_prompt_bans_pygame_when_unavailable(self):
        from generation import codegen as aodcodegen

        spec = ActivitySpec(
            'Racer', 'A space racer 2d game.', 'games', 'MIT')
        plan = enrich_plan(spec, {
            'name': 'Racer', 'template': 'grid',
            'bundle_id': 'org.sugarlabs.aod.Racer1234567890',
            'class_name': 'GeneratedActivity',
        })
        with mock.patch.object(
                aodcodegen, '_module_available', return_value=False):
            prompt = aodcodegen.build_codegen_system_prompt(spec, plan)
        self.assertIn('NOT installed on this system', prompt)
        self.assertNotIn('pygame via sugargame', prompt)

        with mock.patch.object(
                aodcodegen, '_module_available', return_value=True):
            prompt = aodcodegen.build_codegen_system_prompt(spec, plan)
        self.assertIn('pygame via sugargame', prompt)

    def test_requires_activity_structure(self):
        report = validate_source('class PlainObject:\n    pass\n')
        self.assertFalse(report.valid)
        self.assertTrue(any(
            error.startswith(
                'Generated source must define exactly one Activity subclass')
            for error in report.errors), report.errors)

    def test_rejects_invented_toolbar_and_adjustment_apis(self):
        spec = ActivitySpec(
            'Counter',
            'Make a counter utility.',
            'tools_utils',
            'MIT',
        )
        plan = enrich_plan(spec, {'template': 'utility'})
        source = render_activity_source(spec, plan)
        source = source.replace(
            'toolbar.insert(ActivityToolbarButton(self), 0)',
            'toolbar_box.add_toolbar_button(ActivityToolbarButton(self))',
        )
        source = source.replace(
            'self.set_canvas(canvas)',
            'adjustment.set_bounds(0, 10)\n        self.set_canvas(canvas)',
        )

        report = validate_source(source)

        self.assertFalse(report.valid)
        self.assertTrue(any(
            'add_toolbar_button' in error for error in report.errors
        ))
        self.assertTrue(any(
            'set_bounds' in error for error in report.errors
        ))

    def test_rejects_c_api_cairo_gradient_calls(self):
        spec = ActivitySpec(
            'Painter',
            'Draw a colourful gradient background.',
            'creation',
            'MIT',
        )
        plan = enrich_plan(spec, {'template': 'canvas'})
        source = render_activity_source(spec, plan)
        # A draw handler using the C cairo API instead of the pycairo
        # constructor — this raises AttributeError every frame and blanks
        # the canvas, so validation must reject it for the repair loop.
        source += (
            '\n\ndef _paint(cr, width, height):\n'
            '    gradient = cr.pattern_create_linear(0, 0, 0, height)\n'
            '    cr.set_source(gradient)\n'
            '    cr.paint()\n'
        )

        report = validate_source(source)

        self.assertFalse(report.valid)
        self.assertTrue(any(
            'pattern_create_linear' in error for error in report.errors
        ))

    def test_request_validation_rejects_generic_source_for_drawing(self):
        spec = ActivitySpec(
            'Draw Together',
            'Make an activity where two students can draw together.',
            'creation',
            'MIT',
        )
        plan = enrich_plan(spec, {
            'template': 'narrative',
            'summary': 'A writing activity.',
            'learner_goal': 'Write together.',
            'learner_steps': ['Write', 'Share'],
        })
        source = render_activity_source(spec, plan)

        report = validate_activity_source_for_request(source, spec, plan)

        self.assertFalse(report.valid)
        self.assertTrue(any(
            'Drawing requests must use' in error
            for error in report.errors
        ))

    def test_request_validation_accepts_real_canvas_for_drawing(self):
        spec = ActivitySpec(
            'Draw Together',
            'Make an activity where two students can draw together.',
            'creation',
            'MIT',
        )
        plan = enrich_plan(spec, {
            'template': 'canvas',
            'summary': 'A drawing activity for Student A and Student B.',
            'learner_goal': 'Students draw together.',
            'learner_steps': ['Student A draws', 'Student B draws'],
            'interaction_model': 'Students switch turns and draw together.',
        })
        source = render_activity_source(spec, plan)
        source += '\n# Student A and Student B switch turns together.\n'

        report = validate_activity_source_for_request(source, spec, plan)

        self.assertTrue(report.valid, report.errors)

    def test_solo_prompts_do_not_trigger_two_learner_or_drawing_gates(self):
        # 'students' as audience phrasing, 'two' as numeric phrasing, and
        # bare 'color' vocabulary must not force collaboration or drawing
        # features onto a valid solo activity.
        source = _PLAIN_ACTIVITY_SOURCE + \
            "\n        button.set_tooltip_text('Add a note')\n"
        for prompt in (
                'A counting practice for my students.',
                'A two-digit addition practice game.',
                'Name the color of each fruit game.'):
            spec = ActivitySpec('Solo Demo', prompt, 'logic_math', 'MIT')
            plan = enrich_plan(spec, {'template': 'utility'})
            report = validate_activity_source_for_request(source, spec, plan)
            self.assertFalse(
                any('Two-learner' in error or 'Drawing requests' in error
                    for error in report.errors),
                '%s -> %s' % (prompt, report.errors))

    def test_real_pairing_phrases_still_trigger_two_learner_gate(self):
        source = _PLAIN_ACTIVITY_SOURCE + \
            "\n        button.set_tooltip_text('Add a note')\n"
        spec = ActivitySpec(
            'Pair Demo', 'Two students take turns and play together.',
            'games', 'MIT')
        plan = enrich_plan(spec, {'template': 'utility'})
        report = validate_activity_source_for_request(source, spec, plan)
        self.assertTrue(
            any('Two-learner' in error for error in report.errors),
            report.errors)

    def test_source_terms_are_word_anchored(self):
        # 'return' must not satisfy the 'turn' requirement; real 'turns'
        # usage must.
        base = _PLAIN_ACTIVITY_SOURCE + \
            "\n        button.set_tooltip_text('Add a note')\n" + \
            "\n        self._player = 'Player 1'\n"
        spec = ActivitySpec(
            'Pair Demo', 'Two students play together.', 'games', 'MIT')
        plan = enrich_plan(spec, {'template': 'utility'})

        report = validate_activity_source_for_request(base, spec, plan)
        self.assertTrue(any(
            'turn, role, or collaboration' in error
            for error in report.errors), report.errors)

        satisfied = base + "\n        self._turns = 0\n"
        report = validate_activity_source_for_request(satisfied, spec, plan)
        self.assertFalse(any(
            'turn, role, or collaboration' in error
            for error in report.errors), report.errors)

    def test_imported_activity_base_class_style_is_accepted(self):
        source = _PLAIN_ACTIVITY_SOURCE.replace(
            'from sugar3.activity import activity',
            'from sugar3.activity.activity import Activity',
        ).replace(
            'class GeneratedActivity(activity.Activity):',
            'class GeneratedActivity(Activity):',
        ).replace(
            'activity.Activity.__init__(self, handle)',
            'Activity.__init__(self, handle)',
        )
        report = validate_source(source)
        self.assertFalse(any(
            'exactly one Activity subclass' in error
            for error in report.errors), report.errors)

    def test_validate_bundle_reports_malformed_archives(self):
        import tempfile
        from generation.validator import validate_bundle

        with tempfile.NamedTemporaryFile(
                suffix='.xo', delete=False) as handle:
            handle.write(b'this is not a zip file')
            path = handle.name
        try:
            report = validate_bundle(path)
        finally:
            import os as _os
            _os.unlink(path)
        self.assertFalse(report.valid)
        self.assertTrue(any(
            'Invalid XO bundle' in error for error in report.errors),
            report.errors)

    def _ui_spec(self, **kwargs):
        return ActivitySpec(
            'Notes Keeper',
            'A simple notes keeper for the classroom.',
            'tools_utils',
            'MIT',
            **kwargs)

    def _ui_plan(self):
        return enrich_plan(self._ui_spec(), {
            'template': 'utility',
            'summary': 'A notes activity.',
            'learner_goal': 'Keep classroom notes.',
        })

    def test_ui_gate_rejects_plain_unstyled_source(self):
        report = validate_activity_source_for_request(
            _PLAIN_ACTIVITY_SOURCE, self._ui_spec(), self._ui_plan())
        self.assertFalse(report.valid)
        self.assertTrue(
            any('not Sugar-native' in error for error in report.errors),
            report.errors)

    def test_ui_gate_passes_with_a_single_style_signal(self):
        # Any one styling touch clears the gate (four-signal AND).
        snippets = (
            "\n        button.set_tooltip_text('Add a note')\n",
            "\n        pad = style.zoom(8)\n",
            "\n        label.set_markup('<b>Notes</b>')\n",
            "\n        box.get_style_context().add_class('panel')\n",
        )
        for snippet in snippets:
            source = _PLAIN_ACTIVITY_SOURCE + snippet
            report = validate_activity_source_for_request(
                source, self._ui_spec(), self._ui_plan())
            self.assertFalse(
                any('not Sugar-native' in error for error in report.errors),
                'signal %r should satisfy the gate: %r'
                % (snippet, report.errors))

    def test_ui_gate_skips_compact_activities(self):
        report = validate_activity_source_for_request(
            _PLAIN_ACTIVITY_SOURCE, self._ui_spec(code_size='compact'),
            self._ui_plan())
        self.assertFalse(
            any('not Sugar-native' in error for error in report.errors),
            report.errors)

    def test_ui_gate_skips_barely_interactive_activities(self):
        # Fewer than two interactive widgets -> not judged (a mostly-static
        # or drawing activity is never trapped).
        source = _PLAIN_ACTIVITY_SOURCE.replace(
            "        clear_button = Gtk.Button(label='Clear notes')\n"
            "        clear_button.connect('clicked', self._clear_notes)\n"
            "        box.pack_start(clear_button, False, False, 0)\n", ''
        ).replace(
            "        self._entry = Gtk.Entry()\n"
            "        box.pack_start(self._entry, False, False, 0)\n", ''
        )
        report = validate_activity_source_for_request(
            source, self._ui_spec(), self._ui_plan())
        self.assertFalse(
            any('not Sugar-native' in error for error in report.errors),
            report.errors)

    def test_generated_templates_pass_the_ui_gate(self):
        # The offline templates are Sugar-native, so they never trip the
        # gate (they also never reach it on the real path, but prove it).
        spec = self._ui_spec()
        plan = self._ui_plan()
        source = render_activity_source(spec, plan)
        report = validate_activity_source_for_request(source, spec, plan)
        self.assertFalse(
            any('not Sugar-native' in error for error in report.errors),
            report.errors)


_PLAIN_ACTIVITY_SOURCE = '''\
# SPDX-License-Identifier: MIT

import json

import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gtk

from sugar3.activity import activity
from sugar3.activity.widgets import ActivityToolbarButton
from sugar3.activity.widgets import StopButton
from sugar3.graphics.toolbarbox import ToolbarBox


class GeneratedActivity(activity.Activity):
    def __init__(self, handle):
        activity.Activity.__init__(self, handle)
        self.max_participants = 1
        self._notes = []
        self._build_toolbar()
        self._build_canvas()

    def _build_toolbar(self):
        toolbar_box = ToolbarBox()
        toolbar = toolbar_box.toolbar
        toolbar.insert(ActivityToolbarButton(self), 0)
        toolbar.insert(StopButton(self), -1)
        self.set_toolbar_box(toolbar_box)
        toolbar_box.show_all()

    def _build_canvas(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(24)
        self._label = Gtk.Label(label='Notes')
        box.pack_start(self._label, False, False, 0)
        self._entry = Gtk.Entry()
        box.pack_start(self._entry, False, False, 0)
        add_button = Gtk.Button(label='Add note')
        add_button.connect('clicked', self._add_note)
        box.pack_start(add_button, False, False, 0)
        clear_button = Gtk.Button(label='Clear notes')
        clear_button.connect('clicked', self._clear_notes)
        box.pack_start(clear_button, False, False, 0)
        self.set_canvas(box)
        box.show_all()

    def _add_note(self, button):
        text = self._entry.get_text().strip()
        if text:
            self._notes.append(text)
            self._entry.set_text('')
            self._label.set_text('%d notes saved' % len(self._notes))

    def _clear_notes(self, button):
        self._notes = []
        self._label.set_text('Notes')

    def write_file(self, file_path):
        with open(file_path, 'w', encoding='utf-8') as output:
            json.dump({'notes': self._notes}, output)

    def read_file(self, file_path):
        try:
            with open(file_path, encoding='utf-8') as source:
                self._notes = json.load(source).get('notes', [])
        except (OSError, ValueError):
            self._notes = []
        self._label.set_text('%d notes saved' % len(self._notes))
'''
