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
from generation.known_repairs import find_known_api_issues


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
    'time',
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
    for node in activity_class.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (
            node.target,)
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            state_name = target.id.lower()
            if state_name in (
                    'keys_held', 'keys_pressed', 'key_state',
                    'pressed_keys'):
                report.errors.append(
                    'Keyboard state `%s` must be initialized on each activity '
                    'instance (for example `self.%s = {}` in __init__ or a '
                    'reset method), not shared as mutable class state.' % (
                        target.id, target.id))
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

    # Fail exact GTK/Sugar API mismatches before the preview subprocess
    # crashes. Saved drafts can correct the same issues locally.
    report.errors.extend(find_known_api_issues(source))

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
    """Report best-effort Sugar interface guidance without blocking output.

    The gate intentionally avoids judging request-specific cairo artwork.
    It checks the surrounding activity chrome and interaction structure:
    Sugar sizing/theme APIs, helpful control palettes/tooltips, Sugar toolkit
    controls, and the absence of the generic web-card skin that previously
    overrode every generated UI.
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
    uses_tooltips = (
        'tooltip_text' in source_lower
        or 'set_tooltip_markup' in source_lower
        or 'set_tooltip(' in source_lower)
    uses_sugar_sizing = any(signal in source_lower for signal in (
        'style.zoom(', 'style.grid_cell_size', 'style.default_spacing',
        'style.default_padding', 'style.standard_icon_size',
        'style.small_icon_size', 'style.large_icon_size'))
    uses_sugar_controls = any(signal in source_lower for signal in (
        'sugar3.graphics.toolbutton',
        'sugar3.graphics.toggletoolbutton',
        'sugar3.graphics.radiotoolbutton',
        'sugar3.graphics.colorbutton',
        'sugar3.graphics.palette',
        'sugar3.graphics.alert',
        'sugar3.graphics.icon'))

    missing = []
    if not uses_sugar_style:
        missing.append('sugar3.graphics.style')
    if not uses_sugar_sizing:
        missing.append('Sugar grid/spacing/icon-size constants')
    if not uses_tooltips:
        missing.append('tooltips or Sugar palettes for interactive controls')
    if not uses_sugar_controls:
        missing.append('Sugar toolkit controls beyond the activity shell')

    if missing:
        report.warnings.append(
            'The activity UI is not Sugar-native across the whole interface; '
            'it is missing %s. Keep the learner workspace dominant, use '
            'Sugar style sizing/theme constants throughout the layout, use '
            'sugar3 graphics controls for activity chrome, and give '
            'interactive controls palettes or tooltips. Do not replace the '
            'UI with a generic card/dashboard skin.' % ', '.join(missing))

    # Reference pixels may intentionally settle a framed, multi-panel, or
    # text-action composition. Those target-region decisions outrank generic
    # visual cleanup. Structural Sugar API/style checks above still apply;
    # the vision prompt and provider-visible pixels own fidelity.
    reference_settled = (
        'reference image brief' in _spec_request_text(spec).lower())

    generic_web_skin = any(signal in source_lower for signal in (
        '.aod-card',
        'box-shadow:',
        '#2f6fb0',
        'automatic visual polish',
    ))
    if generic_web_skin and not reference_settled:
        report.warnings.append(
            'The activity UI is not Sugar-native: it contains a generic '
            'card/dashboard brand skin. Remove card shadows and brand-blue '
            'chrome, let the Sugar GTK theme style normal widgets, and use '
            'style.COLOR_* only for request-specific custom visuals.')

    fixed_side_regions = set(re.findall(
        r'(?m)^\s*(?:self\.)?'
        r'([a-z_][a-z0-9_]*(?:panel|sidebar)[a-z0-9_]*)'
        r'\.set_size_request\(\s*[^,\n]+,\s*-1\s*\)',
        source_lower,
    ))
    if len(fixed_side_regions) >= 2 and not reference_settled:
        report.warnings.append(
            'The activity UI is not Sugar-native: it creates multiple '
            'fixed-width persistent panels/sidebars (%s), which crowds the '
            'learner workspace. Keep the work surface dominant; move primary '
            'actions into ToolbarBox, contextual controls into Sugar '
            'palettes/sub-toolbars, and retain at most one compact panel or '
            'tray when its contents must stay visible.' %
            ', '.join(sorted(fixed_side_regions)))

    if 'gtk.toolbutton(' in source_lower:
        report.warnings.append(
            'The activity UI is not Sugar-native: use '
            'sugar3.graphics.toolbutton.ToolButton for toolbar actions '
            'instead of raw Gtk.ToolButton.')

    frame_count = len(re.findall(r'\bGtk\.Frame\s*\(', source))
    if frame_count >= 4 and not reference_settled:
        report.warnings.append(
            'The activity UI is visually fragmented: it creates %d separate '
            'Gtk.Frame regions. Do not box every instruction, requirement, '
            'setting, and status value. Keep one dominant learner workspace, '
            'group secondary information with Sugar spacing/separators, and '
            'use at most one compact contextual tray or status region.'
            % frame_count)

    primary_canvas_actions = []
    for label in _raw_gtk_button_labels(source):
        normalized = re.sub(r'[^a-z]+', ' ', label.lower()).strip()
        if any(normalized == action or normalized.startswith(action + ' ')
               for action in (
                   'check', 'clear', 'hint', 'new', 'next', 'pause', 'play',
                   'redo', 'reset', 'restart', 'undo')):
            primary_canvas_actions.append(label)
    if primary_canvas_actions and not reference_settled:
        report.warnings.append(
            'Primary activity actions must not be raw text Gtk.Buttons in '
            'the learner workspace (%s). Put these repeated actions in '
            'ToolbarBox as Sugar ToolButtons with real Sugar Artwork icons '
            'and tooltips; keep task-content answer/choice buttons in the '
            'workspace.' % ', '.join(sorted(set(primary_canvas_actions))))


def _raw_gtk_button_labels(source):
    """Return literal labels assigned directly to Gtk.Button constructors."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    labels = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _base_name(node.func) != \
                'Gtk.Button':
            continue
        for keyword in node.keywords:
            if keyword.arg != 'label':
                continue
            value = keyword.value
            if isinstance(value, ast.Call) and value.args \
                    and _call_name(value.func) == '_':
                value = value.args[0]
            if isinstance(value, ast.Constant) \
                    and isinstance(value.value, str):
                labels.append(value.value)
    return labels


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
