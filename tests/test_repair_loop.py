# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import unittest

from generation.repair_loop import RepairCheckResult
from generation.repair_loop import build_repair_system_prompt
from generation.repair_loop import build_repair_user_prompt
from generation.repair_loop import patches_match_uniquely
from generation.repair_loop import patches_replace_whole_file
from generation.repair_loop import repair_candidate


_SOURCE = (
    'class GeneratedActivity:\n'
    '    def status(self):\n'
    '        value = "broken"\n'
    '        return value\n'
)


def _patch(search, replace):
    return (
        '<<<<<<< SEARCH\n%s\n=======\n%s\n>>>>>>> REPLACE\n'
        % (search, replace)
    )


class _Provider:

    name = 'repair-fake'
    model = 'repair-1'

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        self.full_generation_calls = 0

    def generate_text(self, system_prompt, user_prompt, timeout=120,
                      stream_callback=None):
        self.prompts.append((system_prompt, user_prompt, timeout))
        return self.responses.pop(0)

    def generate_activity_source(self, *args, **kwargs):
        self.full_generation_calls += 1
        raise AssertionError('Full generation must never be called.')


class TestRepairLoop(unittest.TestCase):

    def test_repairs_existing_candidate_and_emits_source_free_event(self):
        provider = _Provider([_patch(
            '        value = "broken"',
            '        value = "fixed"',
        )])
        events = []

        result = repair_candidate(
            provider,
            _SOURCE,
            {'phase': 'runtime', 'error': 'wrong value'},
            lambda candidate: (True, {'errors': []}),
            event_callback=events.append,
        )

        self.assertTrue(result.success)
        self.assertEqual('passed', result.reason)
        self.assertIn('value = "fixed"', result.source)
        self.assertEqual(0, provider.full_generation_calls)
        self.assertIn('wrong value', provider.prompts[0][1])
        self.assertIn('Never return FULLREGEN', provider.prompts[0][0])
        self.assertEqual(['passed'], [event['outcome'] for event in events])
        encoded_event = json.dumps(events[0], sort_keys=True)
        self.assertNotIn('value =', encoded_event)
        self.assertNotIn('patches', events[0])
        self.assertNotIn('diagnostics', events[0])
        self.assertEqual(2, len(result.snapshots))

    def test_rejected_patch_rolls_back_before_next_attempt(self):
        provider = _Provider([
            _patch('        value = "broken"',
                   '        value = "worse"'),
            _patch('        value = "broken"',
                   '        value = "fixed"'),
        ])

        def verify(candidate):
            if 'worse' in candidate:
                return RepairCheckResult(
                    False, 'candidate still fails', False)
            return RepairCheckResult(True, 'all gates passed')

        result = repair_candidate(
            provider, _SOURCE, 'runtime failed', verify, max_attempts=2)

        self.assertTrue(result.success)
        self.assertEqual(
            ['verification_rejected', 'passed'],
            [entry['outcome'] for entry in result.history],
        )
        self.assertTrue(result.history[0]['rolled_back'])
        second_prompt = provider.prompts[1][1]
        self.assertIn('        value = "broken"', second_prompt)
        self.assertNotIn('        value = "worse"', second_prompt)
        self.assertEqual(3, len(result.snapshots))

    def test_safe_intermediate_can_be_committed_for_next_repair(self):
        source = (
            'first = "bad"\n'
            'second = "bad"\n'
        )
        provider = _Provider([
            _patch('first = "bad"', 'first = "good"'),
            _patch('second = "bad"', 'second = "good"'),
        ])

        def verify(candidate):
            if 'second = "bad"' in candidate:
                return RepairCheckResult(
                    False, {'error': 'second remains broken'}, True)
            return RepairCheckResult(True, {'errors': []})

        result = repair_candidate(
            provider, source, 'both values broken', verify,
            max_attempts=2)

        self.assertTrue(result.success)
        self.assertNotIn('"bad"', result.source)
        self.assertEqual(
            ['intermediate_committed', 'passed'],
            [entry['outcome'] for entry in result.history],
        )
        self.assertIn('first = "good"', provider.prompts[1][1])
        self.assertIn('second remains broken', provider.prompts[1][1])

    def test_multi_block_proposal_is_atomic_when_one_block_fails(self):
        response = (
            _patch('        value = "broken"',
                   '        value = "partly-fixed"') +
            '\n' +
            _patch('        missing = True',
                   '        missing = False')
        )
        provider = _Provider([
            response,
            _patch('        value = "broken"',
                   '        value = "fixed"'),
        ])
        verified = []

        def verify(candidate):
            verified.append(candidate)
            return True

        result = repair_candidate(
            provider, _SOURCE, 'broken', verify, max_attempts=2)

        self.assertTrue(result.success)
        self.assertEqual(1, len(verified))
        self.assertEqual('patch_apply_failed', result.history[0]['outcome'])
        self.assertEqual(1, result.history[0]['applied_count'])
        self.assertTrue(result.history[0]['rolled_back'])
        self.assertIn('value = "broken"', provider.prompts[1][1])
        self.assertNotIn('partly-fixed', provider.prompts[1][1])

    def test_non_unique_search_anchor_is_rejected(self):
        source = (
            'flag = False\n'
            'middle = True\n'
            'flag = False\n'
        )
        provider = _Provider([_patch('flag = False', 'flag = True')])
        verified = []

        result = repair_candidate(
            provider, source, 'one flag is wrong',
            lambda candidate: verified.append(candidate) or True,
            max_attempts=1,
        )

        self.assertFalse(result.success)
        self.assertEqual(source, result.source)
        self.assertEqual([], verified)
        self.assertEqual('patch_apply_failed', result.history[0]['outcome'])
        self.assertIn('matched 2 locations', result.history[0]['error'])

    def test_public_unique_match_helper_observes_patch_order(self):
        patches = [
            ('state = "a"', 'state = "b"'),
            ('state = "b"', 'state = "c"'),
        ]
        self.assertTrue(patches_match_uniquely('state = "a"\n', patches))
        self.assertFalse(patches_match_uniquely(
            'state = "a"\nstate = "a"\n', patches))

    def test_fullregen_is_refused_without_calling_full_generator(self):
        provider = _Provider(['FULLREGEN'])
        result = repair_candidate(
            provider, _SOURCE, 'broken', lambda candidate: True,
            max_attempts=1)

        self.assertFalse(result.success)
        self.assertEqual(_SOURCE, result.source)
        self.assertEqual(0, provider.full_generation_calls)
        self.assertEqual(
            'full_regeneration_refused', result.history[0]['outcome'])

    def test_complete_source_patch_is_refused(self):
        replacement = _SOURCE.replace('"broken"', '"fixed"')
        provider = _Provider([_patch(_SOURCE.rstrip(),
                                     replacement.rstrip())])
        verified = []
        result = repair_candidate(
            provider, _SOURCE, 'broken',
            lambda candidate: verified.append(candidate) or True,
            max_attempts=1)

        self.assertFalse(result.success)
        self.assertEqual([], verified)
        self.assertEqual('full_file_patch_refused',
                         result.history[0]['outcome'])
        self.assertEqual({_hash_for_test(_SOURCE)}, set(result.snapshots))

    def test_multi_block_whole_file_rewrite_is_refused(self):
        patches = [
            ('class GeneratedActivity:\n    def status(self):',
             'class GeneratedActivity:\n    def answer(self):'),
            ('        value = "broken"\n        return value',
             '        value = "fixed"\n        return value'),
        ]
        provider = _Provider(['\n'.join(
            _patch(search, replace).strip()
            for search, replace in patches)])
        verified = []

        result = repair_candidate(
            provider, _SOURCE, 'broken',
            lambda candidate: verified.append(candidate) or True,
            max_attempts=1,
        )

        self.assertTrue(patches_replace_whole_file(_SOURCE, patches))
        self.assertFalse(result.success)
        self.assertEqual([], verified)
        self.assertEqual('full_file_patch_refused',
                         result.history[0]['outcome'])

    def test_reusing_imports_with_new_activity_class_is_refused(self):
        source = (
            'from sugar3.activity import activity\n'
            'class GeneratedActivity(activity.Activity):\n' +
            ''.join('    value_%d = %d\n' % (index, index)
                    for index in range(12))
        )
        new_class = (
            '    value_0 = 0\n'
            'class GeneratedActivity(activity.Activity):\n' +
            ''.join('    repaired_%d = %d\n' % (index, index)
                    for index in range(9))
        ).rstrip()
        patches = [
            ('class GeneratedActivity(activity.Activity):',
             'class ReplacedActivity(activity.Activity):'),
            ('    value_0 = 0', new_class),
        ]
        provider = _Provider(['\n'.join(
            _patch(search, replace).strip()
            for search, replace in patches)])

        result = repair_candidate(
            provider, source, 'broken', lambda candidate: True,
            max_attempts=1)

        self.assertTrue(patches_replace_whole_file(source, patches))
        self.assertFalse(result.success)
        self.assertEqual('full_file_patch_refused',
                         result.history[0]['outcome'])

    def test_raw_complete_source_is_not_accepted(self):
        provider = _Provider([_SOURCE.replace('"broken"', '"fixed"')])
        result = repair_candidate(
            provider, _SOURCE, 'broken', lambda candidate: True,
            max_attempts=1)
        self.assertFalse(result.success)
        self.assertEqual('invalid_response', result.history[0]['outcome'])
        self.assertEqual(_SOURCE, result.source)

    def test_explanation_between_patch_blocks_is_rejected(self):
        response = (
            _patch('        value = "broken"',
                   '        value = "fixed"') +
            'I also changed another line.\n' +
            _patch('        return value',
                   '        return str(value)')
        )
        provider = _Provider([response])
        result = repair_candidate(
            provider, _SOURCE, 'broken', lambda candidate: True,
            max_attempts=1,
        )
        self.assertFalse(result.success)
        self.assertEqual('invalid_response', result.history[0]['outcome'])

    def test_candidate_cycle_keeps_best_source_until_attempt_limit(self):
        source = 'prefix = True\nstate = "a"\n'
        provider = _Provider([
            _patch('state = "a"', 'state = "b"'),
            _patch('state = "b"', 'state = "a"'),
        ])
        checks = []

        def verify(candidate):
            checks.append(candidate)
            return RepairCheckResult(False, 'try again', True)

        result = repair_candidate(
            provider, source, 'state a fails', verify, max_attempts=2)

        self.assertFalse(result.success)
        self.assertEqual('attempt_limit_reached', result.reason)
        self.assertEqual('prefix = True\nstate = "b"\n', result.source)
        self.assertEqual(1, len(checks))
        self.assertEqual('candidate_cycle_detected',
                         result.history[-1]['outcome'])

    def test_repeated_invalid_response_uses_full_repair_budget(self):
        provider = _Provider(['not patches', 'not patches'])
        result = repair_candidate(
            provider, _SOURCE, 'broken', lambda candidate: True,
            max_attempts=2)
        self.assertFalse(result.success)
        self.assertEqual('attempt_limit_reached', result.reason)
        self.assertEqual(2, result.attempts)

    def test_provider_error_redacts_key_and_event_has_no_error_text(self):
        secret = 'super-secret-api-key'

        class FailingProvider:
            _api_key = secret

            def generate_text(self, *args, **kwargs):
                raise RuntimeError('request with %s failed' % secret)

        events = []
        result = repair_candidate(
            FailingProvider(), _SOURCE, 'broken', lambda candidate: True,
            event_callback=events.append,
        )

        self.assertFalse(result.success)
        self.assertNotIn(secret, json.dumps(result.to_dict()))
        self.assertNotIn(secret, json.dumps(events))
        self.assertIn('[redacted]', result.history[0]['error'])
        self.assertNotIn('error', events[0])

    def test_response_containing_provider_key_is_refused_and_not_stored(self):
        secret = 'never-store-this-key'
        provider = _Provider([
            _patch('        value = "broken"',
                   '        value = "%s"' % secret),
        ])
        provider._api_key = secret
        result = repair_candidate(
            provider, _SOURCE, 'broken', lambda candidate: True,
            max_attempts=1,
        )
        self.assertFalse(result.success)
        self.assertEqual('credential_leak_refused',
                         result.history[0]['outcome'])
        self.assertNotIn(secret, json.dumps(result.to_dict()))

    def test_base_generate_text_not_implemented_is_unsupported(self):
        class PlanOnlyProvider:
            def generate_text(self, *args, **kwargs):
                raise NotImplementedError('raw text is unsupported')

        result = repair_candidate(
            PlanOnlyProvider(), _SOURCE, 'broken', lambda candidate: True)
        self.assertFalse(result.success)
        self.assertEqual('provider_does_not_support_patch_repair',
                         result.reason)
        self.assertEqual('repair_not_supported',
                         result.history[0]['outcome'])

    def test_event_callback_failure_does_not_change_repair_result(self):
        provider = _Provider([_patch(
            '        value = "broken"', '        value = "fixed"')])

        def broken_callback(_event):
            raise RuntimeError('event sink unavailable')

        result = repair_candidate(
            provider, _SOURCE, 'broken', lambda candidate: True,
            event_callback=broken_callback,
        )
        self.assertTrue(result.success)
        json.dumps(result.to_dict())

    def test_system_prompt_forbids_any_regeneration(self):
        prompt = build_repair_system_prompt()
        self.assertIn('Never return FULLREGEN', prompt)
        self.assertIn('never return a complete activity.py', prompt)

    def test_goal_is_stated_in_the_repair_prompt(self):
        provider = _Provider([_patch(
            '        value = "broken"', '        value = "fixed"')])
        repair_candidate(
            provider, _SOURCE, 'broken', lambda candidate: True,
            goal='Add a reset button labelled RESET.')
        self.assertIn('Add a reset button labelled RESET.',
                      provider.prompts[0][1])

    def test_cancellation_stops_before_calling_the_provider(self):
        provider = _Provider([_patch(
            '        value = "broken"', '        value = "fixed"')])
        result = repair_candidate(
            provider, _SOURCE, 'broken', lambda candidate: True,
            max_attempts=3, cancel_check=lambda: True)
        self.assertFalse(result.success)
        self.assertEqual('cancelled', result.reason)
        self.assertEqual(0, result.attempts)
        self.assertEqual(_SOURCE, result.source)
        self.assertEqual([], provider.prompts)
        self.assertEqual([], result.history)

    def test_cancellation_between_attempts_stops_the_loop(self):
        provider = _Provider([
            _patch('        value = "broken"', '        value = "worse"'),
            _patch('        value = "broken"', '        value = "fixed"'),
        ])
        state = {'cancel': False}

        def verify(candidate):
            # Ask to cancel after the first candidate is examined.
            state['cancel'] = True
            return RepairCheckResult(False, 'still failing', False)

        result = repair_candidate(
            provider, _SOURCE, 'broken', verify, max_attempts=5,
            cancel_check=lambda: state['cancel'])

        self.assertFalse(result.success)
        self.assertEqual('cancelled', result.reason)
        # Only the first attempt reached the provider; the loop stopped
        # instead of running to the attempt limit.
        self.assertEqual(1, len(provider.prompts))
        self.assertEqual(1, result.attempts)

    def test_cancel_check_survives_a_broken_event_sink(self):
        # A cancel must be honoured even though event-callback failures are
        # swallowed: cancellation is independent of diagnostics streaming.
        provider = _Provider([_patch(
            '        value = "broken"', '        value = "fixed"')])

        def broken_callback(_event):
            raise RuntimeError('event sink unavailable')

        result = repair_candidate(
            provider, _SOURCE, 'broken', lambda candidate: True,
            cancel_check=lambda: True, event_callback=broken_callback)
        self.assertEqual('cancelled', result.reason)
        self.assertEqual([], provider.prompts)


_FOCUS_HANDLER = '        self.score.increment()'
_FOCUS_CONNECT = "        button.connect('clicked', self._on_click)"


def _large_source():
    """A >60-line activity whose _on_click handler is far from the __init__
    that wires it, so focus can meaningfully shrink the prompt."""
    lines = [
        'from sugar3.activity import activity',
        '',
        '',
        'class GeneratedActivity(activity.Activity):',
        '    def __init__(self, handle):',
        '        activity.Activity.__init__(self, handle)',
        "        button = ToolButton('go')",
        _FOCUS_CONNECT,
        '        self.button = button',
    ]
    for index in range(14):
        lines += [
            '',
            '    def _filler_%d(self, widget):' % index,
            '        value = %d' % index,
            '        return value',
        ]
    lines += ['', '    def _on_click(self, button):', _FOCUS_HANDLER,
              '        return None', '']
    return '\n'.join(lines) + '\n'


def _runtime_diag(source):
    line_no = source.split('\n').index(_FOCUS_HANDLER) + 1
    frame = ('  File "<activity>/activity.py", line %d, in _on_click\n'
             '    self.score.increment()\n'
             "AttributeError: 'NoneType' object has no attribute 'increment'"
             % line_no)
    return {'stage': 'runtime_check', 'errors': [frame],
            'runtime_detail': frame}


class TestRepairFocus(unittest.TestCase):

    def test_focus_shrinks_prompt_but_still_repairs_full_file(self):
        source = _large_source()
        provider = _Provider([_patch(
            _FOCUS_HANDLER, '        self.score.add(1)')])

        result = repair_candidate(
            provider, source, _runtime_diag(source),
            lambda candidate: True)

        self.assertTrue(result.success)
        self.assertIn('self.score.add(1)', result.source)
        prompt = provider.prompts[0][1]
        # The failing handler and its wiring are shown; far filler is elided.
        self.assertIn(_FOCUS_HANDLER, prompt)
        self.assertIn(_FOCUS_CONNECT, prompt)
        self.assertNotIn('def _filler_7', prompt)
        self.assertIn('elided and unchanged', prompt)

    def test_focus_disabled_env_sends_full_source(self):
        source = _large_source()
        provider = _Provider([_patch(
            _FOCUS_HANDLER, '        self.score.add(1)')])

        previous = os.environ.get('AOD_REPAIR_FOCUS')
        os.environ['AOD_REPAIR_FOCUS'] = 'off'
        try:
            result = repair_candidate(
                provider, source, _runtime_diag(source),
                lambda candidate: True)
        finally:
            if previous is None:
                del os.environ['AOD_REPAIR_FOCUS']
            else:
                os.environ['AOD_REPAIR_FOCUS'] = previous

        self.assertTrue(result.success)
        prompt = provider.prompts[0][1]
        # Whole file present, no focus framing.
        self.assertIn('def _filler_7', prompt)
        self.assertNotIn('elided and unchanged', prompt)

    def test_no_location_signal_sends_full_source(self):
        source = _large_source()
        provider = _Provider([_patch(
            _FOCUS_HANDLER, '        self.score.add(1)')])

        result = repair_candidate(
            provider, source,
            {'stage': 'static_validation',
             'errors': ['Forbidden import: subprocess']},
            lambda candidate: True)

        self.assertTrue(result.success)
        prompt = provider.prompts[0][1]
        self.assertIn('def _filler_7', prompt)
        self.assertNotIn('elided and unchanged', prompt)

    def test_small_source_prompt_is_unchanged(self):
        # The existing tiny fixture stays on the full-source path unchanged.
        focused = build_repair_user_prompt(_SOURCE, 'boom', 1)
        self.assertIn('Current activity.py', focused)
        self.assertIn('        value = "broken"', focused)
        self.assertNotIn('elided and unchanged', focused)
        self.assertEqual(
            focused, build_repair_user_prompt(_SOURCE, 'boom', 1,
                                              focused_view=None))


def _hash_for_test(source):
    # Keep this assertion independent of private module helpers.
    import hashlib
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


if __name__ == '__main__':
    unittest.main()
