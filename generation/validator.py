# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import ast
import configparser
import importlib.util
from dataclasses import dataclass
from dataclasses import field
import os
import re
import zipfile

from sugar3.bundle.bundle import MalformedBundleException
from sugar3.bundle.helpers import bundle_from_archive
from sugar3.bundle.helpers import bundle_from_dir

from core.spec import LICENSE_IDS


ALLOWED_IMPORT_ROOTS = {
    'cairo',
    'datetime',
    'gettext',
    'gi',
    'json',
    'logging',
    'math',
    'pygame',
    'random',
    'sugar3',
    'sugargame',
}

# Allowed only when the runtime actually provides them.  pygame and
# sugargame are common in real Sugar games but are not installed
# everywhere; code importing a missing one would pass static checks and
# then crash in the preview and on launch.
OPTIONAL_RUNTIME_ROOTS = ('pygame', 'sugargame')

_module_availability = {}


def _module_available(root):
    if root not in _module_availability:
        try:
            _module_availability[root] = \
                importlib.util.find_spec(root) is not None
        except (ImportError, ValueError):
            _module_availability[root] = False
    return _module_availability[root]


FORBIDDEN_IMPORT_ROOTS = {
    'ctypes',
    'http',
    'multiprocessing',
    'os',
    'pathlib',
    'requests',
    'shutil',
    'socket',
    'subprocess',
    'urllib',
}

FORBIDDEN_CALLS = {
    '__import__',
    'compile',
    'eval',
    'exec',
    'globals',
    'locals',
}


@dataclass
class ValidationReport:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def valid(self):
        return not self.errors

    def extend(self, report):
        self.errors.extend(report.errors)
        self.warnings.extend(report.warnings)


def validate_source(source):
    report = ValidationReport()
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        report.errors.append(
            'Python syntax error on line %s: %s'
            % (error.lineno, error.msg)
        )
        return report

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split('.')[0])

    for name in sorted(imports):
        if name in FORBIDDEN_IMPORT_ROOTS:
            report.errors.append('Forbidden import: %s' % name)
        elif name not in ALLOWED_IMPORT_ROOTS:
            report.errors.append('Import is not allowlisted: %s' % name)
        elif name in OPTIONAL_RUNTIME_ROOTS and not _module_available(name):
            report.errors.append(
                "The '%s' library is not installed on this system; "
                'rewrite the activity with GTK3 + cairo instead — use a '
                'Gtk.DrawingArea draw callback with GLib.timeout_add for '
                'the frame loop and GTK key-press-event handlers for '
                'controls.' % name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name in FORBIDDEN_CALLS:
                report.errors.append('Forbidden call: %s' % call_name)

    # Names bound to sugar3's Activity via `from sugar3.activity.activity
    # import Activity` (including aliases) are as canonical as the
    # `activity.Activity` attribute style and must be accepted too.
    imported_activity_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and \
                node.module.startswith('sugar3.activity'):
            for alias in node.names:
                if alias.name == 'Activity':
                    imported_activity_names.add(alias.asname or alias.name)

    activity_classes = [
        node for node in tree.body
        if all((
            isinstance(node, ast.ClassDef),
            any(_base_name(base).endswith('activity.Activity')
                or _base_name(base) in imported_activity_names
                for base in getattr(node, 'bases', ())),
        ))
    ]
    if len(activity_classes) != 1:
        report.errors.append(
            'Generated source must define exactly one Activity subclass '
            '(subclass activity.Activity from sugar3.activity, or Activity '
            'imported from sugar3.activity.activity).'
        )
        return report

    activity_class = activity_classes[0]
    methods = {
        node.name: node for node in activity_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for required in ('__init__', 'read_file', 'write_file'):
        if required not in methods:
            report.errors.append('Missing required method: %s' % required)

    calls = {
        _call_name(node.func) for node in ast.walk(activity_class)
        if isinstance(node, ast.Call)
    }
    for required_call in ('set_canvas', 'set_toolbar_box'):
        if not any(name.endswith(required_call) for name in calls):
            report.errors.append(
                'Generated activity must call %s().' % required_call
            )

    if 'StopButton' not in source:
        report.errors.append('Generated activity must include a StopButton.')
    if 'ToolbarBox' not in source:
        report.errors.append('Generated activity must include a ToolbarBox.')

    invalid_api_calls = {
        'add_toolbar_button': (
            'ToolbarBox has no add_toolbar_button() method; insert items with '
            'toolbar_box.toolbar.insert(item, position).'
        ),
        'set_bounds': (
            'Gtk.Adjustment has no set_bounds() method; use set_lower() and '
            'set_upper().'
        ),
        'pattern_create_linear': (
            'cairo.Context has no pattern_create_linear() method (that is the '
            'C API). Build the gradient with cairo.LinearGradient(x0, y0, x1, '
            'y1), add stops with add_color_stop_rgb/rgba, then '
            'cr.set_source(gradient) — otherwise the draw handler raises '
            'AttributeError and the canvas stays blank.'
        ),
        'pattern_create_radial': (
            'cairo.Context has no pattern_create_radial() method (that is the '
            'C API). Use cairo.RadialGradient(cx0, cy0, r0, cx1, cy1, r1), add '
            'stops, then cr.set_source(gradient).'
        ),
    }
    # Scan the whole module, not just the Activity class: draw handlers and
    # helpers are often module-level functions.
    all_calls = {
        _call_name(node.func) for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    for call_name, message in invalid_api_calls.items():
        if any(name.endswith(call_name) for name in all_calls):
            report.errors.append(message)

    return report


def validate_activity_source_for_request(source, spec, plan=None):
    """Validate generated activity.py against the teacher's request.

    validate_source() checks the Sugar/Python safety contract.  This extra
    pass catches the common LLM failure mode where the source is technically
    valid but too generic to be the requested activity.
    """
    report = validate_source(source)
    if report.errors:
        return report

    request = _request_text(spec, plan)
    prompt = _spec_request_text(spec)
    prompt_words = _tokens(prompt)
    source_lower = source.lower()

    min_source_size = 1200
    if getattr(spec, 'code_size', 'standard') == 'compact':
        # Compact activities are intentionally small; only reject sizes
        # that cannot possibly hold a working Sugar activity.
        min_source_size = 800
    if len(source) < min_source_size:
        report.errors.append(
            'Generated activity is too small to be a full learner activity.'
        )

    # Trigger only on genuine drawing verbs.  Bare 'color'/'canvas'
    # phrasing ("name the color of each fruit") used to force a
    # DrawingArea onto activities that never needed one, hard-failing
    # valid candidates and thrashing the repair loop.
    if _has_any(prompt_words, (
            'draw', 'drawing', 'paint', 'painting', 'sketch')):
        _require_source_terms(
            report,
            source_lower,
            ('drawingarea',),
            'Drawing requests must use a Gtk.DrawingArea draw surface.',
        )
        _require_source_terms(
            report,
            source_lower,
            ('button-press-event', 'button_press_event',
             'motion-notify-event', 'motion_notify_event',
             'button-release-event', 'button_release_event',
             'eventmask', 'event_mask', 'add_events', 'add-events'),
            'Drawing requests must handle pointer events, not show a static '
            'sample image.',
        )
        _require_source_terms(
            report,
            source_lower,
            ('stroke', 'strokes', 'points', 'path', 'line', 'lines',
             'drawings', 'cairo'),
            'Drawing requests must store learner drawing state for Journal '
            'saving.',
        )

    # Bare 'two'/'student(s)' are audience or numeric phrasing ("a quiz
    # for my students", "two-digit addition"), not proof of a two-learner
    # activity; require an actual pairing phrase or pairing word.
    two_learner_request = (
        _has_any(prompt_words, (
            'pair', 'pairs', 'partner', 'partners', 'team', 'teams',
            'together', 'collaborative', 'collaboration')) or
        re.search(
            r'\b(two|2)\s+(players?|students?|learners?|kids|children|'
            r'teams?)\b',
            prompt.lower()) is not None
    )
    if two_learner_request:
        _require_source_terms(
            report,
            source_lower,
            ('student', 'learner', 'team', 'partner', 'player'),
            'Two-learner requests must show learner/team roles in the '
            'activity.',
        )
        _require_source_terms(
            report,
            source_lower,
            ('turn', 'switch', 'active', 'partner', 'together',
             'collaborat'),
            'Two-learner requests must include a turn, role, or '
            'collaboration workflow.',
        )

    if 'carrom' in prompt_words:
        _require_source_terms(
            report,
            source_lower,
            ('striker', 'pocket', 'coin', 'queen'),
            'Carrom requests must model a board with striker, pockets, '
            'coins, or queen state.',
        )
        _require_source_terms(
            report,
            source_lower,
            ('score', 'turn', 'foul'),
            'Carrom requests must include scoring, turns, or fouls.',
        )

    if 'chess' in prompt_words:
        _require_source_terms(
            report,
            source_lower,
            ('king', 'queen', 'rook', 'bishop', 'knight', 'pawn'),
            'Chess requests must model chess pieces, not a generic grid.',
        )
        _require_source_terms(
            report,
            source_lower,
            ('grid', 'board', 'square'),
            'Chess requests must include a visible 8x8 board or board '
            'state.',
        )

    if _has_any(prompt_words, ('quiz', 'question', 'questions')):
        _require_source_terms(
            report,
            source_lower,
            ('question', 'answer', 'feedback', 'score'),
            'Quiz requests must include questions, answers, feedback, or '
            'score state.',
        )
        _require_source_terms(
            report,
            source_lower,
            ('entry', 'textview', 'button'),
            'Quiz requests must provide learner input controls.',
        )

    if re.search(r'\b(todo|lorem ipsum|placeholder only)\b',
                 source_lower):
        report.errors.append(
            'Generated activity still contains placeholder text.'
        )

    _check_ui_quality(report, source, source_lower, spec)

    request_words = _tokens(request)
    overlap = request_words.intersection(_tokens(source))
    if request_words and len(overlap) < min(2, len(request_words)):
        report.warnings.append(
            'Generated source contains little vocabulary from the request.'
        )

    return report


def _check_ui_quality(report, source, source_lower, spec):
    """Reject only *clearly* unstyled activity UIs.

    High precision on purpose: the error fires only when the UI is plain on
    every axis at once -- no Sugar style, no CSS/style-context work, no
    tooltips, and no Pango markup -- and only for a substantial, interactive
    activity.  Any single styling touch clears the gate, so drawing-heavy or
    intentionally minimal activities are never trapped.  When it does fire,
    the error rides the normal repair loop, which makes the model add the
    missing Sugar-native styling.
    """
    if getattr(spec, 'code_size', 'standard') == 'compact':
        return
    if len(source) < 1500:
        return
    interactive = ('gtk.button', 'gtk.togglebutton', 'gtk.entry',
                   'gtk.combobox', 'gtk.scale', 'toolbutton(')
    if sum(source_lower.count(widget) for widget in interactive) < 2:
        return

    uses_sugar_style = (
        'sugar3.graphics.style' in source_lower
        or 'graphics import style' in source_lower
        or '.zoom(' in source_lower
        or 'icon_size' in source_lower
        or 'style.color_' in source_lower)
    uses_css = (
        'cssprovider' in source_lower
        or 'get_style_context' in source_lower
        or 'add_provider_for_screen' in source_lower)
    uses_tooltips = (
        'tooltip_text' in source_lower
        or 'set_tooltip_markup' in source_lower)
    uses_pango_markup = (
        'set_markup' in source_lower
        or 'pango' in source_lower
        or '<b>' in source_lower
        or '<span' in source_lower)

    if uses_sugar_style or uses_css or uses_tooltips or uses_pango_markup:
        return

    report.errors.append(
        'The activity UI is not Sugar-native: it uses none of '
        'sugar3.graphics.style, Gtk.CssProvider/get_style_context styling, '
        'widget tooltips, or Pango markup. Make it look like a real Sugar '
        'activity: import sugar3.graphics.style and use style.zoom(N) for '
        'spacing/margins and style.COLOR_* for colors; add tooltip_text to '
        'every button and entry; use Pango markup (<b>...</b>) for section '
        'titles via Gtk.Label.set_markup; and apply a Gtk.CssProvider with '
        'get_style_context().add_class(...) for panels. Keep all existing '
        'behavior and the GeneratedActivity class.')


def validate_project(project_path):
    report = ValidationReport()
    required_files = (
        'activity.py',
        'setup.py',
        'README.md',
        'LICENSE',
        'aod_plan.json',
        os.path.join('activity', 'activity.info'),
        os.path.join('activity', 'activity.svg'),
    )
    for relative_path in required_files:
        if not os.path.isfile(os.path.join(project_path, relative_path)):
            report.errors.append('Missing project file: %s' % relative_path)

    source_path = os.path.join(project_path, 'activity.py')
    if os.path.isfile(source_path):
        with open(source_path, encoding='utf-8') as source_file:
            report.extend(validate_source(source_file.read()))

    info_path = os.path.join(project_path, 'activity', 'activity.info')
    if os.path.isfile(info_path):
        report.extend(_validate_activity_info(info_path))

    try:
        if bundle_from_dir(project_path) is None:
            report.errors.append(
                'Sugar cannot recognize the project directory.')
    except MalformedBundleException as error:
        report.errors.append(
            'Sugar cannot recognize the project directory: %s' % error)

    return report


def validate_bundle(bundle_path):
    report = ValidationReport()
    if not os.path.isfile(bundle_path):
        report.errors.append('XO bundle does not exist.')
        return report

    try:
        bundle = bundle_from_archive(
            bundle_path,
            mime_type='application/vnd.olpc-sugar',
        )
        if bundle is None:
            report.errors.append('Sugar cannot recognize the XO bundle.')
            return report

        root = bundle.get_name().replace(' ', '') + '.activity/'
        with zipfile.ZipFile(bundle_path) as archive:
            names = archive.namelist()
        if not any(name.endswith('/activity/activity.info')
                   for name in names):
            report.errors.append(
                'XO bundle is missing activity/activity.info.'
            )
        if not any(name.endswith('/activity.py') for name in names):
            report.errors.append('XO bundle is missing activity.py.')
        if not all(name.startswith(root) for name in names):
            report.warnings.append(
                'XO root differs from the normalized activity name.'
            )
    except (OSError, ValueError, zipfile.BadZipFile,
            MalformedBundleException) as error:
        # sugar3 wraps zip errors and activity.info defects in
        # MalformedBundleException (a plain Exception subclass), which
        # used to escape this validator instead of becoming a report error.
        report.errors.append('Invalid XO bundle: %s' % error)

    return report


def _validate_activity_info(info_path):
    report = ValidationReport()
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(info_path, encoding='utf-8')
    except (configparser.Error, UnicodeDecodeError) as error:
        report.errors.append('Invalid activity.info: %s' % error)
        return report

    if not parser.has_section('Activity'):
        report.errors.append('activity.info is missing [Activity].')
        return report

    required = (
        'name',
        'bundle_id',
        'icon',
        'exec',
        'activity_version',
        'license',
    )
    for key in required:
        if not parser.get('Activity', key, fallback='').strip():
            report.errors.append('activity.info is missing %s.' % key)

    license_id = parser.get('Activity', 'license', fallback='')
    if license_id not in LICENSE_IDS:
        report.errors.append(
            'activity.info has an unsupported license: %s' % license_id
        )

    exec_line = parser.get('Activity', 'exec', fallback='')
    if not exec_line.startswith('sugar-activity3 '):
        report.errors.append(
            'activity.info must launch with sugar-activity3.'
        )

    return report


def _request_text(spec, plan):
    parts = [_spec_request_text(spec)]
    if isinstance(plan, dict):
        for key in (
                'activity_kind',
                'summary',
                'learner_goal',
                'interaction_model',
                'state_schema'):
            value = plan.get(key)
            if isinstance(value, str):
                parts.append(value)
        for key in (
                'learner_steps',
                'ui_regions',
                'features',
                'classroom_flow'):
            values = plan.get(key)
            if isinstance(values, list):
                parts.extend(str(value) for value in values)
    return ' '.join(part for part in parts if part)


def _spec_request_text(spec):
    return ' '.join((
        getattr(spec, 'prompt', ''),
        getattr(spec, 'name', ''),
        getattr(spec, 'learner_goal', ''),
    ))


def _tokens(value):
    ignored = {
        'a', 'an', 'and', 'app', 'activity', 'can', 'create', 'for', 'make',
        'me', 'of', 'please', 'the', 'to', 'where', 'with',
    }
    return {
        token for token in re.findall(r'[a-z0-9]+', value.lower())
        if token not in ignored and len(token) > 2
    }


def _has_any(words, candidates):
    return bool(words.intersection(candidates))


def _require_source_terms(report, source_lower, terms, message):
    # Prefix-anchored matching: a term must start at a word boundary so
    # 'turn' is found in 'turns'/'_turn' but never inside 'return', and
    # 'active' never matches inside 'interactive'.  Plain substring
    # matching made several of these requirements trivially true in any
    # Python source.
    if not any(
            re.search(r'(?<![a-z0-9])' + re.escape(term), source_lower)
            for term in terms):
        report.errors.append(message)


def _base_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return '%s.%s' % (_base_name(node.value), node.attr)
    return ''


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ''
