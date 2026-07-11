# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run generated code before accepting it.

Static validation cannot see runtime crashes — code that imports
cleanly and has the right structure can still die in __init__ or in
its Journal methods.  This gate executes each candidate activity in a
isolated subprocess with a minimal environment (the same PreviewActivity path
the studio preview
uses) so a crash becomes retry feedback for the model instead of a
broken activity for the learner.
"""

import os
import shutil
import subprocess
import sys
import tempfile

_HARNESS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'runtime_harness.py')
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))

# Generated code runs with a minimal environment.  Besides preventing
# Snap/IDE library-path contamination, this keeps API keys, tokens, proxy
# credentials, and unrelated host configuration out of the subprocess.
_RUNTIME_ENV_ALLOWLIST = {
    'DBUS_SESSION_BUS_ADDRESS',
    'DISPLAY',
    'GDK_BACKEND',
    'HOME',
    'LANG',
    'LANGUAGE',
    'PATH',
    'TMPDIR',
    'USER',
    'WAYLAND_DISPLAY',
    'XAUTHORITY',
    'XDG_DATA_DIRS',
    'XDG_RUNTIME_DIR',
    'XDG_SESSION_TYPE',
}

_DETAIL_LINES = 15

# Keep this independent of generated source.  A display variable only says
# where GTK should try to connect; stale DISPLAY/WAYLAND_DISPLAY values are
# common in IDE and test shells.  Probing the same imports and GTK connection
# as the runtime harness lets us distinguish a broken candidate from a broken
# host environment before executing the candidate.
_INFRASTRUCTURE_PROBE = r'''
import sys
import traceback

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk

    result = Gtk.init_check()
    available = result[0] if isinstance(result, tuple) else result
    if not available:
        raise RuntimeError('GTK could not connect to the configured display')

    # The harness imports this before loading the generated activity.  Import
    # it here as well so missing Sugar/preview dependencies are infrastructure
    # failures, not repair feedback for otherwise valid generated code.
    from preview.runner import render_activity_preview  # noqa: F401
except BaseException:
    traceback.print_exc()
    sys.exit(1)

print('INFRASTRUCTURE-OK')
'''

_ACTIVITY_INFO = (
    '[Activity]\n'
    'name = %(name)s\n'
    'bundle_id = org.sugarlabs.aod.RuntimeCheck\n'
    'icon = activity\n'
    'exec = sugar-activity3 activity.GeneratedActivity\n'
    'activity_version = 1\n'
    'license = MIT\n'
)


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def run_runtime_check(source, name='Generated Activity', timeout=None):
    """Return (ok, detail); never raises.

    ok is True when the activity started, survived event pumping, and
    completed a Journal round-trip — or when the check cannot run here
    (no display / disabled), in which case detail says why it was
    skipped.
    """
    if os.environ.get('AOD_RUNTIME_CHECK', 'on').lower() in (
            'off', '0', 'no', 'false'):
        return True, 'skipped: disabled'
    if not (os.environ.get('DISPLAY')
            or os.environ.get('WAYLAND_DISPLAY')):
        return True, 'skipped: no display'

    if timeout is None:
        timeout = _env_int('AOD_RUNTIME_CHECK_TIMEOUT', 25)

    env = {
        key: value for key, value in os.environ.items()
        if key in _RUNTIME_ENV_ALLOWLIST or key.startswith('LC_')
    }
    env['PYTHONPATH'] = _REPO_ROOT

    infrastructure_problem = _probe_runtime_infrastructure(env, timeout)
    if infrastructure_problem is not None:
        return True, _infrastructure_skip_detail(infrastructure_problem)

    project_dir = tempfile.mkdtemp(prefix='aod-runtime-check-')
    try:
        os.makedirs(os.path.join(project_dir, 'activity'))
        with open(os.path.join(project_dir, 'activity.py'), 'w',
                  encoding='utf-8') as output:
            output.write(source)
        with open(os.path.join(project_dir, 'activity',
                               'activity.info'), 'w',
                  encoding='utf-8') as output:
            output.write(_ACTIVITY_INFO % {'name': name})

        try:
            completed = subprocess.run(
                [sys.executable, _HARNESS, project_dir],
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, (
                'The activity took longer than %d seconds to start. '
                'Remove blocking loops from __init__; drive animation '
                'and game loops with GLib.timeout_add instead.'
                % timeout)

        if completed.returncode == 0 and \
                'RUNTIME-OK' in completed.stdout:
            return True, 'passed'
        return False, _failure_detail(completed, project_dir)
    except Exception as error:
        # The gate itself failing must never block generation.
        return True, 'skipped: %s' % error
    finally:
        shutil.rmtree(project_dir, ignore_errors=True)


def _probe_runtime_infrastructure(env, timeout):
    """Return a host-runtime problem description, or None when usable."""
    try:
        completed = subprocess.run(
            [sys.executable, '-c', _INFRASTRUCTURE_PROBE],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 'GTK/Sugar startup probe timed out after %d seconds' % timeout
    except Exception as error:
        return str(error)

    if completed.returncode == 0 \
            and 'INFRASTRUCTURE-OK' in completed.stdout:
        return None
    return _process_detail(completed)


def _infrastructure_skip_detail(problem):
    prefix = 'skipped: runtime infrastructure unavailable'
    return '%s: %s' % (prefix, problem) if problem else prefix


def _failure_detail(completed, project_dir):
    return _process_detail(completed, project_dir)


def _process_detail(completed, project_dir=None):
    text = (completed.stderr or '') + '\n' + (completed.stdout or '')
    lines = [line for line in text.splitlines() if line.strip()]
    tail = lines[-_DETAIL_LINES:]
    detail = '\n'.join(tail)
    if project_dir:
        detail = detail.replace(project_dir, '<activity>')
    detail = detail.replace(_REPO_ROOT, '<studio>')
    home_path = os.path.expanduser('~')
    if home_path and home_path != os.path.sep:
        detail = detail.replace(home_path, '<home>')
    return detail or ('runtime check exited with code %d'
                      % completed.returncode)
