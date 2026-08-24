# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_GTK_SANITIZED_VARS = (
    'LD_LIBRARY_PATH', 'GTK_PATH', 'GIO_MODULE_DIR',
    'GDK_PIXBUF_MODULE_FILE', 'GTK_EXE_PREFIX', 'GTK_IM_MODULE_FILE',
)


def _clean_gtk_env():
    return {
        key: value for key, value in os.environ.items()
        if key not in _GTK_SANITIZED_VARS
    }


def _gtk_display_available():
    if not (os.environ.get('DISPLAY') or
            os.environ.get('WAYLAND_DISPLAY')):
        return False
    probe = (
        'import gi\n'
        'gi.require_version("Gtk", "3.0")\n'
        'from gi.repository import Gtk\n'
        'result = Gtk.init_check()\n'
        'available = result[0] if isinstance(result, tuple) else result\n'
        'raise SystemExit(0 if available else 1)\n'
    )
    try:
        completed = subprocess.run(
            [sys.executable, '-c', probe],
            cwd=REPO_ROOT,
            env=_clean_gtk_env(),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


class _StatusLabel:
    """Minimal stand-in for the GTK labels the provider callbacks write to."""

    def __init__(self):
        self.text = ''

    def set_text(self, text):
        self.text = text


def _provider_apply_panel(**overrides):
    """Panel stub for __provider_apply_clicked_cb, without a display."""
    from types import SimpleNamespace

    panel = SimpleNamespace(
        _provider_test_running=False,
        _provider_status_label=_StatusLabel(),
        _prompt_status_label=_StatusLabel(),
    )
    for name, value in overrides.items():
        setattr(panel, name, value)
    return panel


class TestStudioDecoupling(unittest.TestCase):

    def test_activity_tools_presets_follow_activity_capabilities(self):
        from ui.panel import _activity_tools_presets
        quiz = [label for label, prompt in _activity_tools_presets({
            'template': 'quiz', 'summary': 'A scored challenge'})]
        generic = [label for label, prompt in _activity_tools_presets({
            'template': 'tool', 'summary': 'A simple counter'})]
        self.assertIn('Adjust challenge', quiz)
        self.assertNotIn('Add a level', generic)
        self.assertIn('Fix a problem', generic)

    def test_activity_tools_health_does_not_invent_runtime_success(self):
        from ui.panel import _activity_health_rows
        rows = dict(_activity_health_rows({
            'verification_status': 'passed',
            'runtime_check': 'skipped: disabled',
            'critic': 'ok',
        }))
        self.assertEqual('Passed', rows['Code checks'])
        self.assertEqual('Skipped', rows['Activity launch'])
        self.assertEqual('Skipped', rows['Journal save test'])
        self.assertEqual('Passed', rows['Model review'])

    def test_unverified_critic_patch_is_not_shown_as_passed(self):
        from ui.panel import _activity_health_rows
        rows = dict(_activity_health_rows({
            'verification_status': 'passed',
            'runtime_check': 'skipped: disabled',
            'critic': 'patched-unverified:2',
        }))
        self.assertEqual('Not verified', rows['Model review'])

    def test_reflection_prompts_are_activity_specific(self):
        from ui.panel import _activity_reflection_prompts
        from ui.panel import _activity_student_explanation
        prompts = _activity_reflection_prompts({
            'template': 'game', 'summary': 'Swim around obstacles'})
        self.assertEqual(4, len(prompts))
        self.assertIn('round', prompts[0].lower())
        self.assertIn('score', prompts[1].lower())
        self.assertIn('own words', prompts[2].lower())
        explanation = _activity_student_explanation({
            'interaction_model': 'Move the swimmer with arrow keys.',
            'learner_steps': ['Start swimming', 'Avoid a jellyfish'],
        })
        self.assertIn('Move the swimmer', explanation)
        self.assertIn('• Avoid a jellyfish', explanation)

    def test_learning_area_cards_use_bundled_sugar_artwork(self):
        from ui.panel import _learning_area_icon_kwargs

        for learning_area in (
                'logic_math', 'science', 'language', 'tools_utils',
                'games', 'creation'):
            kwargs = _learning_area_icon_kwargs(
                learning_area, 'image-missing')
            self.assertEqual({'file'}, set(kwargs))
            self.assertTrue(os.path.isfile(kwargs['file']))
            self.assertIn(
                os.path.join('data', 'icons', 'learning-areas'),
                kwargs['file'])

    def test_prompt_controls_use_bundled_sugar_style_icons(self):
        from ui.panel import _prompt_control_icon_kwargs

        for control in ('example', 'reference', 'send'):
            kwargs = _prompt_control_icon_kwargs(control, 'image-missing')
            self.assertEqual({'file'}, set(kwargs))
            self.assertTrue(os.path.isfile(kwargs['file']))
            self.assertIn(
                os.path.join('data', 'icons', 'prompt-controls'),
                kwargs['file'])

    def test_panel_imports_without_any_jarabe_module(self):
        code = (
            'import sys\n'
            'import ui.panel\n'
            'import ui.window\n'
            'import main\n'
            'bad = [m for m in sys.modules if m.startswith("jarabe")]\n'
            'assert not bad, "jarabe leaked into standalone studio: %s" '
            '% bad\n'
        )
        completed = subprocess.run(
            [sys.executable, '-c', code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            0, completed.returncode,
            'decoupling check failed:\n%s%s'
            % (completed.stdout, completed.stderr))

    def test_clean_generation_error_text_strips_pipeline_prefixes(self):
        from ui.panel import _clean_generation_error_text

        self.assertEqual(
            'Drawing requests must use a Gtk.DrawingArea draw surface.',
            _clean_generation_error_text(
                'Provider could not generate valid activity code: '
                'Provider generated code did not pass validation: '
                'Drawing requests must use a Gtk.DrawingArea draw '
                'surface.'))
        self.assertEqual(
            'attempt_limit_reached: validation still failed',
            _clean_generation_error_text(
                'Provider could not repair activity code: '
                'attempt_limit_reached: validation still failed'))
        self.assertEqual('plain message',
                         _clean_generation_error_text('plain message'))
        self.assertEqual('', _clean_generation_error_text(None))

    def test_format_user_friendly_error(self):
        from ui.panel import _format_user_friendly_error

        self.assertIn(
            'What went wrong:',
            _format_user_friendly_error(
                'Provider could not repair activity code: '
                'attempt_limit_reached: validation still failed'))

        self.assertIn(
            'automatically pass all validation checks',
            _format_user_friendly_error('attempt_limit_reached'))

        self.assertIn(
            'syntax error',
            _format_user_friendly_error('SyntaxError: invalid syntax'))

        self.assertIn(
            'missing variable, function, or library',
            _format_user_friendly_error("NameError: name 'foo' is not defined"))

        self.assertIn(
            'AI model provider',
            _format_user_friendly_error('HTTP 401 Unauthorized API key error'))

        self.assertIn(
            'What went wrong: Custom error message',
            _format_user_friendly_error('Custom error message'))


    def test_refinement_prompt_respects_backend_limit(self):
        from core.spec import MAX_PROMPT_LENGTH
        from ui.panel import CreateAIActivityPanel

        limited = CreateAIActivityPanel._limit_refinement_prompt(
            None, 'head' + ('x' * 20000) + 'tail')

        self.assertLessEqual(len(limited), MAX_PROMPT_LENGTH)
        self.assertTrue(limited.startswith('head'))
        self.assertTrue(limited.endswith('tail'))

    def test_refinement_spec_contains_only_latest_instruction(self):
        from types import SimpleNamespace

        from core.spec import ActivitySpec
        from ui.panel import CreateAIActivityPanel

        base_spec = ActivitySpec(
            'Swim', 'Original long swimming request.', 'games', 'MIT')
        panel = SimpleNamespace(
            _generation_result=SimpleNamespace(
                spec=base_spec,
                plan={
                    'template': 'canvas',
                    'summary': 'Old summary that is context, not a request.',
                }),
            _selected_options={'code_size': 'standard'},
        )
        spec = CreateAIActivityPanel._build_refinement_spec(
            panel, 'Make the arrow keys responsive.')

        self.assertEqual('Make the arrow keys responsive.', spec.prompt)
        self.assertNotIn('Original long swimming request', spec.prompt)
        self.assertNotIn('Old summary', spec.prompt)

    def test_provider_apply_starts_model_test_for_cloud_provider(self):
        import threading
        import types
        from types import SimpleNamespace

        from ui.panel import CreateAIActivityPanel

        provider = SimpleNamespace(label='OpenRouter', model='test-model')
        tested = []
        finished = threading.Event()

        def worker(test_provider):
            tested.append(test_provider)
            finished.set()

        panel = _provider_apply_panel(
            _configure_selected_provider=lambda persist: provider,
            _provider_test_worker=worker)
        panel._start_provider_test = types.MethodType(
            CreateAIActivityPanel._start_provider_test, panel)

        CreateAIActivityPanel.\
            _CreateAIActivityPanel__provider_apply_clicked_cb(panel, None)

        self.assertTrue(finished.wait(timeout=5))
        self.assertEqual([provider], tested)
        self.assertTrue(panel._provider_test_running)
        self.assertIn('OpenRouter', panel._provider_status_label.text)
        self.assertEqual('Testing model', panel._prompt_status_label.text)

    def test_provider_apply_skips_model_test_when_no_key_needed(self):
        import types
        from types import SimpleNamespace

        from ui.panel import CreateAIActivityPanel

        tested = []
        panel = _provider_apply_panel(
            _configure_selected_provider=lambda persist: True,
            _provider_test_worker=tested.append)
        panel._start_provider_test = types.MethodType(
            CreateAIActivityPanel._start_provider_test, panel)

        CreateAIActivityPanel.\
            _CreateAIActivityPanel__provider_apply_clicked_cb(panel, None)

        self.assertEqual([], tested)
        self.assertFalse(panel._provider_test_running)

    def test_provider_apply_skips_model_test_when_setup_failed(self):
        import types

        from ui.panel import CreateAIActivityPanel

        tested = []
        panel = _provider_apply_panel(
            _configure_selected_provider=lambda persist: False,
            _provider_test_worker=tested.append)
        panel._start_provider_test = types.MethodType(
            CreateAIActivityPanel._start_provider_test, panel)

        CreateAIActivityPanel.\
            _CreateAIActivityPanel__provider_apply_clicked_cb(panel, None)

        self.assertEqual([], tested)
        self.assertFalse(panel._provider_test_running)

    def test_auto_reference_provider_falls_back_to_configured_vision(self):
        from types import SimpleNamespace

        from ui.panel import CreateAIActivityPanel

        text_provider = SimpleNamespace(
            supports_image_input=lambda: False)
        vision_provider = SimpleNamespace(
            supports_image_input=lambda: True)
        providers = {
            'freemodel': text_provider,
            'gemini': vision_provider,
        }
        service = SimpleNamespace(
            resolve_provider=lambda name: providers.get(name))
        panel = SimpleNamespace(
            _selected_options={'provider': 'default'})

        name, provider = \
            CreateAIActivityPanel._resolve_reference_image_provider(
                panel, service, 'freemodel')

        self.assertEqual('gemini', name)
        self.assertIs(vision_provider, provider)

    def test_local_policy_never_falls_back_to_cloud_for_reference(self):
        from types import SimpleNamespace

        from ui.panel import CreateAIActivityPanel

        vision_provider = SimpleNamespace(
            supports_image_input=lambda: True)
        providers = {'gemini': vision_provider}
        service = SimpleNamespace(
            resolve_provider=lambda name: providers.get(name))
        panel = SimpleNamespace(_selected_options={
            'provider': 'default',
            'policy': 'local',
            'planner': 'rag',
        })

        unused_name, provider = \
            CreateAIActivityPanel._resolve_reference_image_provider(
                panel, service, 'local-template')

        self.assertIsNone(provider)

    def test_reference_image_candidates_fall_back_across_vision_providers(self):
        from types import SimpleNamespace

        from ui.panel import CreateAIActivityPanel

        text_only_openrouter = SimpleNamespace(
            label='OpenRouter', supports_image_input=lambda: True)
        gemini = SimpleNamespace(
            label='Gemini', supports_image_input=lambda: True)
        providers = {
            'openrouter': text_only_openrouter,
            'gemini': gemini,
        }
        service = SimpleNamespace(
            resolve_provider=lambda name: providers.get(name))
        panel = SimpleNamespace(_selected_options={
            'provider': 'openrouter',
            'policy': 'default',
            'planner': 'rag',
        })

        candidates = \
            CreateAIActivityPanel._reference_image_candidates(panel, service,
                                                              'openrouter')

        names = [name for name, unused_provider in candidates]
        self.assertEqual('openrouter', names[0])
        self.assertIn('gemini', names)
        self.assertEqual(candidates[1][1], gemini)

    def test_local_policy_never_adds_cloud_reference_fallback(self):
        from types import SimpleNamespace

        from ui.panel import CreateAIActivityPanel

        gemini = SimpleNamespace(
            label='Gemini', supports_image_input=lambda: True)
        providers = {'gemini': gemini}
        service = SimpleNamespace(
            resolve_provider=lambda name: providers.get(name))
        panel = SimpleNamespace(_selected_options={
            'provider': 'local-template',
            'policy': 'local',
            'planner': 'rag',
        })

        candidates = \
            CreateAIActivityPanel._reference_image_candidates(
                panel, service, 'local-template')

        self.assertEqual([], candidates)

    def test_openrouter_vision_fallback_routes_are_added(self):
        from types import SimpleNamespace

        from llm.providers import create_provider
        from ui.panel import CreateAIActivityPanel
        from ui.panel import _OPENROUTER_VISION_FALLBACK_MODELS

        openrouter = create_provider('openrouter', api_key='or-key',
                                     model='some/text-only-route')
        providers = {'openrouter': openrouter}
        service = SimpleNamespace(
            resolve_provider=lambda name: providers.get(name))
        panel = SimpleNamespace(_selected_options={
            'provider': 'openrouter',
            'policy': 'default',
            'planner': 'rag',
        })

        candidates = \
            CreateAIActivityPanel._reference_image_candidates(
                panel, service, 'openrouter')

        names = [name for name, unused_provider in candidates]
        models = [provider.model for unused_name, provider in candidates]
        self.assertEqual('openrouter', names[0])
        self.assertEqual('some/text-only-route', models[0])
        for vision_model in _OPENROUTER_VISION_FALLBACK_MODELS:
            self.assertIn(vision_model, models)

    def test_openrouter_vision_fallback_skips_configured_model(self):
        from types import SimpleNamespace

        from llm.providers import create_provider
        from ui.panel import CreateAIActivityPanel
        from ui.panel import _OPENROUTER_VISION_FALLBACK_MODELS

        openrouter = create_provider(
            'openrouter', api_key='or-key',
            model=_OPENROUTER_VISION_FALLBACK_MODELS[0])
        providers = {'openrouter': openrouter}
        service = SimpleNamespace(
            resolve_provider=lambda name: providers.get(name))
        panel = SimpleNamespace(_selected_options={
            'provider': 'openrouter',
            'policy': 'default',
            'planner': 'rag',
        })

        candidates = \
            CreateAIActivityPanel._reference_image_candidates(
                panel, service, 'openrouter')

        models = [provider.model for unused_name, provider in candidates]
        self.assertEqual(1, models.count(_OPENROUTER_VISION_FALLBACK_MODELS[0]))


_OFFSCREEN_SCRIPT = '''
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk
from gi.repository import Gtk

from ui.panel import CreateAIActivityPanel

window = Gtk.OffscreenWindow()
window.set_default_size(900, 800)
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
while Gtk.events_pending():
    Gtk.main_iteration_do(False)

assert panel._stack.get_visible_child_name() == 'home', \\
    panel._stack.get_visible_child_name()
assert panel._sidebar_visible is False
assert isinstance(panel._sidebar_toggle_button, Gtk.Button)
assert panel._sidebar_toggle_button.get_label() == '🔧 Change'
assert not panel._sidebar_toggle_button.get_sensitive()
assert panel._live_edit_enabled is False
assert panel._live_edit_off_button.get_style_context().has_class(
    'create-ai-live-toggle-active')
assert not panel._live_edit_on_button.get_style_context().has_class(
    'create-ai-live-toggle-active')

panel.append_prompt_text('a fractions quiz for kids')
panel.cancel_generation()
while Gtk.events_pending():
    Gtk.main_iteration_do(False)

# Destroy the panel before the OffscreenWindow. GTK's OffscreenWindow
# segfaults if it disposes this widget tree itself during its own
# teardown; a real Gtk.Window (and the running app) tears the same panel
# down cleanly, so this is a harness-only teardown detail, not an app bug.
panel.destroy()
window.destroy()
print('OFFSCREEN-OK')
'''


_OFFSCREEN_HOME_SCRIPT = '''
import json
import os
import tempfile
import time
from types import SimpleNamespace

sugar_home = tempfile.mkdtemp(prefix='aod-studio-home-test-')
os.environ['SUGAR_HOME'] = sugar_home

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk
from gi.repository import Gtk

from ui.panel import CreateAIActivityPanel


def pump():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


window = Gtk.OffscreenWindow()
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
pump()

assert panel._stack.get_visible_child_name() == 'home'
assert panel._home_empty_box.get_visible()
assert len(panel._home_ring_icons) == 0

assert panel._enhance_button is not None
assert not panel._enhance_button.get_visible()
assert panel._enhance_chip is not None
assert panel._enhance_chip_value_label.get_text() == 'Auto'
assert panel._prompt_status_label is not None
assert not panel._prompt_status_label.get_visible()
assert panel._template_hint is not None
assert not panel._template_hint.get_visible()
assert panel._planner_hint is not None
assert not panel._planner_hint.get_visible()
assert panel._selected_options['enhance'] == 'on'

# "Create new" now opens the prompt directly (the MODIFY/CREATE chooser
# was removed), so the stack goes straight to the create view.
panel._CreateAIActivityPanel__home_create_new_cb(None)
pump()
assert panel._stack.get_visible_child_name() == 'create'


class FakeEnhancer:
    def generate_text(self, system_prompt, user_prompt, timeout=120,
                      stream_callback=None):
        assert 'Do not turn a normal game' in system_prompt
        assert 'space racer' in user_prompt
        return ('Build a space racer with arrow-key steering, moving '
                'obstacles, a finish line, score, and Journal-saved progress.')


panel._resolve_active_provider = lambda: FakeEnhancer()
panel._set_prompt_text('space racer')
panel._enhance_chip.emit('clicked')
deadline = time.monotonic() + 3
while panel._enhance_running and time.monotonic() < deadline:
    pump()
    time.sleep(0.01)
pump()
assert not panel._enhance_running
assert panel._enhance_chip_value_label.get_text() == 'Done'
assert 'arrow-key steering' in panel._get_prompt_text()

# Enter submits the complete automatic flow; Shift+Enter still inserts a
# newline so longer prompts remain easy to write.
submit_calls = []
panel._CreateAIActivityPanel__send_button_clicked_cb = (
    lambda widget: submit_calls.append(widget))

class PromptKeyEvent:
    keyval = Gdk.KEY_Return
    state = 0

assert panel._CreateAIActivityPanel__prompt_key_press_event_cb(
    panel._prompt_text, PromptKeyEvent())
assert submit_calls == [panel._prompt_text]
PromptKeyEvent.state = Gdk.ModifierType.SHIFT_MASK
assert not panel._CreateAIActivityPanel__prompt_key_press_event_cb(
    panel._prompt_text, PromptKeyEvent())
assert submit_calls == [panel._prompt_text]


class FakeAutoFlowProvider:
    def __init__(self):
        self.question_prompt = ''

    def generate_text(self, system_prompt, user_prompt, timeout=120,
                      stream_callback=None):
        return ('A swimming obstacle race where the player alternates arrow '
                'keys, avoids rocks, reaches a finish line, and saves the '
                'best time to the Journal.')

    def generate_plan(self, system_prompt, user_prompt, timeout=90):
        self.question_prompt = user_prompt
        return {'questions': []}


auto_provider = FakeAutoFlowProvider()
panel._resolve_active_provider = lambda: auto_provider
generated_prompts = []
panel._submit_generation_from_prompt = (
    lambda prompt, chat_prompt=None, display_prompt=None,
    already_enhanced=False:
    generated_prompts.append(
        (prompt, chat_prompt, display_prompt, already_enhanced)))
panel._set_prompt_text(
    'swimming activity where a character avoids obstacles')
panel._begin_guided_generation(
    'swimming activity where a character avoids obstacles')
deadline = time.monotonic() + 3
while not generated_prompts and time.monotonic() < deadline:
    pump()
    time.sleep(0.01)
pump()
assert generated_prompts, generated_prompts
assert 'alternates arrow keys' in generated_prompts[0][0]
assert 'alternates arrow keys' in auto_provider.question_prompt
assert generated_prompts[0][1] == (
    'swimming activity where a character avoids obstacles')
assert generated_prompts[0][3]

panel._CreateAIActivityPanel__back_to_home_cb(None)
pump()
assert panel._stack.get_visible_child_name() == 'home'

project_dir = os.path.join(
    sugar_home, 'default', 'aod', 'projects', 'Demo.activity')
os.makedirs(os.path.join(project_dir, 'activity'))
with open(os.path.join(project_dir, 'aod_plan.json'), 'w',
          encoding='utf-8') as plan_file:
    json.dump({'name': 'Demo Activity', 'template': 'grid'}, plan_file)
with open(os.path.join(project_dir, 'activity', 'activity.svg'), 'w',
          encoding='utf-8') as icon_file:
    icon_file.write('<svg xmlns="http://www.w3.org/2000/svg"/>')

panel._refresh_home_projects()
pump()
assert len(panel._home_ring_icons) == 1
assert panel._home_ring.get_visible()
assert not panel._home_empty_box.get_visible()

# A completed activity exposes activity-aware refinement suggestions beside
# the refinement textbox. Choosing one fills the textbox without immediately
# submitting it, so the learner can edit the proposed request first.
panel._generation_result = SimpleNamespace(
    plan={'template': 'game', 'summary': 'A scored obstacle race'},
    files={'activity.py': 'def move_with_arrow_keys(): pass'},
)
panel._refresh_refinement_suggestions()
pump()
assert panel._chat_suggestions.get_visible()
suggestion_labels = [button.get_label()
                     for button in panel._chat_suggestion_buttons]
assert 'Adjust challenge' in suggestion_labels
assert 'Improve controls' not in suggestion_labels  # only four concise chips
first_suggestion = panel._chat_suggestion_buttons[0]
assert panel._chat_entry.get_text() == ''
first_suggestion.emit('clicked')
pump()
assert panel._chat_entry.get_text()
assert 'engaging and fair' in panel._chat_entry.get_text()

# Destroy the panel first: see the note in _OFFSCREEN_SCRIPT above.
panel.destroy()
window.destroy()
print('OFFSCREEN-HOME-OK')
'''


_OFFSCREEN_TARGET_SCRIPT = '''
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from ui.panel import CreateAIActivityPanel

window = Gtk.OffscreenWindow()
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
while Gtk.events_pending():
    Gtk.main_iteration_do(False)

# A click inside a canvas maps to a named 3x3 zone plus exact percentages.
assert panel._live_edit_zone(0, 0, 200, 100)[0] == 'top-left'
assert panel._live_edit_zone(100, 50, 200, 100)[0] == 'centre'
assert panel._live_edit_zone(200, 100, 200, 100)[0] == 'bottom-right'
zone, px, py = panel._live_edit_zone(150, 25, 200, 100)
assert zone == 'top-right', zone
assert (px, py) == (75, 25), (px, py)

# The description carries the zone and clamped percentages...
desc = panel._describe_canvas_point(
    'drawing canvas', 180, 20, (0, 0), (200, 100))
assert 'drawing canvas' in desc and 'top-right' in desc, desc
assert '90%' in desc and '20%' in desc, desc
# ...and the widget origin is subtracted before measuring.
desc2 = panel._describe_canvas_point(
    'drawing canvas', 60, 60, (40, 40), (40, 40))
assert '50%, 50%' in desc2, desc2

# Target kind drives the note the refinement backend receives.
panel._set_live_edit_target('drawing canvas - centre (50%, 50%)', kind='point')
assert panel._live_edit_target_kind == 'point'
assert not panel._live_edit_target_is_region
assert 'precise spot' in panel._preview_target_note()

panel._set_live_edit_target('area 10%, 10%', is_region=True)
assert panel._live_edit_target_kind == 'region'
assert 'dragged a selection' in panel._preview_target_note()

panel._set_live_edit_target('button: Clear')
assert panel._live_edit_target_kind == 'widget'
assert 'clicked this specific part' in panel._preview_target_note()

# Picking a target now returns (desc, widget, origin, size); nothing under
# the pointer yields a clean 4-tuple of Nones rather than crashing.
result = panel._pick_live_edit_target_at(window, -100, -100)
assert isinstance(result, tuple) and len(result) == 4, result
assert result[1] is None

panel.destroy()
window.destroy()
print('OFFSCREEN-TARGET-OK')
'''


_OFFSCREEN_ASK_BAR_SCRIPT = '''
import time
from types import SimpleNamespace

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, Gtk

from core.spec import ActivitySpec
import service.service as service_module
from ui.panel import CreateAIActivityPanel
from ui.reference_image import ReferenceImage
from sugar3.graphics.toolbutton import ToolButton

window = Gtk.OffscreenWindow()
window.set_default_size(1280, 800)
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
panel._stack.set_transition_duration(0)
panel._stack.set_visible_child_name('create')
while Gtk.events_pending():
    Gtk.main_iteration_do(False)

default_prompt_width = panel._prompt_box.get_allocated_width()
assert default_prompt_width >= 850, default_prompt_width

assert panel._ask_bar_entry is not None, 'ask bar entry missing'
assert panel._ask_bar_reference_button is not None, \
    'reference image button missing'
assert panel._prompt_reference_button is not None, \
    'create prompt reference image button missing'
assert isinstance(panel._prompt_reference_button, ToolButton), \
    'create prompt reference control is not a Sugar ToolButton'
assert panel._reference_image is None, 'reference should start empty'
assert not panel._ask_bar_reference_clear.get_visible(), \
    'studio remove button visible without attachment'
assert not panel._prompt_reference_clear.get_visible(), \
    'create remove button visible without attachment'

# Ctrl+V attaches a clipboard image in the studio prompt. A text clipboard
# remains available to the entry's normal paste behavior.
paste_pixbuf = GdkPixbuf.Pixbuf.new(
    GdkPixbuf.Colorspace.RGB, False, 8, 20, 10)
paste_pixbuf.fill(0x3366ccff)
clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
clipboard.set_image(paste_pixbuf)
paste_event = SimpleNamespace(
    state=Gdk.ModifierType.CONTROL_MASK,
    keyval=Gdk.KEY_v,
)
handled = panel._CreateAIActivityPanel__ask_bar_key_press_event_cb(
    panel._ask_bar_entry, paste_event)
assert handled, 'clipboard image paste was not handled'
deadline = time.monotonic() + 3
while panel._reference_loading_running and time.monotonic() < deadline:
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    time.sleep(0.01)
assert panel._reference_image is not None, 'clipboard image was not attached'
assert panel._reference_image.source_name == 'pasted-reference.png'
panel._clear_reference_image()
clipboard.set_text('ordinary copied text', -1)
assert not panel._CreateAIActivityPanel__ask_bar_key_press_event_cb(
    panel._ask_bar_entry, paste_event), 'text paste should remain native'

# The ask bar must submit without depending on the removed live-edit
# entry (which is always None now).
calls = []
panel._submit_refinement_from_prompt = (
    lambda text, source='chat': calls.append((source, text)))
send = panel._CreateAIActivityPanel__ask_bar_send_cb

panel._live_edit_enabled = False
panel._ask_bar_entry.set_text('make the score bigger')
send(None)
assert panel._ask_bar_entry.get_text() == '', 'entry not cleared after send'

panel._live_edit_enabled = True
panel._ask_bar_entry.set_text('change the button colour')
send(None)

# Blank input must not submit.
panel._ask_bar_entry.set_text('   ')
send(None)

assert calls == [
    ('chat', 'make the score bigger'),
    ('preview', 'change the button colour'),
], calls

# With an existing activity, an attached image can be sent without text and
# is routed to the asynchronous reference path instead of the text path.
pixbuf = GdkPixbuf.Pixbuf.new(
    GdkPixbuf.Colorspace.RGB, False, 8, 2, 1)
pixbuf.fill(0x3366ccff)
saved, image_data = pixbuf.save_to_bufferv('png', [], [])
assert saved
reference = ReferenceImage(
    data=bytes(image_data), mime_type='image/png', width=2, height=1,
    source_name='mockup.png', sha256='abc123')

panel._generation_result = object()
panel._reference_image = reference
panel._update_reference_image_ui()
assert panel._ask_bar_reference_clear.get_visible()
assert panel._prompt_reference_clear.get_visible()
window.show_all()
while Gtk.events_pending():
    Gtk.main_iteration_do(False)
assert panel._ask_bar_reference_clear.get_visible()
assert panel._prompt_reference_clear.get_visible()
assert panel._prompt_box.get_allocated_width() == default_prompt_width, (
    panel._prompt_box.get_allocated_width(), default_prompt_width)
reference_calls = []
panel._begin_reference_image_refinement = (
    lambda text, source: reference_calls.append((source, text)))
panel._live_edit_enabled = False
panel._ask_bar_entry.set_text('')
send(None)
assert reference_calls == [('chat', '')], reference_calls

# The initial creation prompt uses the same attachment path.
panel._generation_result = None
panel._set_prompt_text('build a science observation game')
panel._CreateAIActivityPanel__send_button_clicked_cb(None)
assert reference_calls[-1] == (
    'create', 'build a science observation game'), reference_calls

# The vision result is added only to the backend prompt. The learner-facing
# prompt stays readable, and the attachment is marked for the eventual job.
panel._reference_analysis_running = True
guided_calls = []
panel._begin_guided_generation = (
    lambda prompt, display_prompt=None:
    guided_calls.append((prompt, display_prompt)))
panel._reference_image_analysis_finished_cb(
    panel._reference_analysis_serial,
    'abc123',
    'build a science observation game',
    'create',
    'Reference image brief:\\n- Layout: two large cards',
    '',
)
assert len(guided_calls) == 1, guided_calls
assert 'two large cards' in guided_calls[0][0], guided_calls
assert guided_calls[0][1] == 'build a science observation game', guided_calls
assert panel._reference_pending_sha == 'abc123'

# Optional vision analysis must never block generation. If analysis fails,
# continue from the activity prompt while keeping the pixels attached for the
# code model (which may still support image input directly).
panel._reference_analysis_running = True
panel._reference_image_analysis_finished_cb(
    panel._reference_analysis_serial,
    'abc123',
    'build a science observation game',
    'create',
    '',
    'vision route temporarily unavailable',
)
assert len(guided_calls) == 2, guided_calls
assert guided_calls[1] == (
    'build a science observation game',
    'build a science observation game'), guided_calls
assert panel._reference_image is reference
assert panel._reference_pending_sha == 'abc123'

# Submitting the backend-expanded spec must keep the original learner prompt
# visible. The same in-memory mockup appears in the user bubble without being
# added to persisted session data or duplicated above the activity preview.
submitted = []
fake_job = SimpleNamespace(job_id='fake-job', session_id='fake-session')
fake_service = SimpleNamespace(
    submit_activity=lambda spec, **kwargs:
    (submitted.append((spec, kwargs)) or fake_job),
    watch=lambda job_id, callback: None,
)
service_module._service = fake_service
panel._resolve_generation_provider_name = lambda service: 'local-template'
panel._generation_job_updated_from_worker = lambda job: None
backend_spec = ActivitySpec(
    'Science Sort',
    'BACKEND CONFIRMED REQUIREMENTS THAT MUST STAY HIDDEN',
    'science',
    'MIT',
    categories=('science', 'games'),
)
panel._submit_generation_spec(
    backend_spec,
    chat_prompt='Original learner prompt',
    display_prompt='Original learner prompt',
)
assert submitted and submitted[0][0].prompt.startswith('BACKEND CONFIRMED')
assert panel._get_prompt_text() == 'Original learner prompt'
assert submitted[0][1]['reference_image_data'] == reference.data
assert submitted[0][1]['reference_image_mime_type'] == 'image/png'

def descendants(widget):
    found = [widget]
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            found.extend(descendants(child))
    return found

reference_images = [
    widget for widget in descendants(panel._chat_messages_box)
    if isinstance(widget, Gtk.Image)
    and (widget.get_tooltip_text() or '').startswith('Reference:')
]
assert reference_images, 'left chat user bubble has no reference mockup'

# A completed unrelated job must not alter the attachment. The exact job that
# consumed it releases ownership but keeps the memory-only image for Rebuild.
panel._reference_inflight_sha = 'abc123'
panel._reference_inflight_job_id = 'reference-job'
assert not panel._clear_reference_for_completed_job('other-job')
assert panel._reference_image is not None
assert panel._clear_reference_for_completed_job('reference-job')
assert panel._reference_image is reference
assert panel._reference_pending_sha == 'abc123'
assert panel._reference_inflight_sha == ''
assert panel._reference_inflight_job_id == ''
panel._clear_reference_image()
window.show_all()
while Gtk.events_pending():
    Gtk.main_iteration_do(False)
assert not panel._ask_bar_reference_clear.get_visible()
assert not panel._prompt_reference_clear.get_visible()

panel.destroy()
window.destroy()
print('OFFSCREEN-ASKBAR-OK')
'''


_OFFSCREEN_GUIDED_SCRIPT = '''
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from llm.clarify import format_answers
from ui.panel import CreateAIActivityPanel


def pump():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def all_label_text(widget):
    texts = []
    getter = getattr(widget, 'get_children', None)
    if getter is None:
        return texts
    for child in getter():
        if isinstance(child, Gtk.Label):
            texts.append(child.get_text())
        texts.extend(all_label_text(child))
    return texts


window = Gtk.OffscreenWindow()
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
pump()

# The guided page lives in the studio preview column and its scaffolding
# is visible (regression: an all-hidden child produced a blank screen).
assert panel._studio_mode_stack.get_child_by_name('guided') is not None
assert panel._guided_view.get_visible()

questions = [
    {'id': 'mode', 'label': 'Who plays?', 'type': 'single',
     'options': ['Human vs AI', '2-player']},
    {'id': 'features', 'label': 'Which features?', 'type': 'multi',
     'options': ['Undo', 'Clock']},
    {'id': 'else', 'label': 'Anything else?', 'type': 'text'},
]
display_prompt = 'PROMPT MUST STAY IN CHAT ONLY ' * 80
panel._guided_state = {
    'prompt': 'chess', 'display_prompt': display_prompt,
    'spec': None, 'provider': None,
    'questions': questions, 'answers': {}, 'answers_text': '',
    'answer_widgets': {}, 'plan_text': '', 'discussion': [],
}
panel._show_questions_page(questions)
pump()
children = panel._guided_body.get_children()
assert children, 'questions page has no widgets'
assert any(w.get_visible() for w in children), 'questions widgets hidden'
labels = all_label_text(panel._guided_body)
assert not any('PROMPT MUST STAY IN CHAT ONLY' in text for text in labels), \
    labels
assert set(panel._guided_state['answer_widgets']) == {
    'mode', 'features', 'else'}

panel._collect_guided_answers()
assert isinstance(panel._guided_state['answers'], dict)

panel._guided_state['answers'] = {'mode': 'Human vs AI'}

# Continue goes straight to building — there is no separate plan-review
# step. The answers are folded into the prompt for the normal submit path.
captured = {}
panel._submit_generation_from_prompt = (
    lambda prompt, chat_prompt=None, display_prompt=None,
    already_enhanced=False: captured.update(
        prompt=prompt, chat_prompt=chat_prompt,
        display_prompt=display_prompt,
        already_enhanced=already_enhanced))
panel._commit_guided_and_build()
assert 'chess' in captured['prompt'], captured
assert 'Confirmed requirements' in captured['prompt'], captured
assert 'Human vs AI' in captured['prompt'], captured
assert captured['chat_prompt'] == display_prompt
assert captured['display_prompt'] == display_prompt
assert panel._guided_state is None

panel.destroy()
window.destroy()
print('OFFSCREEN-GUIDED-OK')
'''


_OFFSCREEN_GUIDED_TRIGGER_SCRIPT = '''
import threading
import time

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import llm.clarify as clarify
from ui.panel import CreateAIActivityPanel


def pump():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def all_label_text(widget):
    texts = []
    getter = getattr(widget, 'get_children', None)
    if getter is None:
        return texts
    for child in getter():
        if isinstance(child, Gtk.Label):
            texts.append(child.get_text())
        texts.extend(all_label_text(child))
    return texts


class _FakeProvider:
    name = 'openrouter'
    model = 'test'


QUESTIONS = [
    {'id': 'mode', 'label': 'Who plays?', 'type': 'single',
     'options': ['A', 'B']},
    {'id': 'extra', 'label': 'Anything else?', 'type': 'text'},
]
questions_release = threading.Event()


def paused_questions(provider, spec, timeout=90):
    questions_release.wait(2)
    return QUESTIONS


clarify.generate_questions = paused_questions

window = Gtk.OffscreenWindow()
window.set_default_size(1200, 900)
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
pump()

# Sending an idea must open the questionnaire in the studio (regression:
# it fell straight through to the blank preview when the guided flow or
# provider resolution failed).
panel._resolve_active_provider = lambda: _FakeProvider()
panel._begin_guided_generation('chess')
pump()

# Assert during the asynchronous thinking screen, before any question has
# rendered. The old regression test only checked afterward and missed the
# visible sidebar flash.
assert panel._guided_running
assert panel._sidebar_visible is False
assert not panel._sidebar_revealer.get_reveal_child()
assert not panel._sidebar_revealer.get_visible()

questions_release.set()

ok = False
for _ in range(400):
    pump()
    if (panel._stack.get_visible_child_name() == 'studio' and
            panel._studio_mode_stack.get_visible_child_name() == 'guided'):
        labels = all_label_text(panel._guided_body)
        if any('Who plays' in text for text in labels):
            ok = True
            break
    time.sleep(0.01)

assert ok, 'guided questions did not render after Send'
assert panel._sidebar_visible is False
assert not panel._sidebar_revealer.get_reveal_child()
assert not panel._sidebar_revealer.get_visible()
assert abs(panel._inner_paned.get_position() -
           panel._inner_paned.get_allocated_width()) <= 1, (
    panel._inner_paned.get_position(),
    panel._inner_paned.get_allocated_width())

# While the questionnaire is open the studio tabs are locked so the user
# cannot navigate away from the questions mid-answer.
assert not panel._studio_preview_tab.get_sensitive()
assert not panel._studio_review_tab.get_sensitive()
assert all(not pill.get_sensitive() for pill in panel._studio_action_pills)

# On the studio the content fills top-to-bottom (no floating margins).
assert panel._content_alignment.get_property('yscale') == 1.0, \\
    panel._content_alignment.get_property('yscale')

panel.destroy()
window.destroy()
print('OFFSCREEN-GUIDED-TRIGGER-OK')
'''


_OFFSCREEN_CHAT_AVATAR_SCRIPT = '''
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from ui.panel import CreateAIActivityPanel


def pump():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def all_label_text(widget):
    texts = []
    getter = getattr(widget, 'get_children', None)
    if getter is None:
        return texts
    for child in getter():
        if isinstance(child, Gtk.Label):
            texts.append(child.get_text())
        texts.extend(all_label_text(child))
    return texts


window = Gtk.OffscreenWindow()
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
pump()

# An AI message is presented as "Sparky" with the round drawn avatar.
panel._add_chat_bubble('Hello there!', from_user=False, scroll=False)
pump()
labels = all_label_text(panel._chat_messages_box)
assert 'Sparky' in labels, labels

# The thinking indicator also carries the Sparky avatar/name.
row = panel._show_typing_bubble(panel._chat_messages_box, None)
pump()
assert row is not None
typing_labels = all_label_text(row)
assert any('Sparky' in text for text in typing_labels), typing_labels
assert any('thinking' in text for text in typing_labels), typing_labels
assert getattr(row, '_typing_dots', None) is not None
panel._remove_typing_bubble(row)

panel.destroy()
window.destroy()
print('OFFSCREEN-CHAT-AVATAR-OK')
'''


_OFFSCREEN_STEPS_SCRIPT = '''
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from ui.panel import CreateAIActivityPanel


def pump():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def all_label_text(widget):
    texts = []
    getter = getattr(widget, 'get_children', None)
    if getter is None:
        return texts
    for child in getter():
        if isinstance(child, Gtk.Label):
            texts.append(child.get_text())
        texts.extend(all_label_text(child))
    return texts


window = Gtk.OffscreenWindow()
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
pump()

panel._start_generation_steps()
pump()
labels = all_label_text(panel._chat_messages_box)
assert 'Thinking through your idea' in labels, labels
assert 'Building your activity' in labels, labels
assert 'Getting it ready to play' in labels, labels

# Advancing to code generation marks earlier steps done and this one active.
panel._update_generation_steps('generating')
pump()
assert panel._step_rows['planning']._step_state == 'done'
assert panel._step_rows['grounding']._step_state == 'done'
assert panel._step_rows['writing']._step_state == 'active'
assert panel._step_rows['packaging']._step_state == 'pending'

# The active step is emphasised and a live sub-status reflects the work.
assert panel._step_labels['writing'].get_style_context().has_class(
    'create-ai-step-label-active')
panel._set_step_substatus('Writing with the model…')
pump()
assert panel._step_sub_label.get_text() == 'Writing with the model…'

# Finishing marks everything done and flips the name to Done.
panel._finish_generation_steps()
pump()
assert all(icon._step_state == 'done'
           for icon in panel._step_rows.values())
assert any('Done' in text for text in all_label_text(panel._step_widget))

panel.destroy()
window.destroy()
print('OFFSCREEN-STEPS-OK')
'''


_OFFSCREEN_LEARNING_SCRIPT = '''
import time
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk

from ui.panel import CreateAIActivityPanel
from core.spec import ActivitySpec
from generation.generator import enrich_plan
from generation.templates import render_activity_source
from sugar3.graphics.toolbutton import ToolButton


def pump():
    for unused_index in range(20):
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.002)


def walk(widget):
    yield widget
    getter = getattr(widget, 'get_children', None)
    if getter is None:
        return
    for child in getter():
        yield from walk(child)


def all_label_text(widget):
    return [item.get_text() for item in walk(widget)
            if isinstance(item, Gtk.Label)]


class FakeResult:
    def __init__(self, source, plan, spec):
        self.files = {'activity.py': source}
        self.plan = plan
        self.spec = spec
        self.provider = 'fake'
        self.model = 'fake-1'
        self.project_path = '/tmp/aod-fake'


window = Gtk.OffscreenWindow()
window.set_default_size(1024, 768)
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
pump()

assert panel._activity_tools_stack is not None
assert panel._activity_tools_stack.get_visible_child_name() == 'home'
home_labels = all_label_text(
    panel._activity_tools_stack.get_child_by_name('home'))
assert 'Change this activity' in home_labels, home_labels
assert 'Understand & reflect' in home_labels, home_labels
assert 'The activity keeps running safely.' in home_labels, home_labels
assert 'Fix a problem' not in home_labels, home_labels
assert 'Challenges' not in home_labels, home_labels
assert 'Annotations' not in home_labels, home_labels
assert isinstance(panel._sidebar_toggle_button, Gtk.Button)
assert not isinstance(panel._sidebar_toggle_button, ToolButton)
assert isinstance(panel._activity_tools_close_button, Gtk.Button)
assert not isinstance(panel._activity_tools_close_button, ToolButton)
assert all(isinstance(button, Gtk.Button) and
           not isinstance(button, ToolButton)
           for button in panel._activity_tools_back_buttons.values())
assert panel._sidebar_toggle_button.get_label() == '🔧 Change'
assert not panel._sidebar_toggle_button.get_sensitive()

spec = ActivitySpec('Fraction Quest', 'Make a fractions quiz.',
                    'logic_math', 'MIT')
plan = enrich_plan(spec, {'template': 'quiz', 'summary': 's',
                          'learner_goal': 'g',
                          'learner_steps': ['a', 'b', 'c']})
source = render_activity_source(spec, plan)
panel._generation_result = FakeResult(source, plan, spec)
panel._refresh_activity_tools()
panel._stack.set_transition_duration(0)
panel._stack.set_visible_child_name('studio')
pump()
assert window.get_allocated_width() <= 1024, window.get_allocated_width()
assert panel._sidebar_toggle_button.get_sensitive()
preview_width = panel._inner_paned.get_allocated_width()

# Every preview-toolbar control remains distinct at Sugar's 1024px canvas.
# Gtk.Box may allocate overlapping children when their minimum widths exceed
# the available preview width, so visibility alone does not prove this.
title_alloc = panel._preview_toolbar_title.get_allocation()
tools_alloc = panel._sidebar_toggle_button.get_allocation()
assert title_alloc.x + title_alloc.width <= tools_alloc.x, (
    title_alloc.x, title_alloc.width, tools_alloc.x, tools_alloc.width)

# Opening Activity Tools overlays the full-width preview; it is not a second
# Gtk.Paned child that can crush the generated activity.
panel._set_activity_tools_open(True)
pump()
assert panel._sidebar_visible
assert panel._sidebar_toggle_button.get_label() == '🔧 Change'
assert panel._sidebar_toggle_button.get_style_context().has_class(
    'create-ai-activity-tools-trigger-active')
assert panel._sidebar_revealer.get_reveal_child()
assert panel._studio_right_panel.get_parent() is panel._sidebar_revealer
assert panel._inner_paned.get_child2() is None
assert panel._inner_paned.get_allocated_width() == preview_width, (
    panel._inner_paned.get_allocated_width(), preview_width)
drawer_width = panel._studio_right_panel.get_allocated_width()
assert drawer_width <= int(preview_width * 0.60) + 1, (
    drawer_width, preview_width)
assert preview_width - drawer_width >= int(preview_width * 0.40) - 1, (
    drawer_width, preview_width)
assert panel._activity_tools_close_button.get_allocated_width() >= 40, \
    panel._activity_tools_close_button.get_allocated_width()
assert panel._activity_tools_close_button.get_allocated_height() >= 40, \
    panel._activity_tools_close_button.get_allocated_height()

event = type('Event', (), {'keyval': Gdk.KEY_Escape})()
assert panel._CreateAIActivityPanel__activity_tools_key_press_cb(
    panel, event)
pump()
assert not panel._sidebar_visible
panel._set_activity_tools_open(True)
assert panel._sidebar_visible

panel._show_activity_tools_page('understand')
pump()
assert panel._activity_tools_stack.get_visible_child_name() == 'understand'
overview = panel._activity_tools_understand_overview.get_children()
sections = panel._activity_tools_understand_sections.get_children()
assert len(overview) == 2, 'overview cards: %d' % len(overview)
understand_labels = all_label_text(
    panel._activity_tools_stack.get_child_by_name('understand'))
for expected in ('How this activity works', '1 · Try it',
                 'What did you discover?'):
    assert expected in understand_labels, (expected, understand_labels)
assert panel._activity_tools_reflection_step_progress.get_text() == '1 of 4'
assert not panel._activity_tools_reflection_step_back.get_sensitive()
for title in ('2 · Notice', '3 · Explain', '4 · Imagine'):
    panel._activity_tools_reflection_step_next.clicked()
    assert panel._activity_tools_reflection_step_title.get_text() == title
assert panel._activity_tools_reflection_step_next.get_label() == \
    'Write what you discovered ↓'
panel._activity_tools_reflection_step_back.clicked()
assert panel._activity_tools_reflection_step_title.get_text() == '3 · Explain'
panel._activity_tools_reflection_step_next.clicked()
assert len(sections) >= 5, 'code sections: %d' % len(sections)
assert not panel._activity_tools_code_revealer.get_reveal_child()
assert not panel._activity_tools_health_revealer.get_reveal_child()
panel._activity_tools_code_toggle.clicked()
assert panel._activity_tools_code_revealer.get_reveal_child()

# A reflection can be kept with this revision or turned into a reviewed
# change without exposing the generated machine prompt in the text field.
panel._activity_tools_reflection_text.get_buffer().set_text(
    'I got stuck when the answer feedback disappeared.')
panel._CreateAIActivityPanel__activity_tools_save_note_cb(None)
assert panel._get_activity_tools_reflections()[0]['content'].startswith(
    'I got stuck')
panel._activity_tools_reflection_text.get_buffer().set_text(
    'I would change the answer feedback.')
panel._CreateAIActivityPanel__activity_tools_note_to_change_cb(None)
assert panel._activity_tools_stack.get_visible_child_name() == 'change'
assert not panel._activity_tools_change_entry.get_text()
assert panel._activity_tools_selected_preset[0] == 'From your observation'

# A capability-aware quick change stays human-readable while its complete
# request remains internal, then the learner reviews before submission.
panel._show_activity_tools_page('change')
pump()
change_page = panel._activity_tools_stack.get_child_by_name('change')
panel._activity_tools_change_confirm.set_transition_duration(0)
make_harder = next(
    widget for widget in walk(change_page)
    if isinstance(widget, Gtk.Button) and
    widget.get_label() == 'Adjust challenge')
assert make_harder.get_allocated_height() >= 45
make_harder.clicked()
assert not panel._activity_tools_change_entry.get_text()
assert panel._activity_tools_selected_preset_label.get_text() == \
    'Selected: Adjust challenge'
panel._CreateAIActivityPanel__activity_tools_plan_change_cb(None)
pump()
assert panel._activity_tools_change_confirm.get_reveal_child()
summary = panel._activity_tools_change_summary.get_text()
assert 'whole activity' in summary, summary
assert 'working version stays safe' in summary, summary

# The initial focus handoff is useful, but it must not fire again and steal
# focus after the learner has already moved back to the request field.
panel._activity_tools_change_entry.grab_focus()
pump()
assert window.get_focus() is panel._activity_tools_change_entry
time.sleep(0.27)
pump()
assert window.get_focus() is panel._activity_tools_change_entry

# The revealed confirmation is brought into view on the constrained layout.
panel._focus_activity_tools_confirmation(
    panel._activity_tools_confirmation_serial)
adjustment = panel._activity_tools_change_scroll.get_vadjustment()
confirm_alloc = panel._activity_tools_change_confirm.get_allocation()
assert adjustment.get_value() > 0, adjustment.get_value()
assert confirm_alloc.y + confirm_alloc.height <= \
    adjustment.get_value() + adjustment.get_page_size() + 1, (
        confirm_alloc.y, confirm_alloc.height,
        adjustment.get_value(), adjustment.get_page_size())

# Editing after Review invalidates the snapshot. Apply may review the new
# value, but must never submit content that was not in the shown summary.
submitted = []
panel._submit_refinement_from_prompt = (
    lambda request, source='chat', display_refinement=None:
    submitted.append((request, source)))
panel._activity_tools_change_entry.set_text('Different unreviewed request')
assert not panel._activity_tools_change_confirm.get_reveal_child()
panel._CreateAIActivityPanel__activity_tools_apply_change_cb(None)
assert submitted == [], submitted
assert panel._activity_tools_change_confirm.get_reveal_child()

# A specifically selected preview target becomes available, but whole
# activity remains the safe default until the learner chooses otherwise.
panel._set_live_edit_target('button: Clear')
assert panel._activity_tools_selected_target.get_sensitive()
assert panel._activity_tools_whole_target.get_active()
panel._activity_tools_selected_target.set_active(True)
assert not panel._activity_tools_change_confirm.get_reveal_child()
# A scope change after Review is also not allowed to submit until reviewed.
panel._CreateAIActivityPanel__activity_tools_apply_change_cb(None)
assert submitted == [], submitted
panel._activity_tools_change_entry.set_text('Make the clear button larger')
panel._CreateAIActivityPanel__activity_tools_plan_change_cb(None)
panel._CreateAIActivityPanel__activity_tools_apply_change_cb(None)
assert submitted == [('Make the clear button larger', 'preview')], submitted

pump()
assert not panel._sidebar_visible
assert not panel._sidebar_revealer.get_reveal_child()

# Important-code cards navigate to the real activity.py review surface.
panel._set_activity_tools_open(True)
panel._show_activity_tools_page('understand')
pump()
section_button = panel._activity_tools_understand_sections.get_children()[0]
section_button.clicked()
pump()
assert panel._studio_mode_stack.get_visible_child_name() == 'review'
assert panel._current_review_file == 'activity_py'
assert not panel._sidebar_visible

# Destroy the panel first: see the note in _OFFSCREEN_SCRIPT above.
panel.destroy()
window.destroy()
print('OFFSCREEN-ACTIVITY-TOOLS-OK')
'''


_OFFSCREEN_VERSIONS_SCRIPT = '''
import os
import tempfile

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from ui.panel import CreateAIActivityPanel
from service.sessions import AODRevision


def pump():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def _project(source):
    path = tempfile.mkdtemp(prefix='aod-ver-')
    with open(os.path.join(path, 'activity.py'), 'w') as handle:
        handle.write(source)
    return path


V1 = ('class GeneratedActivity:\\n'
      '    def __init__(self):\\n'
      '        pass\\n')
V2 = ('class GeneratedActivity:\\n'
      '    def __init__(self):\\n'
      '        pass\\n'
      '    def added_helper(self):\\n'
      '        return 1\\n')

r1 = AODRevision.create('job1', 'make a quiz',
                        {'project_path': _project(V1), 'activity_name': 'Quiz',
                         'provider': 'p', 'model': 'm', 'template': 'quiz'})
r2 = AODRevision.create('job2', 'add a helper',
                        {'project_path': _project(V2), 'activity_name': 'Quiz',
                         'provider': 'p', 'model': 'm', 'template': 'quiz'},
                        parent_revision_id=r1.revision_id)

window = Gtk.OffscreenWindow()
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
pump()

# Two real revisions: history, compare dropdowns, and a real diff.
panel._aod_session_id = 'test-session'
panel._get_session_revisions = lambda: [r1, r2]
panel._refresh_version_history()
pump()

assert len(panel._version_history_box.get_children()) == 2, 'history cards'
assert panel._version_compare_after.get_model().iter_n_children(None) == 2, \\
    'compare dropdown not populated'
assert panel._diff_after == r2.revision_id, 'after default not newest'
assert panel._diff_before == r1.revision_id, 'before default not parent'
assert panel._get_version_diff_pair() == (r1.revision_id, r2.revision_id)

lines = panel._get_version_diff_lines()
assert any(marker == '+' and 'added_helper' in text
           for marker, text in lines), 'added method missing from diff'

# One revision: nothing to compare.
panel._get_session_revisions = lambda: [r1]
panel._refresh_version_history()
pump()
assert not panel._version_compare_before.get_sensitive(), 'compare not disabled'
assert panel._get_version_diff_pair() == ('', ''), 'unexpected diff pair'

# No session: honest empty state, no fabricated versions.
panel._aod_session_id = ''
panel._get_session_revisions = lambda: []
panel._refresh_version_history()
pump()
assert panel._get_version_history() == [], 'fabricated placeholder versions'

# Destroy the panel first: see the note in _OFFSCREEN_SCRIPT above.
panel.destroy()
window.destroy()
print('OFFSCREEN-VERSIONS-OK')
'''


_OFFSCREEN_PREVIEW_KEYS_SCRIPT = '''
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk

from ui.panel import CreateAIActivityPanel


def pump():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


class FakeActivity:
    def __init__(self):
        self.emitted = []

    def emit(self, signal, event):
        self.emitted.append((signal, event.type, event.keyval))


class FakeEvent:
    def __init__(self, etype):
        self.type = etype
        self.keyval = Gdk.KEY_Up
        self.state = Gdk.ModifierType.CONTROL_MASK


window = Gtk.OffscreenWindow()
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel.reset_view()
pump()

forward = panel._CreateAIActivityPanel__preview_key_event_cb

# Key presses/releases are forwarded to the previewed activity instance so
# handlers connected on the activity window (self) fire even though that
# window is never shown in the preview.
panel._live_preview_activity = FakeActivity()
assert forward(None, FakeEvent(Gdk.EventType.KEY_PRESS)) is False
assert forward(None, FakeEvent(Gdk.EventType.KEY_RELEASE)) is False
assert panel._live_preview_activity.emitted == [
    ('key-press-event', Gdk.EventType.KEY_PRESS, Gdk.KEY_Up),
    ('key-release-event', Gdk.EventType.KEY_RELEASE, Gdk.KEY_Up),
], panel._live_preview_activity.emitted

# No previewed activity: forwarding is a safe no-op, never raises.
panel._live_preview_activity = None
assert forward(None, FakeEvent(Gdk.EventType.KEY_PRESS)) is False

# Focus helper is a safe no-op when there is no canvas.
panel._live_preview_canvas = None
assert panel._focus_live_preview_canvas() is False

panel.destroy()
window.destroy()
print('OFFSCREEN-PREVIEW-KEYS-OK')
'''


@unittest.skipUnless(
    _gtk_display_available(), 'needs a usable display server')
class TestStudioOffscreen(unittest.TestCase):

    def _run_offscreen(self, script):
        clean_env = _clean_gtk_env()
        try:
            return subprocess.run(
                [sys.executable, '-c', script],
                cwd=REPO_ROOT,
                env=clean_env,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired as expired:
            self.fail('offscreen script timed out:\n%s\n%s'
                      % (expired.stdout, expired.stderr))

    def test_home_gallery_empty_state_and_refresh(self):
        completed = self._run_offscreen(_OFFSCREEN_HOME_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen home test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-HOME-OK', completed.stdout)

    def test_panel_starts_on_home_and_survives_lifecycle(self):
        # Sanitized-env subprocess: snap/IDE shells leak
        # LD_LIBRARY_PATH/GTK_PATH values that make GTK hang, and a
        # subprocess isolates GTK state from other tests.
        completed = self._run_offscreen(_OFFSCREEN_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen smoke failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-OK', completed.stdout)

    def test_ask_bar_submits_in_both_modes(self):
        completed = self._run_offscreen(_OFFSCREEN_ASK_BAR_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'ask bar test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-ASKBAR-OK', completed.stdout)

    def test_live_edit_targets_a_precise_canvas_point(self):
        completed = self._run_offscreen(_OFFSCREEN_TARGET_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen target test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-TARGET-OK', completed.stdout)

    def test_guided_flow_renders_and_builds(self):
        completed = self._run_offscreen(_OFFSCREEN_GUIDED_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen guided test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-GUIDED-OK', completed.stdout)

    def test_activity_tools_has_two_directions_and_safe_change_review(self):
        completed = self._run_offscreen(_OFFSCREEN_LEARNING_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen Activity Tools test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-ACTIVITY-TOOLS-OK', completed.stdout)

    def test_versions_compare_uses_real_revisions(self):
        completed = self._run_offscreen(_OFFSCREEN_VERSIONS_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen versions test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-VERSIONS-OK', completed.stdout)

    def test_preview_forwards_keys_to_activity(self):
        completed = self._run_offscreen(_OFFSCREEN_PREVIEW_KEYS_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen preview-keys test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-PREVIEW-KEYS-OK', completed.stdout)

    def test_guided_flow_triggers_on_send_and_studio_fills(self):
        completed = self._run_offscreen(_OFFSCREEN_GUIDED_TRIGGER_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen guided trigger test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-GUIDED-TRIGGER-OK', completed.stdout)

    def test_chat_ai_messages_carry_mr_john_avatar(self):
        completed = self._run_offscreen(_OFFSCREEN_CHAT_AVATAR_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen chat avatar test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-CHAT-AVATAR-OK', completed.stdout)

    def test_generation_step_list_advances_and_completes(self):
        completed = self._run_offscreen(_OFFSCREEN_STEPS_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen steps test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-STEPS-OK', completed.stdout)

    def test_prompt_activity_name_updates_spec_name(self):
        completed = self._run_offscreen(_OFFSCREEN_PROMPT_NAME_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen prompt activity name test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-PROMPT-NAME-OK', completed.stdout)

    def test_install_setup_applies_name_and_license_without_icon_controls(self):
        completed = self._run_offscreen(_OFFSCREEN_INSTALL_SETUP_SCRIPT)
        self.assertEqual(
            0, completed.returncode,
            'offscreen install setup test failed:\n%s%s'
            % (completed.stdout, completed.stderr))
        self.assertIn('OFFSCREEN-INSTALL-SETUP-OK', completed.stdout)


_OFFSCREEN_PROMPT_NAME_SCRIPT = '''
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from ui.panel import CreateAIActivityPanel
from core.spec import ActivitySpec

window = Gtk.OffscreenWindow()
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()

class MockResult:
    def __init__(self):
        self.spec = ActivitySpec('Old Name', 'prompt', 'category', 'MIT')
        self.bundle_path = '/tmp/fake.xo'

panel._generation_result = MockResult()

class MockNameDialog:
    def __init__(self, **kwargs):
        self._content = Gtk.VBox()
    def add_button(self, text, response_id):
        return Gtk.Button(label=text)
    def set_default_response(self, response_id):
        pass
    def set_decorated(self, decorated):
        pass
    def get_style_context(self):
        return Gtk.Button().get_style_context()
    def set_size_request(self, w, h):
        pass
    def get_content_area(self):
        return self._content
    def response(self, response_id):
        pass
    def run(self):
        def _find_entry(container):
            for child in container.get_children():
                if isinstance(child, Gtk.Entry):
                    return child
                if hasattr(child, 'get_children'):
                    found = _find_entry(child)
                    if found is not None:
                        return found
            return None
        entry = _find_entry(self._content)
        if entry is not None:
            entry.set_text('Super Fun Math')
        return Gtk.ResponseType.ACCEPT
    def destroy(self):
        pass

original_dialog = Gtk.Dialog
Gtk.Dialog = MockNameDialog

res = panel._prompt_activity_name()
assert res is True
assert panel._generation_result.spec.name == 'Super Fun Math'
assert panel._generation_result.bundle_path == ''

Gtk.Dialog = original_dialog
panel.destroy()
window.destroy()
print('OFFSCREEN-PROMPT-NAME-OK')
'''


_OFFSCREEN_INSTALL_SETUP_SCRIPT = '''
import os
import shutil
import tempfile

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from core.spec import ActivitySpec
from generation.generator import create_prototype_activity
from ui.panel import CreateAIActivityPanel


def walk(widget):
    yield widget
    getter = getattr(widget, 'get_children', None)
    if getter is None:
        return
    for child in getter():
        yield from walk(child)


project_root = tempfile.mkdtemp(prefix='aod-install-setup-test-')
result = create_prototype_activity(
    ActivitySpec(
        'Old Garden', 'Create a garden drawing activity.',
        'creation', 'MIT', template='canvas'),
    project_root,
)

window = Gtk.OffscreenWindow()
panel = CreateAIActivityPanel()
window.add(panel)
window.show_all()
panel._generation_result = result

original_run = Gtk.Dialog.run

original_icon = result.files['activity/activity.svg']
Gtk.Dialog.run = lambda dialog: Gtk.ResponseType.CANCEL
cancelled = panel._prompt_install_setup()
assert not cancelled
assert result.spec.name == 'Old Garden', result.spec.name
assert result.spec.license_id == 'MIT', result.spec.license_id
assert result.files['activity/activity.svg'] == original_icon


def mock_run(dialog):
    widgets = list(walk(dialog.get_content_area()))
    labels = [widget.get_text() for widget in widgets
              if isinstance(widget, Gtk.Label)]
    assert '1  Name your activity' in labels, labels
    assert '2  Choose a license' in labels, labels
    assert '3  Review your activity icon' not in labels, labels
    assert 'Regenerate with AI' not in labels, labels

    entry = next(widget for widget in widgets
                 if isinstance(widget, Gtk.Entry))
    entry.set_text('My Garden Lab')
    license_combo = next(widget for widget in widgets
                         if isinstance(widget, Gtk.ComboBoxText))
    license_combo.set_active_id('GPL-3.0-or-later')
    assert not any(isinstance(widget, Gtk.ColorButton) for widget in widgets)
    return Gtk.ResponseType.ACCEPT


Gtk.Dialog.run = mock_run
try:
    accepted = panel._prompt_install_setup()
finally:
    Gtk.Dialog.run = original_run

assert accepted
assert result.spec.name == 'My Garden Lab', result.spec.name
assert result.spec.license_id == 'GPL-3.0-or-later', result.spec.license_id
info = result.files['activity/activity.info']
assert 'name = My Garden Lab' in info, info
assert 'license = GPL-3.0-or-later' in info, info
icon = result.files['activity/activity.svg']
assert icon == original_icon
assert result.bundle_path == '', result.bundle_path

panel.destroy()
window.destroy()
shutil.rmtree(project_root)
print('OFFSCREEN-INSTALL-SETUP-OK')
'''


if __name__ == '__main__':
    unittest.main()
