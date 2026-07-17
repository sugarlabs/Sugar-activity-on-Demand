# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transactional repair loop for an existing generated activity.

This module deliberately has no full-generation fallback.  Every proposed
candidate must be derived from the current candidate through exact
SEARCH/REPLACE blocks.  Failed proposals are retained as snapshots for
diagnostics, but they do not replace the active candidate unless the caller's
verification result explicitly accepts the intermediate source.
"""

from dataclasses import dataclass
from dataclasses import field
import hashlib
import json
import math

from generation.focus import build_focused_view
from generation.refine import REPLACE_MARKER
from generation.refine import SEARCH_MARKER
from generation.refine import apply_patches
from generation.refine import parse_search_replace


@dataclass
class RepairCheckResult:
    """Result returned by a repair candidate verification callback.

    ``passed`` means the source is fully repaired.  A failed source is rolled
    back by default.  Set ``accept_candidate`` only when the source is a safe,
    useful intermediate improvement that should become the base of the next
    repair attempt.
    """

    passed: bool
    diagnostics: object = ''
    accept_candidate: bool = False


@dataclass
class RepairResult:
    """Final result and audit trail from :func:`repair_candidate`."""

    success: bool
    source: str
    diagnostics: object
    reason: str
    attempts: int
    history: list = field(default_factory=list)
    snapshots: dict = field(default_factory=dict)
    original_source_hash: str = ''

    @property
    def source_hash(self):
        return _source_hash(self.source)

    def to_dict(self):
        """Return a JSON-serializable representation of the result."""
        return {
            'success': self.success,
            'source_hash': self.source_hash,
            'original_source_hash': self.original_source_hash,
            'diagnostics': _json_safe(self.diagnostics),
            'reason': self.reason,
            'attempts': self.attempts,
            'history': _json_safe(self.history),
            'snapshots': dict(self.snapshots),
        }


def build_repair_system_prompt():
    """Return the strict, patch-only instruction for code repair."""
    return (
        'You are debugging an existing Sugar activity.py.  Repair the '
        'existing candidate in place; do not generate a replacement file.\n\n'
        'Return ONLY one or more exact SEARCH/REPLACE blocks in this '
        'format:\n\n'
        '<<<<<<< SEARCH\n'
        '<exact lines copied from the current candidate>\n'
        '=======\n'
        '<replacement lines>\n'
        '>>>>>>> REPLACE\n\n'
        'Rules:\n'
        '- Copy every SEARCH section exactly from the current candidate, '
        'including indentation.\n'
        '- Make the smallest edits that address the supplied diagnostics.\n'
        '- You may return several blocks when several local fixes are '
        'required.\n'
        '- Do not include explanations, markdown fences, or any text outside '
        'the blocks.\n'
        '- Never return FULLREGEN and never return a complete activity.py.\n'
        '- Preserve working behavior and the GeneratedActivity class.\n'
        '- Preserve Sugar safety constraints: no networking, subprocesses, '
        'or unrestricted filesystem access.\n'
    )


def build_repair_user_prompt(source, diagnostics, attempt,
                             previous_feedback='', goal='', focused_view=None):
    """Build a repair request around the current, never-discarded source.

    ``goal``, when supplied, states the change the repaired source must
    contain.  It lets the repair loop re-apply a requested refinement whose
    first patch failed a gate instead of silently fixing only the diagnostics.

    ``focused_view``, when supplied, is a rendered slice of the failing region
    (see :func:`generation.focus.build_focused_view`) sent in place of the full
    source so repair is faster.  It is presentation only: the SHA-256 below and
    all downstream verification still identify and check the whole ``source``.
    When it is ``None`` the full source is sent exactly as before.
    """
    parts = [
        'Repair attempt %d.\n' % attempt,
        'Current candidate SHA-256: %s\n\n' % _source_hash(source),
    ]
    if goal:
        parts.extend([
            'Requested change that the repaired source must contain '
            '(preserve it if it is already applied, otherwise apply it '
            'through focused SEARCH/REPLACE blocks):\n',
            _diagnostics_text(goal),
            '\n\n',
        ])
    parts.extend([
        'Failure diagnostics:\n',
        _diagnostics_text(diagnostics),
    ])
    if previous_feedback:
        parts.extend([
            '\n\nThe previous proposal was not committed:\n',
            _diagnostics_text(previous_feedback),
        ])
    if focused_view:
        parts.extend([
            '\n\nThe full activity.py is %d lines. Only the failing region '
            'and the code that wires it are shown below; every other region '
            'is elided and unchanged:\n' % source.count('\n'),
            focused_view.rstrip(),
            '\n\n---\n\nThe lines above are copied verbatim from the current '
            'file. Copy SEARCH sections exactly from them, including '
            'indentation. Keep each SEARCH block small but unique in the '
            'whole file -- 3-10 lines is ideal. Do not reference or edit '
            'elided regions. Return only minimal exact SEARCH/REPLACE blocks. '
            'FULLREGEN and complete-file output are forbidden.',
        ])
    else:
        parts.extend([
            '\n\nCurrent activity.py (%d lines):\n' % source.count('\n'),
            source.rstrip(),
            '\n\n---\n\nReturn only minimal exact SEARCH/REPLACE blocks. '
            'FULLREGEN and complete-file output are forbidden.',
        ])
    return ''.join(parts)


def patches_match_uniquely(source, patches):
    """Return whether every patch matches exactly once, transactionally.

    Later patches are checked against the source produced by earlier blocks,
    matching the order in which :func:`apply_patches` applies them.  The input
    source is never changed.
    """
    if not isinstance(source, str) or not patches:
        return False
    _patched, applied, failed, _error = _apply_patches_transactionally(
        source, patches)
    return not failed and applied == len(patches)


def patches_replace_whole_file(source, patches):
    """Return True when one patch transaction is effectively regeneration.

    Large repairs remain possible across focused transactions, but a model
    may not evade the no-regeneration rule by splitting a complete rewrite
    into several SEARCH/REPLACE blocks in one response.
    """
    if not isinstance(source, str) or not patches:
        return False
    source_text = source.strip('\n')
    source_lines = source_text.splitlines()
    if not source_lines:
        return False
    source_count = len(source_lines)

    destructive_lines = 0
    replacements = []
    for search, replace in patches:
        search_text = search.strip('\n')
        replace_text = replace.strip('\n')
        search_count = len(search_text.splitlines())
        if search_text.rstrip() == source_text.rstrip():
            # Permit a one-line syntax correction, and permit an append that
            # visibly retains the complete tiny/truncated candidate.  Larger
            # exact whole-source replacements are regeneration.
            if source_count > 2:
                return True
            tiny_replacement_lines = len(replace_text.splitlines())
            tiny_local_fix = tiny_replacement_lines <= source_count
            bounded_append = (
                search_text in replace_text and tiny_replacement_lines <= 50)
            if not tiny_local_fix and not bounded_append:
                return True
        # Anchor-preserving insertions are repairs even when the candidate is
        # a one-line truncated stream.  Count only old lines actually removed
        # or rewritten when deciding whether a transaction is regeneration.
        if search_text not in replace_text:
            destructive_lines += search_count
        replacements.append(replace)

    if source_count < 10:
        # Small/truncated candidates must remain repairable.  Only reject an
        # obvious complete-program replacement; local syntax repairs and
        # anchor-preserving appends are allowed.
        combined = '\n'.join(replacements)
        return bool(
            (len(patches) > 1 and destructive_lines >= source_count) or
            destructive_lines >= source_count and
            len(combined.splitlines()) > source_count * 2 and
            _looks_like_complete_activity(combined)
        )

    destructive_limit = int(math.ceil(source_count * 0.75))
    if destructive_lines >= destructive_limit:
        return True

    combined = '\n'.join(replacements)
    # A complete import + GeneratedActivity payload inside patch replacements
    # is a disguised second generation, even when spread over several blocks.
    # Require it to be introduced through smaller staged repairs instead.
    if _looks_like_complete_activity(combined):
        return True
    if 'class GeneratedActivity' in combined and \
            len(combined.splitlines()) >= max(
                10, int(math.ceil(source_count * 0.25))):
        return True
    return False


def response_contains_only_patches(response):
    """Return whether text is strictly composed of patch protocol blocks."""
    return isinstance(response, str) and _contains_only_patch_blocks(response)


def _looks_like_complete_activity(text):
    lines = text.splitlines()
    return bool(
        'class GeneratedActivity' in text and
        any(line.startswith(('import ', 'from ')) for line in lines)
    )


def repair_candidate(provider, source, diagnostics, verify_candidate,
                     max_attempts=8, timeout=None, event_callback=None,
                     goal='', cancel_check=None):
    """Repair ``source`` through transactional SEARCH/REPLACE attempts.

    ``verify_candidate`` is called with each completely-applied proposal.  It
    may return a :class:`RepairCheckResult`, a bool, a ``(passed,
    diagnostics)`` tuple, a ``(passed, diagnostics, accept_candidate)``
    tuple, or a mapping with those keys.  Failed candidates roll back unless
    ``accept_candidate`` is true.

    The function never calls a full-source generation method and never treats
    ``FULLREGEN`` as permission to regenerate.  On provider, protocol,
    verification, cycle, or attempt-limit failure it returns ``success=False``
    with the best explicitly accepted candidate still active.  When supplied,
    ``event_callback`` receives a JSON-safe, source-free summary after every
    attempt; callback failures never interrupt repair.

    ``cancel_check``, when supplied, is polled at the start of every attempt.
    When it returns true the loop stops immediately with ``reason='cancelled'``
    and the best accepted candidate preserved, so a cancelled repair stops
    calling the provider instead of running to the attempt limit.  Cancellation
    is deliberately independent of ``event_callback`` (whose failures are
    swallowed) so it cannot be lost in diagnostics streaming.
    """
    if not isinstance(source, str) or not source.strip():
        raise ValueError('Repair source must be non-empty text.')
    if not callable(verify_candidate):
        raise TypeError('verify_candidate must be callable.')
    if event_callback is not None and not callable(event_callback):
        raise TypeError('event_callback must be callable when supplied.')
    if cancel_check is not None and not callable(cancel_check):
        raise TypeError('cancel_check must be callable when supplied.')
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) \
            or max_attempts < 1:
        raise ValueError('max_attempts must be a positive integer.')

    original_hash = _source_hash(source)
    snapshots = {original_hash: source}
    history = []
    active_source = source
    active_diagnostics = diagnostics
    previous_feedback = ''
    seen_candidates = {original_hash}
    seen_requests = set()

    def record(entry):
        history.append(entry)
        _emit_event(event_callback, entry)

    generate_text = getattr(provider, 'generate_text', None)
    if not callable(generate_text):
        return _result(
            False, active_source, active_diagnostics,
            'provider_does_not_support_patch_repair', 0, history,
            snapshots, original_hash,
        )

    for attempt in range(1, max_attempts + 1):
        if cancel_check is not None and cancel_check():
            return _result(
                False, active_source, active_diagnostics, 'cancelled',
                attempt - 1, history, snapshots, original_hash,
            )
        before_hash = _source_hash(active_source)
        # Focus is recomputed each attempt because a committed intermediate
        # changes the active source and diagnostics.  It only shrinks what the
        # prompt shows; every check below still runs against active_source.
        focused_view = build_focused_view(active_source, active_diagnostics)
        user_prompt = build_repair_user_prompt(
            active_source,
            active_diagnostics,
            attempt,
            previous_feedback=previous_feedback,
            goal=goal,
            focused_view=focused_view,
        )
        try:
            if timeout is None:
                response = generate_text(
                    build_repair_system_prompt(), user_prompt)
            else:
                response = generate_text(
                    build_repair_system_prompt(), user_prompt,
                    timeout=timeout,
                )
        except NotImplementedError as error:
            record(_history_entry(
                attempt, 'repair_not_supported', before_hash,
                active_after=before_hash,
                error=_safe_error(error, provider), rolled_back=True,
            ))
            return _result(
                False, active_source, active_diagnostics,
                'provider_does_not_support_patch_repair', attempt, history,
                snapshots, original_hash,
            )
        except Exception as error:
            record(_history_entry(
                attempt, 'provider_error', before_hash,
                active_after=before_hash,
                error=_safe_error(error, provider),
                rolled_back=True,
            ))
            return _result(
                False, active_source, active_diagnostics, 'provider_error',
                attempt, history, snapshots, original_hash,
            )

        if not isinstance(response, str):
            feedback = 'Provider response was not text.'
            record(_history_entry(
                attempt, 'invalid_response', before_hash,
                active_after=before_hash, error=feedback, rolled_back=True,
            ))
            previous_feedback = feedback
            continue

        response_text = response.strip()
        if _contains_provider_secret(response_text, provider):
            feedback = (
                'Provider response contained credential material and was '
                'refused.'
            )
            record(_history_entry(
                attempt, 'credential_leak_refused', before_hash,
                active_after=before_hash, error=feedback, rolled_back=True,
            ))
            previous_feedback = feedback
            continue
        request_key = (before_hash, _source_hash(response_text))
        if request_key in seen_requests:
            feedback = (
                'The same response was already rejected for this candidate. '
                'Use different, smaller SEARCH/REPLACE blocks that address '
                'the diagnostics.'
            )
            record(_history_entry(
                attempt, 'response_cycle_detected', before_hash,
                active_after=before_hash,
                error=feedback,
                rolled_back=True,
            ))
            previous_feedback = feedback
            continue
        seen_requests.add(request_key)

        if response_text.startswith('FULLREGEN'):
            feedback = (
                'FULLREGEN was refused.  Repair must use exact local '
                'SEARCH/REPLACE blocks.'
            )
            record(_history_entry(
                attempt, 'full_regeneration_refused', before_hash,
                active_after=before_hash, error=feedback, rolled_back=True,
            ))
            previous_feedback = feedback
            continue

        if not _contains_only_patch_blocks(response_text):
            feedback = (
                'Response must contain only SEARCH/REPLACE blocks with no '
                'explanation, markdown, or complete-file output.'
            )
            record(_history_entry(
                attempt, 'invalid_response', before_hash,
                active_after=before_hash, error=feedback, rolled_back=True,
            ))
            previous_feedback = feedback
            continue

        try:
            patches = parse_search_replace(response_text)
        except ValueError as error:
            feedback = str(error)
            record(_history_entry(
                attempt, 'invalid_response', before_hash,
                active_after=before_hash, error=feedback, rolled_back=True,
            ))
            previous_feedback = feedback
            continue

        # Defensive even though FULLREGEN is handled before parsing.
        if patches is None:
            feedback = 'Full-file regeneration is forbidden.'
            record(_history_entry(
                attempt, 'full_regeneration_refused', before_hash,
                active_after=before_hash, error=feedback, rolled_back=True,
            ))
            previous_feedback = feedback
            continue

        patch_records = [
            {'search': search, 'replace': replace}
            for search, replace in patches
        ]
        if patches_replace_whole_file(active_source, patches):
            feedback = (
                'A patch attempted to replace the complete source file.  '
                'Only local repairs are accepted.'
            )
            record(_history_entry(
                attempt, 'full_file_patch_refused', before_hash,
                active_after=before_hash, patches=patch_records,
                error=feedback, rolled_back=True,
            ))
            previous_feedback = feedback
            continue

        proposed_source, applied, failed, apply_error = \
            _apply_patches_transactionally(active_source, patches)
        if failed or applied != len(patches) or not applied:
            feedback = apply_error or (
                '%d patch block(s) applied and %d failed; the whole '
                'proposal was rolled back.' % (applied, failed))
            record(_history_entry(
                attempt, 'patch_apply_failed', before_hash,
                active_after=before_hash, patches=patch_records,
                applied_count=applied, failed_count=failed,
                error=feedback, rolled_back=True,
            ))
            previous_feedback = feedback
            continue

        proposed_hash = _source_hash(proposed_source)
        snapshots.setdefault(proposed_hash, proposed_source)
        if proposed_hash in seen_candidates:
            feedback = (
                'The patch returned to an already-tested candidate.  Keep '
                'the active source and propose a different local repair.'
            )
            record(_history_entry(
                attempt, 'candidate_cycle_detected', before_hash,
                proposed=proposed_hash, active_after=before_hash,
                patches=patch_records, applied_count=applied,
                error=feedback,
                rolled_back=True,
            ))
            previous_feedback = feedback
            continue
        seen_candidates.add(proposed_hash)

        try:
            check = _normalize_check_result(
                verify_candidate(proposed_source), active_diagnostics)
        except Exception as error:
            record(_history_entry(
                attempt, 'verification_error', before_hash,
                proposed=proposed_hash, active_after=before_hash,
                patches=patch_records, applied_count=applied,
                error=_safe_error(error, provider),
                rolled_back=True,
            ))
            return _result(
                False, active_source, active_diagnostics,
                'verification_error', attempt, history, snapshots,
                original_hash,
            )

        if check.passed:
            record(_history_entry(
                attempt, 'passed', before_hash, proposed=proposed_hash,
                active_after=proposed_hash, patches=patch_records,
                applied_count=applied, diagnostics=check.diagnostics,
                rolled_back=False,
            ))
            return _result(
                True, proposed_source, check.diagnostics, 'passed', attempt,
                history, snapshots, original_hash,
            )

        if check.accept_candidate:
            record(_history_entry(
                attempt, 'intermediate_committed', before_hash,
                proposed=proposed_hash, active_after=proposed_hash,
                patches=patch_records, applied_count=applied,
                diagnostics=check.diagnostics, rolled_back=False,
            ))
            active_source = proposed_source
            active_diagnostics = check.diagnostics
            previous_feedback = ''
        else:
            feedback = {
                'message': 'Verification rejected the proposed patch; the '
                           'active candidate was preserved.',
                'rejected_candidate_diagnostics': check.diagnostics,
            }
            record(_history_entry(
                attempt, 'verification_rejected', before_hash,
                proposed=proposed_hash, active_after=before_hash,
                patches=patch_records, applied_count=applied,
                diagnostics=check.diagnostics, rolled_back=True,
            ))
            previous_feedback = feedback

    return _result(
        False, active_source, active_diagnostics, 'attempt_limit_reached',
        max_attempts, history, snapshots, original_hash,
    )


def _normalize_check_result(value, fallback_diagnostics):
    if isinstance(value, RepairCheckResult):
        result = value
    elif isinstance(value, bool):
        result = RepairCheckResult(value, fallback_diagnostics, False)
    elif isinstance(value, tuple):
        if len(value) == 2:
            result = RepairCheckResult(value[0], value[1], False)
        elif len(value) == 3:
            result = RepairCheckResult(value[0], value[1], value[2])
        else:
            raise TypeError(
                'Verification tuples must contain two or three values.')
    elif isinstance(value, dict):
        passed = value.get('passed', value.get('valid'))
        if not isinstance(passed, bool):
            raise TypeError(
                'Verification mapping must contain a boolean passed key.')
        result = RepairCheckResult(
            passed,
            value.get('diagnostics', fallback_diagnostics),
            value.get('accept_candidate', False),
        )
    elif hasattr(value, 'valid'):
        diagnostics = {
            'errors': list(getattr(value, 'errors', ())),
            'warnings': list(getattr(value, 'warnings', ())),
        }
        result = RepairCheckResult(bool(value.valid), diagnostics, False)
    else:
        raise TypeError(
            'verify_candidate returned an unsupported result type.')

    if not isinstance(result.passed, bool):
        raise TypeError('Verification passed value must be boolean.')
    if not isinstance(result.accept_candidate, bool):
        raise TypeError(
            'Verification accept_candidate value must be boolean.')
    return RepairCheckResult(
        result.passed,
        result.diagnostics,
        result.accept_candidate or result.passed,
    )


def _contains_only_patch_blocks(response):
    try:
        patches = parse_search_replace(response)
    except ValueError:
        return False
    if not patches:
        return False

    position = 0
    for search, replace in patches:
        while position < len(response) and response[position].isspace():
            position += 1
        block = (
            '%s\n%s\n=======\n%s\n%s'
            % (SEARCH_MARKER, search, replace, REPLACE_MARKER)
        )
        if not response.startswith(block, position):
            return False
        position += len(block)
    return not response[position:].strip()


def _apply_patches_transactionally(source, patches):
    """Apply only uniquely matching blocks, rolling back on any failure."""
    working_source = source
    applied_total = 0
    for index, patch in enumerate(patches, 1):
        match_count = _search_match_count(working_source, patch[0])
        if match_count != 1:
            if match_count == 0:
                detail = 'did not match the active candidate'
            else:
                detail = 'matched %d locations and was not unique' \
                    % match_count
            return (
                source,
                applied_total,
                1,
                'Patch block %d %s; the whole proposal was rolled back.'
                % (index, detail),
            )

        patched, applied, failed = apply_patches(working_source, [patch])
        if failed or applied != 1:
            return (
                source,
                applied_total,
                1,
                'Patch block %d could not be applied; the whole proposal '
                'was rolled back.' % index,
            )
        working_source = patched
        applied_total += 1
    return working_source, applied_total, 0, ''


def _search_match_count(source, search):
    search_lines = search.split('\n')
    while search_lines and search_lines[-1] == '':
        search_lines.pop()
    if not search_lines:
        return 0
    normalized_search = [line.rstrip() for line in search_lines]
    normalized_source = [line.rstrip() for line in source.split('\n')]
    width = len(normalized_search)
    return sum(
        1
        for start in range(len(normalized_source) - width + 1)
        if normalized_source[start:start + width] == normalized_search
    )


def _history_entry(attempt, outcome, active_before, proposed=None,
                   active_after=None, patches=None, applied_count=0,
                   failed_count=0, diagnostics=None, error='',
                   rolled_back=False):
    return {
        'attempt': attempt,
        'outcome': outcome,
        'active_source_hash_before': active_before,
        'proposed_source_hash': proposed,
        'active_source_hash_after': active_after or active_before,
        'patches': patches or [],
        'applied_count': applied_count,
        'failed_count': failed_count,
        'diagnostics': _json_safe(diagnostics),
        'error': error,
        'rolled_back': rolled_back,
    }


def _emit_event(callback, entry):
    if callback is None:
        return
    event = {
        'event': 'repair_attempt',
        'attempt': entry['attempt'],
        'outcome': entry['outcome'],
        'active_source_hash_before': entry['active_source_hash_before'],
        'proposed_source_hash': entry['proposed_source_hash'],
        'active_source_hash_after': entry['active_source_hash_after'],
        'patch_count': len(entry['patches']),
        'applied_count': entry['applied_count'],
        'failed_count': entry['failed_count'],
        'rolled_back': entry['rolled_back'],
    }
    if entry.get('error'):
        event['detail'] = str(entry['error'])[:1000]
    try:
        callback(_json_safe(event))
    except Exception:
        # Diagnostics streaming must not decide whether code is accepted.
        pass


def _safe_error(error, provider):
    message = '%s: %s' % (type(error).__name__, error)
    for secret in _provider_secrets(provider):
        message = message.replace(secret, '[redacted]')
    return message


def _contains_provider_secret(text, provider):
    return any(secret in text for secret in _provider_secrets(provider))


def _provider_secrets(provider):
    secrets = []
    for name in ('_api_key', 'api_key'):
        value = getattr(provider, name, '')
        if isinstance(value, str) and value:
            secrets.append(value)
    return secrets


def _result(success, source, diagnostics, reason, attempts, history,
            snapshots, original_hash):
    return RepairResult(
        success=success,
        source=source,
        diagnostics=diagnostics,
        reason=reason,
        attempts=attempts,
        history=history,
        snapshots=snapshots,
        original_source_hash=original_hash,
    )


def _source_hash(source):
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def _diagnostics_text(diagnostics):
    if isinstance(diagnostics, str):
        return diagnostics or '(no diagnostic detail supplied)'
    try:
        return json.dumps(
            _json_safe(diagnostics), indent=2, sort_keys=True)
    except (TypeError, ValueError):
        return str(diagnostics)


def _json_safe(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)
