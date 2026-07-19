# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import unittest

from core.spec import ActivitySpec
from core.spec import MAX_PROMPT_LENGTH
from llm.clarify import build_activity_prompt
from llm.clarify import build_questions_system_prompt
from llm.clarify import format_answers
from llm.clarify import generate_plan_proposal
from llm.clarify import generate_questions


def _spec():
    return ActivitySpec('Chess', 'a chess game', 'games', 'MIT')


class _QuestionProvider:
    """Mimics a provider whose generate_plan returns parsed JSON."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def generate_plan(self, system_prompt, user_prompt, timeout=90):
        self.calls.append((system_prompt, user_prompt))
        return self._payload


class _JsonTextProvider:
    """Provider whose generate_plan returns a raw JSON string."""

    def __init__(self, text):
        self._text = text

    def generate_plan(self, system_prompt, user_prompt, timeout=90):
        return self._text


class _BrokenProvider:
    def generate_plan(self, *args, **kwargs):
        raise RuntimeError('boom')

    def generate_text(self, *args, **kwargs):
        raise RuntimeError('boom')


class _PlanProvider:
    def __init__(self, text):
        self._text = text
        self.stream_seen = []

    def generate_text(self, system_prompt, user_prompt, timeout=120,
                      stream_callback=None):
        if stream_callback is not None:
            stream_callback(self._text)
            self.stream_seen.append(self._text)
        return self._text


class TestGenerateQuestions(unittest.TestCase):

    def test_valid_payload_is_normalized(self):
        provider = _QuestionProvider({'questions': [
            {'id': 'Mode', 'label': 'Who plays?', 'type': 'single',
             'options': ['Human vs AI', '2-player']},
            {'id': 'features', 'label': 'Which features?', 'type': 'multi',
             'options': ['Undo', 'Clock', 'Undo']},
            {'label': 'Anything else?', 'type': 'text'},
        ]})

        questions = generate_questions(provider, _spec())

        self.assertEqual(3, len(questions))
        self.assertEqual('mode', questions[0]['id'])
        self.assertEqual('single', questions[0]['type'])
        # Duplicate option removed.
        self.assertEqual(['Undo', 'Clock'], questions[1]['options'])
        # Free-text question carries no options.
        self.assertEqual('text', questions[2]['type'])
        self.assertNotIn('options', questions[2])
        # Prompt is specific to the idea.
        self.assertIn('chess', provider.calls[0][1])

    def test_json_string_response_is_parsed(self):
        payload = json.dumps({'questions': [
            {'id': 'a', 'label': 'One?', 'type': 'text'},
            {'id': 'b', 'label': 'Two?', 'type': 'text'},
        ]})
        questions = generate_questions(_JsonTextProvider(payload), _spec())
        self.assertEqual(2, len(questions))

    def test_single_option_choice_becomes_text(self):
        provider = _QuestionProvider({'questions': [
            {'id': 'a', 'label': 'Pick?', 'type': 'single',
             'options': ['Only one']},
            {'id': 'b', 'label': 'Free?', 'type': 'text'},
        ]})
        questions = generate_questions(provider, _spec())
        self.assertEqual('text', questions[0]['type'])
        self.assertNotIn('options', questions[0])

    def test_too_few_questions_returns_empty(self):
        provider = _QuestionProvider({'questions': [
            {'id': 'a', 'label': 'Only one?', 'type': 'text'},
        ]})
        self.assertEqual([], generate_questions(provider, _spec()))

    def test_appends_free_text_catch_all_when_missing(self):
        provider = _QuestionProvider({'questions': [
            {'id': 'a', 'label': 'One?', 'type': 'single',
             'options': ['x', 'y']},
            {'id': 'b', 'label': 'Two?', 'type': 'multi',
             'options': ['p', 'q']},
        ]})
        questions = generate_questions(provider, _spec())
        self.assertEqual('text', questions[-1]['type'])
        self.assertEqual('anything_else', questions[-1]['id'])

    def test_does_not_append_when_text_present(self):
        provider = _QuestionProvider({'questions': [
            {'id': 'a', 'label': 'One?', 'type': 'text'},
            {'id': 'b', 'label': 'Two?', 'type': 'text'},
        ]})
        questions = generate_questions(provider, _spec())
        self.assertEqual(2, len(questions))
        self.assertTrue(all(q['id'] != 'anything_else' for q in questions))

    def test_no_provider_returns_empty(self):
        self.assertEqual([], generate_questions(None, _spec()))

    def test_provider_failure_returns_empty(self):
        self.assertEqual([], generate_questions(_BrokenProvider(), _spec()))

    def test_bad_json_returns_empty(self):
        self.assertEqual(
            [], generate_questions(_JsonTextProvider('not json'), _spec()))


class TestGeneratePlanProposal(unittest.TestCase):

    def test_returns_cleaned_text(self):
        provider = _PlanProvider(
            '```\nWe will build a chess board.\n- Play vs AI\n```')
        plan = generate_plan_proposal(provider, _spec(), 'Confirmed: x')
        self.assertIn('chess board', plan)
        self.assertNotIn('```', plan)

    def test_stream_callback_receives_text(self):
        provider = _PlanProvider('A full plan for the chess activity here.')
        seen = []
        generate_plan_proposal(provider, _spec(), stream_callback=seen.append)
        self.assertTrue(seen)

    def test_no_provider_uses_fallback(self):
        plan = generate_plan_proposal(None, _spec())
        self.assertIn('Chess', plan)
        self.assertIn("build it", plan)

    def test_provider_failure_uses_fallback(self):
        plan = generate_plan_proposal(_BrokenProvider(), _spec())
        self.assertIn('Chess', plan)


class TestFormatAnswers(unittest.TestCase):

    def test_renders_block_and_joins_multi(self):
        questions = [
            {'id': 'mode', 'label': 'Who plays?', 'type': 'single'},
            {'id': 'features', 'label': 'Features?', 'type': 'multi'},
            {'id': 'blank', 'label': 'Skip me?', 'type': 'text'},
        ]
        answers = {'mode': 'Human vs AI',
                   'features': ['Undo', 'Clock'],
                   'blank': ''}
        text = format_answers(questions, answers)
        self.assertIn('Confirmed requirements:', text)
        self.assertIn('- Who plays?: Human vs AI', text)
        self.assertIn('- Features?: Undo, Clock', text)
        self.assertNotIn('Skip me?', text)

    def test_empty_when_no_answers(self):
        questions = [{'id': 'a', 'label': 'A?', 'type': 'text'}]
        self.assertEqual('', format_answers(questions, {'a': '   '}))
        self.assertEqual('', format_answers(questions, {}))
        self.assertEqual('', format_answers([], {'a': 'x'}))


class TestBuildActivityPrompt(unittest.TestCase):

    def test_folds_sections_in_order(self):
        combined = build_activity_prompt(
            'a chess game', 'Confirmed requirements:\n- Who?: AI',
            'We will build a board.')
        self.assertIn('Confirmed requirements:', combined)
        self.assertIn('Agreed plan:', combined)
        self.assertTrue(combined.rstrip().endswith('a chess game'))

    def test_truncates_to_max_length(self):
        combined = build_activity_prompt('x' * (MAX_PROMPT_LENGTH + 500))
        self.assertLessEqual(len(combined), MAX_PROMPT_LENGTH)

    def test_system_prompt_requests_json(self):
        self.assertIn('JSON', build_questions_system_prompt())


if __name__ == '__main__':
    unittest.main()
