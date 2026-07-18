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


class TestStudioDecoupling(unittest.TestCase):

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


_OFFSCREEN_SCRIPT = '''
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

assert panel._stack.get_visible_child_name() == 'home', \\
    panel._stack.get_visible_child_name()

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

sugar_home = tempfile.mkdtemp(prefix='aod-studio-home-test-')
os.environ['SUGAR_HOME'] = sugar_home

import gi
gi.require_version('Gtk', '3.0')
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
assert panel._selected_options['enhance'] == 'on'

# "Create new" now opens the prompt directly (the MODIFY/CREATE chooser
# was removed), so the stack goes straight to the create view.
panel._CreateAIActivityPanel__home_create_new_cb(None)
pump()
assert panel._stack.get_visible_child_name() == 'create'

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

# Destroy the panel first: see the note in _OFFSCREEN_SCRIPT above.
panel.destroy()
window.destroy()
print('OFFSCREEN-HOME-OK')
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


if __name__ == '__main__':
    unittest.main()
