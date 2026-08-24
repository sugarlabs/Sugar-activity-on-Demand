# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import unittest
from unittest import mock

from generation.critic import run_critic_round
from generation.critic import build_critic_system_prompt
from generation.generator import enrich_plan
from generation.templates import render_activity_source
from core.spec import ActivitySpec

_CRITIC_ENV = {'AOD_CRITIC': 'on', 'AOD_RUNTIME_CHECK': 'off'}


class _CriticProvider:
    name = 'critic-fake'
    model = 'critic-1'

    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.observed_prompts = []

    def generate_text(self, system_prompt, user_prompt, timeout=120,
                      stream_callback=None):
        self.calls += 1
        self.observed_prompts.append((system_prompt, user_prompt))
        return self.response


class _NoTextProvider:
    name = 'plan-only'
    model = 'plan-1'


class _ImageCriticProvider(_CriticProvider):

    def __init__(self, response):
        _CriticProvider.__init__(self, response)
        self.image_data = None
        self.image_mime_type = ''

    def generate_text(self, system_prompt, user_prompt, timeout=120,
                      stream_callback=None, image_data=None,
                      image_mime_type=''):
        self.image_data = image_data
        self.image_mime_type = image_mime_type
        return _CriticProvider.generate_text(
            self, system_prompt, user_prompt, timeout, stream_callback)


def _spec_and_source():
    spec = ActivitySpec(
        'Critic Probe',
        'Make a fractions quiz.',
        'logic_math',
        'MIT',
    )
    plan = enrich_plan(spec, {
        'template': 'quiz',
        'summary': 'Critic probe.',
        'learner_goal': 'Practice fractions.',
        'learner_steps': ['Try', 'Explain', 'Share'],
    })
    return spec, plan, render_activity_source(spec, plan)


def _patch_block(search, replace):
    return (
        '<<<<<<< SEARCH\n%s\n=======\n%s\n>>>>>>> REPLACE\n'
        % (search, replace)
    )


class TestCriticRound(unittest.TestCase):

    def setUp(self):
        self.spec, self.plan, self.source = _spec_and_source()

    def test_ok_reply_keeps_source(self):
        provider = _CriticProvider('OK')
        with mock.patch.dict(os.environ, _CRITIC_ENV):
            result = run_critic_round(
                provider, self.spec, self.plan, self.source)
        self.assertEqual(self.source, result)
        self.assertEqual('ok', self.plan['critic'])
        self.assertEqual(1, provider.calls)

    def test_critic_checks_polish_and_real_interaction(self):
        prompt = build_critic_system_prompt()

        self.assertIn('stretched text action', prompt)
        self.assertIn('one dominant canvas', prompt)
        self.assertIn('success feedback is computed', prompt)
        self.assertIn('reference fidelity overrides', prompt)
        self.assertIn('Never patch away or relocate', prompt)
        self.assertIn('reply OK even when its styling is not perfectly',
                      prompt)
        self.assertIn('do not patch solely for Sugar-native styling', prompt)

    def test_reference_pixels_reach_final_critic(self):
        provider = _ImageCriticProvider('OK')

        with mock.patch.dict(os.environ, _CRITIC_ENV):
            result = run_critic_round(
                provider, self.spec, self.plan, self.source,
                reference_image_data=b'reference-pixels',
                reference_image_mime_type='image/png')

        self.assertEqual(self.source, result)
        self.assertEqual(b'reference-pixels', provider.image_data)
        self.assertEqual('image/png', provider.image_mime_type)

    def test_valid_patch_is_applied(self):
        provider = _CriticProvider(_patch_block(
            '        self.max_participants = 1',
            '        self.max_participants = 1  # critic-touched',
        ))
        with mock.patch.dict(os.environ, _CRITIC_ENV), \
                mock.patch('generation.critic.run_runtime_check',
                           return_value=(True, 'passed')):
            result = run_critic_round(
                provider, self.spec, self.plan, self.source)
        self.assertIn('# critic-touched', result)
        self.assertEqual('patched:1', self.plan['critic'])

    def test_patch_is_marked_unverified_when_runtime_gate_is_skipped(self):
        # run_runtime_check returns ok=True both when the activity really
        # started and when the gate could not run at all.  Recording the
        # second case as 'patched' would claim the patch re-passed a gate
        # that never executed.
        provider = _CriticProvider(_patch_block(
            '        self.max_participants = 1',
            '        self.max_participants = 1  # critic-touched',
        ))
        with mock.patch.dict(os.environ, _CRITIC_ENV), \
                mock.patch('generation.critic.run_runtime_check',
                           return_value=(True, 'skipped: no display')):
            result = run_critic_round(
                provider, self.spec, self.plan, self.source)
        self.assertIn('# critic-touched', result)
        self.assertEqual('patched-unverified:1', self.plan['critic'])

    def test_runtime_breaking_patch_is_not_reported_as_verified(self):
        # A patch that would crash on launch still passes static
        # validation, so with the gate unavailable the only honest
        # outcome is 'patched-unverified'.
        provider = _CriticProvider(_patch_block(
            '        self.max_participants = 1',
            '        self.max_participants = 1\n'
            "        raise RuntimeError('boom')",
        ))
        with mock.patch.dict(os.environ, _CRITIC_ENV):
            run_critic_round(provider, self.spec, self.plan, self.source)
        self.assertFalse(
            self.plan['critic'].startswith('patched:'),
            'a never-executed patch must not be recorded as runtime-verified')

    def test_garbage_reply_keeps_source(self):
        provider = _CriticProvider('Sure! Here are my thoughts...')
        with mock.patch.dict(os.environ, _CRITIC_ENV):
            result = run_critic_round(
                provider, self.spec, self.plan, self.source)
        self.assertEqual(self.source, result)
        self.assertEqual('skipped', self.plan['critic'])

    def test_fullregen_is_refused(self):
        provider = _CriticProvider('FULLREGEN')
        with mock.patch.dict(os.environ, _CRITIC_ENV):
            result = run_critic_round(
                provider, self.spec, self.plan, self.source)
        self.assertEqual(self.source, result)
        self.assertEqual('skipped', self.plan['critic'])

    def test_unmatched_patch_keeps_source(self):
        provider = _CriticProvider(_patch_block(
            'this line does not exist anywhere',
            'replacement',
        ))
        with mock.patch.dict(os.environ, _CRITIC_ENV):
            result = run_critic_round(
                provider, self.spec, self.plan, self.source)
        self.assertEqual(self.source, result)
        self.assertEqual('skipped', self.plan['critic'])

    def test_validation_breaking_patch_keeps_source(self):
        provider = _CriticProvider(_patch_block(
            'class GeneratedActivity(activity.Activity):',
            'class GeneratedActivity(object):',
        ))
        with mock.patch.dict(os.environ, _CRITIC_ENV):
            result = run_critic_round(
                provider, self.spec, self.plan, self.source)
        self.assertEqual(self.source, result)
        self.assertEqual('skipped', self.plan['critic'])

    def test_provider_error_keeps_source(self):
        provider = _CriticProvider('OK')
        provider.generate_text = mock.Mock(
            side_effect=RuntimeError('critic offline'))
        with mock.patch.dict(os.environ, _CRITIC_ENV):
            result = run_critic_round(
                provider, self.spec, self.plan, self.source)
        self.assertEqual(self.source, result)
        self.assertEqual('skipped', self.plan['critic'])

    def test_disabled_by_env_skips_call(self):
        provider = _CriticProvider('OK')
        env = dict(_CRITIC_ENV, AOD_CRITIC='off')
        with mock.patch.dict(os.environ, env):
            result = run_critic_round(
                provider, self.spec, self.plan, self.source)
        self.assertEqual(self.source, result)
        self.assertEqual('skipped', self.plan['critic'])
        self.assertEqual(0, provider.calls)

    def test_provider_without_generate_text_skips(self):
        with mock.patch.dict(os.environ, _CRITIC_ENV):
            result = run_critic_round(
                _NoTextProvider(), self.spec, self.plan, self.source)
        self.assertEqual(self.source, result)
        self.assertEqual('skipped', self.plan['critic'])

    def test_warnings_appear_in_prompt(self):
        provider = _CriticProvider('OK')
        with mock.patch.dict(os.environ, _CRITIC_ENV):
            run_critic_round(
                provider, self.spec, self.plan, self.source,
                warnings=['Score is never shown to the learner.'])
        _system, user = provider.observed_prompts[0]
        self.assertIn('Score is never shown to the learner.', user)


if __name__ == '__main__':
    unittest.main()
