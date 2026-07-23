# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn a generated ``activity.py`` into learner-facing annotations and
reflection prompts.

The Reflective Studio is constructionist: the learner should not just
*receive* generated code but read, question, and own it.  This module reads
the draft source with :mod:`ast` and produces two lists the sidebar renders:

* ``sections`` — plain-language annotations for the major parts of a Sugar
  activity (imports, the Activity class, ``__init__``, the toolbar, the
  canvas, the Journal hooks), each with the line range it covers so the UI
  can point the learner at real code.
* ``reflections`` — targeted questions tied to the patterns actually present
  in the code, merged with the plan's ``assessment_prompts``.

Like the other guided helpers (:mod:`llm.clarify`, :mod:`llm.enhance`),
analysis is fail-soft: unparseable or non-string source yields empty lists
rather than raising, so a studio panel never breaks on a malformed draft.

The module depends only on the standard library so it stays trivial to test.
``_base_name``/``_call_name`` mirror the same-named helpers in
:mod:`generation.validator`, inlined here to avoid pulling in that module's
sugar3 import chain.
"""

import ast


# Plain-language explanations for each detected code section.
_EXPLAIN = {
    'imports': (
        'The libraries this activity builds on. gi and sugar3 bring in the '
        'GTK widgets and the Sugar activity toolkit; the rest are helpers '
        'like math or random.'),
    'activity_class': (
        'This is your activity. It inherits from Sugar\'s Activity base '
        'class, which already gives it a window, a place in the Journal, and '
        'a toolbar — you only add what makes this activity special.'),
    'init': (
        '__init__ runs once, the moment the activity opens. It builds the '
        'toolbar and the canvas and restores any work saved earlier.'),
    'toolbar': (
        'Every Sugar activity has a toolbar with a Stop button. This is '
        'where that bar and its buttons are created.'),
    'canvas': (
        'The canvas is the main area you see and interact with. set_canvas() '
        'tells Sugar which widget to show there.'),
    'journal': (
        'read_file and write_file are how Sugar remembers your work in the '
        'Journal — saving when you close the activity and restoring when you '
        'open it again.'),
}


# Reflection questions keyed on patterns detected in the code.  Each carries a
# "why" the UI reveals behind a small button.
_REFLECT = {
    'inherits': {
        'id': 'inherits',
        'question': (
            "This class inherits from Activity — what do you think "
            "'inherits' means, and what does the Activity base class give "
            "you for free?"),
        'why': (
            'Inheritance lets your activity reuse Sugar\'s window, toolbar, '
            'and Journal plumbing, so you only write the parts that make '
            'your activity unique.'),
    },
    'journal': {
        'id': 'journal',
        'question': (
            'read_file and write_file are how Sugar saves your work. What do '
            'you think would happen if you deleted write_file? Try it and '
            'see.'),
        'why': (
            'Without write_file nothing is written to the Journal, so your '
            'progress would be lost every time the activity closes.'),
    },
    'canvas': {
        'id': 'canvas',
        'question': (
            'Which widget is being used as the canvas here? What would you '
            'see if you swapped it for a different one?'),
        'why': (
            'The canvas is whatever widget you pass to set_canvas(); changing '
            'it changes the whole main area of the activity.'),
    },
    'toolbar': {
        'id': 'toolbar',
        'question': (
            'Look at the toolbar — why do you think every Sugar activity is '
            'required to have a Stop button?'),
        'why': (
            'The Stop button is how a learner cleanly closes an activity and '
            'returns to Sugar; making it consistent means it works the same '
            'in every activity.'),
    },
}


def analyze_source(source, plan=None):
    """Return ``{'sections': [...], 'reflections': [...]}`` for a draft.

    ``source`` is the generated ``activity.py`` text; ``plan`` is the optional
    generation plan whose ``assessment_prompts`` are merged into the
    reflections.  Fail-soft: unparseable or non-string source yields empty
    lists.
    """
    tree = _safe_parse(source)
    sections = []
    reflections = []
    if tree is not None:
        activity = _find_activity_class(tree)
        sections = _detect_sections(tree, activity)
        reflections = _detect_reflections(activity)
    reflections.extend(_plan_reflections(plan, reflections))
    return {'sections': sections, 'reflections': reflections}


def reflections_for_change(old_source, new_source):
    """Return up to two reflection prompts about a just-made modification.

    Compares the old and new ``activity.py`` and asks about what changed —
    edited text or a newly added method — so reflection is tied to the
    learner's own edit.  Fail-soft: returns ``[]`` when nothing notable
    changed or either source is unparseable.
    """
    prompts = []

    added_text = _string_literals(new_source) - _string_literals(old_source)
    if added_text:
        sample = sorted(added_text, key=len)[0]
        if len(sample) > 40:
            sample = sample[:40].rstrip() + '…'
        prompts.append({
            'id': 'changed_text',
            'question': (
                'You changed some wording (for example "%s"). What other '
                'text in the activity might you want to update so it all '
                'agrees?' % sample),
            'why': (
                'The same idea often appears in more than one place — a '
                'title, a label, and a message can all need to match.'),
        })

    added_defs = _method_names(new_source) - _method_names(old_source)
    if added_defs:
        prompts.append({
            'id': 'added_method',
            'question': (
                'A new method (%s) appeared. What calls it, and when does it '
                'run?' % sorted(added_defs)[0]),
            'why': (
                'A method only does something when something else calls it — '
                'following that thread is how you trace what the code does.'),
        })

    return prompts[:2]


def _detect_sections(tree, activity):
    sections = []

    imports = [node for node in tree.body
               if isinstance(node, (ast.Import, ast.ImportFrom))]
    if imports:
        sections.append(_section(
            'imports', 'Imports', imports[0].lineno,
            _end_line(imports[-1]), 'imports'))

    if activity is not None:
        sections.append(_section(
            'activity_class', 'Your activity class', activity.lineno,
            activity.lineno, 'activity_class'))

        methods = {node.name: node for node in activity.body
                   if isinstance(node, (ast.FunctionDef,
                                        ast.AsyncFunctionDef))}

        init = methods.get('__init__')
        if init is not None:
            sections.append(_section(
                'init', 'Setup (__init__)', init.lineno,
                _end_line(init), 'init'))

        toolbar_line = _first_call_line(
            activity, lambda name: name.endswith('set_toolbar_box'))
        if toolbar_line is None:
            toolbar_line = _first_call_line(
                activity, lambda name: name in ('ToolbarBox', 'StopButton'))
        if toolbar_line is not None:
            sections.append(_section(
                'toolbar', 'Toolbar', toolbar_line, toolbar_line, 'toolbar'))

        canvas_line = _first_call_line(
            activity, lambda name: name.endswith('set_canvas'))
        if canvas_line is not None:
            sections.append(_section(
                'canvas', 'Canvas', canvas_line, canvas_line, 'canvas'))

        journal = [methods[name] for name in ('read_file', 'write_file')
                   if name in methods]
        if journal:
            sections.append(_section(
                'journal', 'Journal save & restore',
                min(node.lineno for node in journal),
                max(_end_line(node) for node in journal), 'journal'))

    sections.sort(key=lambda section: section['line_start'])
    return sections


def _detect_reflections(activity):
    if activity is None:
        return []

    methods = {node.name for node in activity.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    calls = {_call_name(node.func) for node in ast.walk(activity)
             if isinstance(node, ast.Call)}

    reflections = [dict(_REFLECT['inherits'])]
    if 'read_file' in methods or 'write_file' in methods:
        reflections.append(dict(_REFLECT['journal']))
    if any(name.endswith('set_canvas') for name in calls):
        reflections.append(dict(_REFLECT['canvas']))
    if any(name.endswith('set_toolbar_box') for name in calls) or \
            'ToolbarBox' in calls or 'StopButton' in calls:
        reflections.append(dict(_REFLECT['toolbar']))
    return reflections


def _plan_reflections(plan, existing):
    if not isinstance(plan, dict):
        return []
    prompts = plan.get('assessment_prompts')
    if not isinstance(prompts, (list, tuple)):
        return []

    seen = {reflection['question'].strip().lower()
            for reflection in existing}
    out = []
    for index, prompt in enumerate(prompts):
        text = str(prompt).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append({'id': 'plan_%d' % index, 'question': text, 'why': ''})
    return out


def _find_activity_class(tree):
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and \
                node.module.startswith('sugar3.activity'):
            for alias in node.names:
                if alias.name == 'Activity':
                    imported.add(alias.asname or alias.name)

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for base in getattr(node, 'bases', ()):
                name = _base_name(base)
                if name.endswith('activity.Activity') or name in imported:
                    return node
    return None


def _first_call_line(scope, predicate):
    best = None
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name and predicate(name):
                if best is None or node.lineno < best:
                    best = node.lineno
    return best


def _section(section_id, title, line_start, line_end, explain_key):
    return {
        'id': section_id,
        'title': title,
        'line_start': line_start,
        'line_end': line_end,
        'explanation': _EXPLAIN[explain_key],
    }


def _end_line(node):
    return getattr(node, 'end_lineno', node.lineno)


def _string_literals(source):
    tree = _safe_parse(source)
    if tree is None:
        return set()
    return {
        node.value.strip()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value.strip()
    }


def _method_names(source):
    tree = _safe_parse(source)
    if tree is None:
        return set()
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _safe_parse(source):
    if not isinstance(source, str) or not source.strip():
        return None
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


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
