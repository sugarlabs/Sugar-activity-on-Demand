# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import unittest
from unittest import mock

from generation.generator import enrich_plan
from generation.runtime_check import run_runtime_check
from generation.runtime_check import _REPO_ROOT
from generation.templates import render_activity_source
from core.spec import ActivitySpec

_HAVE_DISPLAY = bool(
    os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def _template_source():
    spec = ActivitySpec(
        'Runtime Probe',
        'Make a fractions quiz.',
        'logic_math',
        'MIT',
    )
    plan = enrich_plan(spec, {
        'template': 'quiz',
        'summary': 'Runtime check probe.',
        'learner_goal': 'Practice fractions.',
        'learner_steps': ['Try', 'Explain', 'Share'],
    })
    return render_activity_source(spec, plan)


class TestRuntimeCheck(unittest.TestCase):

    def _skip_if_runtime_unavailable(self, ok, detail):
        if ok and detail.startswith(
                'skipped: runtime infrastructure unavailable'):
            self.skipTest(detail)

    def test_disabled_by_env_is_skipped(self):
        with mock.patch.dict(os.environ, {'AOD_RUNTIME_CHECK': 'off'}):
            ok, detail = run_runtime_check('raise SystemExit(1)\n')
        self.assertTrue(ok)
        self.assertEqual('skipped: disabled', detail)

    def test_no_display_is_skipped(self):
        env = {key: value for key, value in os.environ.items()
               if key not in ('DISPLAY', 'WAYLAND_DISPLAY')}
        env['AOD_RUNTIME_CHECK'] = 'on'
        with mock.patch.dict(os.environ, env, clear=True):
            ok, detail = run_runtime_check('raise SystemExit(1)\n')
        self.assertTrue(ok)
        self.assertEqual('skipped: no display', detail)

    def test_stale_display_is_an_infrastructure_skip(self):
        unavailable = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout='',
            stderr='Gtk-WARNING **: cannot open display: :stale',
        )
        env = {
            'AOD_RUNTIME_CHECK': 'on',
            'DISPLAY': ':stale',
        }
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch('generation.runtime_check.subprocess.run',
                           return_value=unavailable) as run:
            ok, detail = run_runtime_check('raise SystemExit(1)\n')

        self.assertTrue(ok)
        self.assertTrue(detail.startswith(
            'skipped: runtime infrastructure unavailable:'), detail)
        self.assertIn('cannot open display', detail)
        # The generated source is never run when the independent probe fails.
        self.assertEqual(1, run.call_count)

    def test_stale_wayland_display_is_an_infrastructure_skip(self):
        unavailable = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout='',
            stderr='Failed to open Wayland display wayland-stale',
        )
        env = {
            'AOD_RUNTIME_CHECK': 'on',
            'WAYLAND_DISPLAY': 'wayland-stale',
        }
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch('generation.runtime_check.subprocess.run',
                           return_value=unavailable):
            ok, detail = run_runtime_check('raise SystemExit(1)\n')

        self.assertTrue(ok)
        self.assertTrue(detail.startswith(
            'skipped: runtime infrastructure unavailable:'), detail)
        self.assertIn('Wayland display', detail)

    def test_wayland_runtime_does_not_force_x11_backend(self):
        probe = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='INFRASTRUCTURE-OK\n', stderr='')
        harness = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='RUNTIME-OK\n', stderr='')
        env = {
            'AOD_RUNTIME_CHECK': 'on',
            'WAYLAND_DISPLAY': 'wayland-0',
        }
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch('generation.runtime_check.subprocess.run',
                           side_effect=[probe, harness]) as run:
            ok, detail = run_runtime_check('pass\n')

        self.assertTrue(ok)
        self.assertEqual('passed', detail)
        self.assertEqual(2, run.call_count)
        for call in run.call_args_list:
            self.assertNotIn('GDK_BACKEND', call.kwargs['env'])

    def test_candidate_failure_fails_after_successful_probe(self):
        probe = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='INFRASTRUCTURE-OK\n', stderr='')
        harness = subprocess.CompletedProcess(
            args=[], returncode=1, stdout='',
            stderr='RuntimeError: candidate-broke')
        env = {
            'AOD_RUNTIME_CHECK': 'on',
            'DISPLAY': ':usable',
            'OPENAI_API_KEY': 'must-not-reach-generated-code',
        }
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch('generation.runtime_check.subprocess.run',
                           side_effect=[probe, harness]) as run:
            ok, detail = run_runtime_check('pass\n')

        self.assertFalse(ok)
        self.assertIn('candidate-broke', detail)
        for call in run.call_args_list:
            self.assertNotIn('OPENAI_API_KEY', call.kwargs['env'])

    def test_candidate_failure_redacts_local_checkout_path(self):
        probe = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='INFRASTRUCTURE-OK\n', stderr='')
        harness = subprocess.CompletedProcess(
            args=[], returncode=1, stdout='',
            stderr='File "%s/activity.py", line 10\n' % _REPO_ROOT)
        runtime_env = {'AOD_RUNTIME_CHECK': 'on', 'DISPLAY': ':usable'}
        with mock.patch.dict(os.environ, runtime_env, clear=True), \
                mock.patch('generation.runtime_check.subprocess.run',
                           side_effect=[probe, harness]):
            ok, detail = run_runtime_check('pass\n')

        self.assertFalse(ok)
        self.assertNotIn(_REPO_ROOT, detail)
        self.assertIn('<studio>/activity.py', detail)

    @unittest.skipUnless(_HAVE_DISPLAY, 'needs a display')
    def test_valid_template_source_passes(self):
        with mock.patch.dict(os.environ, {'AOD_RUNTIME_CHECK': 'on'}):
            ok, detail = run_runtime_check(
                _template_source(), 'Runtime Probe')
        self._skip_if_runtime_unavailable(ok, detail)
        self.assertTrue(ok, detail)
        self.assertEqual('passed', detail)

    @unittest.skipUnless(_HAVE_DISPLAY, 'needs a display')
    def test_crash_in_init_fails_with_traceback(self):
        source = _template_source()
        crashing = source.replace(
            'self._build_canvas()',
            'self._build_canvas()\n'
            '        raise RuntimeError("boom-at-runtime")',
            1,
        )
        self.assertNotEqual(source, crashing)
        with mock.patch.dict(os.environ, {'AOD_RUNTIME_CHECK': 'on'}):
            ok, detail = run_runtime_check(crashing, 'Runtime Probe')
        self._skip_if_runtime_unavailable(ok, detail)
        self.assertFalse(ok)
        self.assertIn('boom-at-runtime', detail)

    @unittest.skipUnless(_HAVE_DISPLAY, 'needs a display')
    def test_blocking_init_times_out(self):
        source = _template_source()
        blocking = source.replace(
            'self._build_canvas()',
            'self._build_canvas()\n'
            '        import time as _time\n'
            '        _time.sleep(120)',
            1,
        )
        self.assertNotEqual(source, blocking)
        with mock.patch.dict(os.environ, {'AOD_RUNTIME_CHECK': 'on'}):
            ok, detail = run_runtime_check(
                blocking, 'Runtime Probe', timeout=8)
        self._skip_if_runtime_unavailable(ok, detail)
        self.assertFalse(ok)
        self.assertIn('blocking loops', detail)


if __name__ == '__main__':
    unittest.main()
