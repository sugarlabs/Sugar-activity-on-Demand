# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One self-review round over freshly generated activity code.

The generated source already passed static validation and the runtime
gate, so it works — but working code can still be shallow: buttons
without handlers, win conditions that never fire, Journal methods that
save nothing real.  This module asks the model to review its own
output once and return either OK or minimal SEARCH/REPLACE fixes.

The critic is strictly fail-safe.  The unpatched source is already
validated and runtime-proven, so on any doubt — unparseable reply,
failed patch, patched code failing validation or the runtime gate —
the original is kept and generation continues as if the critic had
said OK.
"""

import logging
import inspect
import os

from generation.refine import apply_patches
from generation.refine import parse_search_replace
from generation.repair_loop import patches_match_uniquely
from generation.repair_loop import patches_replace_whole_file
from generation.repair_loop import response_contains_only_patches
from generation.runtime_check import run_runtime_check
from generation.validator import validate_activity_source_for_request


def build_critic_system_prompt():
    return (
        'You are Sugar Activity on Demand, reviewing a Sugar activity '
        'you just wrote before it is given to a learner.\n\n'
        'Check the code against this list:\n'
        '- The learner request is the product definition. The activity must '
        'not contain invented math questions, number collecting, quizzes, '
        'vocabulary, assessment, reflection, explanation prompts, teacher '
        'flow, or partner roles unless the request, confirmed requirements, '
        'or reference image explicitly calls for them.\n'
        '- If the request contains a Reference image brief, reference '
        'fidelity overrides every generic layout preference below for the '
        'target activity region. Preserve its visible regions and controls '
        'one-for-one, approximate proportions, placement, ordering, palette '
        'relationships, and state. Never patch away or relocate target '
        'content merely to make it more conventionally Sugar-native; apply '
        'Sugar cleanup only to host chrome and unspecified details.\n'
        '- Every button, entry, and control is connected to a handler '
        'that does something visible.\n'
        '- For real-time games, the player character and controls are clear '
        'before play starts; input state belongs to the activity instance; '
        'damage never makes the player permanently disappear; and restart '
        'clears keys, entities, timers, win, and game-over state. Inspect '
        'every delayed/random entity and drawing branch, not just the first '
        'frame. A cairo.Context must never receive custom attributes such as '
        '`cr.ellipse`; use save/translate/scale/arc/restore instead.\n'
        '- The win / success / feedback logic is actually reachable by '
        'playing the activity.\n'
        '- write_file saves the real activity state and read_file '
        'restores it, so closing and reopening resumes the activity.\n'
        '- The learner can tell what to do: instructions or labels are '
        'visible on screen.\n'
        '- The complete UI is Sugar-native: the learner workspace dominates; '
        'primary actions use Sugar toolbar controls; contextual actions use '
        'palettes/sub-toolbars; persistent panels exist only when continuously '
        'relevant; spacing, colors, icons, and feedback use sugar3.graphics '
        'style/widgets.\n'
        '- The UI is also visually composed and calm: aligned Sugar spacing, '
        'sentence-case labels, compact consistent targets, no tall or '
        'stretched text action beside the workspace, and no separate bordered '
        'frame around every instruction, setting, requirement, and status.\n'
        '- Drawing/construction activities keep one dominant canvas, one '
        'concise challenge/status row, and at most one compact tool tray or '
        'contextual palette. Check/Play/Hint/Undo/Redo/Clear/Reset/Next are '
        'icon-and-tooltip toolbar actions rather than oversized canvas-side '
        'buttons.\n'
        '- The activity does not impose generic white cards, brand-blue '
        'headings, shadows, gradients, a web dashboard, or a permanent '
        'sidebar that crowds the learner canvas.\n'
        '- The interface remains usable at 1024x768, with allocation-driven '
        'boards/canvases and bounded wrapped labels.\n'
        '- Tool and mode selection changes actual interaction; undo/redo/reset '
        'state stays synchronized; success feedback is computed from learner '
        'state; resizing keeps drawing and hit testing aligned; and restored '
        'Journal state is immediately redrawn.\n'
        '- No dead code, placeholder text, or TODO stubs remain.\n\n'
        'Sugar-native appearance and visual polish are advisory. If the '
        'activity follows the learner prompt/reference and works correctly, '
        'reply OK even when its styling is not perfectly Sugar-native. Never '
        'patch a working activity solely for aesthetic conformity.\n\n'
        'If the code passes the whole list, reply with exactly:\n'
        'OK\n'
        '...and nothing else.\n\n'
        'Otherwise return ONLY minimal fixes as SEARCH/REPLACE blocks '
        'in this exact format:\n\n'
        '<<<<<<< SEARCH\n'
        '<exact lines from the current source to find>\n'
        '=======\n'
        '<replacement lines>\n'
        '>>>>>>> REPLACE\n\n'
        'Rules:\n'
        '- The SEARCH section must be copied EXACTLY from the current '
        'source, including indentation and whitespace.\n'
        '- Keep each SEARCH block small but unique (3-10 lines).\n'
        '- Fix only functional, safety, persistence, responsiveness, prompt, '
        'or reference-fidelity defects. Do not rename or rewrite working code '
        'and do not patch solely for Sugar-native styling.\n'
        '- FULLREGEN is not allowed here.  Never reply OK when a defect '
        'exists; express the highest-priority fix as focused patches.\n'
        '- Preserve all Sugar Activity patterns: ToolbarBox, '
        'StopButton, set_canvas, read_file/write_file, Journal '
        'persistence.\n'
        '- Keep the same class name GeneratedActivity.\n'
        '- Use only classroom-safe imports.  No networking, '
        'subprocesses, or filesystem access.\n'
    )


def build_critic_user_prompt(spec, plan, source, warnings=None):
    parts = [
        'Review the activity.py you generated for this request.\n\n',
        'Activity: %s\n' % getattr(spec, 'name', ''),
        'Request: %s\n' % getattr(spec, 'prompt', ''),
    ]
    summary = plan.get('summary') if isinstance(plan, dict) else None
    if summary:
        parts.append('Planned summary: %s\n' % summary)
    if warnings:
        parts.append('\nThe validator raised these concerns:\n')
        parts.extend('- %s\n' % warning for warning in warnings)
    parts.append('\nCurrent activity.py (%d lines):\n' % source.count('\n'))
    parts.append(source.rstrip())
    parts.append(
        '\n\n---\n\n'
        'Reply with exactly OK if the code passes the checklist, or '
        'with minimal SEARCH/REPLACE blocks copied EXACTLY from the '
        'source above.'
    )
    return ''.join(parts)


def run_critic_round(provider, spec, plan, source, warnings=None,
                     reference_image_data=None,
                     reference_image_mime_type=''):
    """Return the (possibly patched) source; never raises.

    Records the outcome in plan['critic']: 'ok' when the model found
    nothing to fix, 'patched:N' when N fixes were applied and the
    result re-passed validation and the runtime gate,
    'patched-unverified:N' when the runtime gate could not run and the
    patch therefore rests on static validation alone, 'skipped' in
    every other case.
    """
    plan['critic'] = 'skipped'

    if os.environ.get('AOD_CRITIC', 'on').lower() in (
            'off', '0', 'no', 'false'):
        return source
    generate_text = getattr(provider, 'generate_text', None)
    if not callable(generate_text):
        return source

    try:
        response = _request_critic_text(
            generate_text,
            build_critic_system_prompt(),
            build_critic_user_prompt(spec, plan, source, warnings),
            reference_image_data,
            reference_image_mime_type,
        )
    except Exception as error:
        logging.warning('Critic call failed: %s',
                        _redact_provider_error(error, provider))
        return source

    if not isinstance(response, str):
        logging.warning('Critic returned a non-text response')
        return source
    if response.strip() == 'OK':
        plan['critic'] = 'ok'
        return source
    if any(secret in response for secret in _provider_secrets(provider)):
        logging.warning('Critic reply contained credential material')
        return source
    if not response_contains_only_patches(response):
        logging.warning('Critic reply contained non-patch protocol text')
        return source

    try:
        patches = parse_search_replace(response)
    except ValueError:
        logging.warning('Critic reply was not OK or valid patches')
        return source
    if patches is None:  # FULLREGEN — forbidden for the critic.
        return source
    if patches_replace_whole_file(source, patches):
        logging.warning('Critic attempted a whole-file replacement')
        return source
    if not patches_match_uniquely(source, patches):
        logging.warning('Critic patch anchors were missing or ambiguous')
        return source

    patched, applied, failed = apply_patches(source, patches)
    if failed or not applied:
        logging.warning('Critic patches failed to apply (%d failed)', failed)
        return source

    report = validate_activity_source_for_request(patched, spec, plan)
    if not report.valid:
        logging.warning('Critic patch broke validation; keeping original')
        return source
    runtime_ok, runtime_detail = run_runtime_check(
        patched, getattr(spec, 'name', 'Generated Activity'))
    if not runtime_ok:
        logging.warning('Critic patch broke the runtime gate; '
                        'keeping original')
        return source

    # run_runtime_check also returns ok=True when it could not run at
    # all (no display, disabled, or the host probe failed); only the
    # detail tells the two apart.  Recording those as 'patched' would
    # claim the patch re-passed a gate that never executed.
    if runtime_detail.startswith('skipped'):
        logging.warning('Critic patch could not be runtime-verified (%s); '
                        'accepting on static validation alone',
                        runtime_detail)
        plan['critic'] = 'patched-unverified:%d' % applied
        return patched

    plan['critic'] = 'patched:%d' % applied
    return patched


def _request_critic_text(generate_text, system_prompt, user_prompt,
                         image_data, image_mime_type):
    """Let the final reviewer compare source against original pixels."""
    kwargs = {}
    try:
        parameters = inspect.signature(generate_text).parameters
    except (TypeError, ValueError):
        parameters = {}
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values())
    if isinstance(image_data, bytes) and image_data and \
            image_mime_type in ('image/png', 'image/jpeg'):
        for name, value in (
                ('image_data', image_data),
                ('image_mime_type', image_mime_type)):
            parameter = parameters.get(name)
            if accepts_kwargs or (
                    parameter is not None and
                    parameter.kind != inspect.Parameter.POSITIONAL_ONLY):
                kwargs[name] = value
    try:
        return generate_text(system_prompt, user_prompt, **kwargs)
    except Exception as error:
        if kwargs and type(error).__name__ == 'ProviderImageUnsupportedError':
            return generate_text(system_prompt, user_prompt)
        raise


def _provider_secrets(provider):
    values = []
    for name in ('_api_key', 'api_key'):
        value = getattr(provider, name, '')
        if isinstance(value, str) and value:
            values.append(value)
    return values


def _redact_provider_error(error, provider):
    message = str(error)
    for secret in _provider_secrets(provider):
        message = message.replace(secret, '[redacted]')
    return message
