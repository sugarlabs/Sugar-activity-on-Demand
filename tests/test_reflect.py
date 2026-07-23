# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import unittest

from core.spec import ActivitySpec
from generation.generator import enrich_plan
from generation.templates import render_activity_source
from generation.reflect import analyze_source
from generation.reflect import reflections_for_change


def _generated_activity():
    spec = ActivitySpec('Fraction Quest', 'Make a fractions quiz.',
                        'logic_math', 'MIT')
    plan = enrich_plan(spec, {
        'template': 'quiz',
        'summary': 'A fractions quiz.',
        'learner_goal': 'Practice fractions.',
        'learner_steps': ['Try', 'Explain', 'Share'],
    })
    return render_activity_source(spec, plan), plan


class TestAnalyzeSourceSections(unittest.TestCase):

    def setUp(self):
        self.source, self.plan = _generated_activity()
        self.result = analyze_source(self.source, self.plan)

    def test_detects_core_sections(self):
        ids = {section['id'] for section in self.result['sections']}
        self.assertLessEqual(
            {'imports', 'activity_class', 'init', 'toolbar', 'canvas',
             'journal'},
            ids)

    def test_line_ranges_are_valid(self):
        total = len(self.source.splitlines())
        for section in self.result['sections']:
            self.assertGreaterEqual(section['line_start'], 1)
            self.assertLessEqual(section['line_end'], total)
            self.assertLessEqual(section['line_start'], section['line_end'])
            self.assertTrue(section['explanation'])

    def test_sections_sorted_by_line(self):
        starts = [section['line_start'] for section in self.result['sections']]
        self.assertEqual(starts, sorted(starts))


class TestAnalyzeSourceReflections(unittest.TestCase):

    def setUp(self):
        self.source, self.plan = _generated_activity()
        self.result = analyze_source(self.source, self.plan)

    def test_detects_pattern_reflections(self):
        ids = {r['id'] for r in self.result['reflections']}
        self.assertLessEqual({'inherits', 'journal', 'canvas', 'toolbar'}, ids)

    def test_merges_plan_assessment_prompts(self):
        questions = {r['question'] for r in self.result['reflections']}
        for prompt in self.plan['assessment_prompts']:
            self.assertIn(prompt, questions)

    def test_every_reflection_has_id_and_question(self):
        for reflection in self.result['reflections']:
            self.assertTrue(reflection['question'])
            self.assertIn('id', reflection)

    def test_deduplicates_plan_prompt_matching_a_pattern(self):
        source, plan = _generated_activity()
        pattern_q = analyze_source(source)['reflections'][0]['question']
        plan['assessment_prompts'] = [pattern_q, 'A genuinely new prompt.']
        questions = [r['question']
                     for r in analyze_source(source, plan)['reflections']]
        self.assertEqual(questions.count(pattern_q), 1)
        self.assertIn('A genuinely new prompt.', questions)


class TestFailSoft(unittest.TestCase):

    def test_syntax_error_returns_empty(self):
        self.assertEqual({'sections': [], 'reflections': []},
                         analyze_source('def (: bad', {}))

    def test_none_and_blank_return_empty(self):
        self.assertEqual({'sections': [], 'reflections': []},
                         analyze_source(None))
        self.assertEqual({'sections': [], 'reflections': []},
                         analyze_source('   '))

    def test_non_activity_source_has_no_pattern_reflections(self):
        result = analyze_source('import math\n\nx = 1\n')
        self.assertEqual([], result['reflections'])
        self.assertEqual({'imports'},
                         {section['id'] for section in result['sections']})

    def test_plan_without_prompts_is_fine(self):
        self.assertEqual([], analyze_source('x = 1', {'other': 1})['reflections'])


class TestReflectionsForChange(unittest.TestCase):

    def setUp(self):
        self.source, _ = _generated_activity()

    def test_changed_text_prompt(self):
        new = self.source.replace('Fraction Quest', 'Fraction Adventure')
        prompts = reflections_for_change(self.source, new)
        self.assertTrue(any(p['id'] == 'changed_text' for p in prompts))

    def test_added_method_prompt(self):
        new = self.source + '\n\ndef _brand_new_helper():\n    return 1\n'
        prompts = reflections_for_change(self.source, new)
        self.assertTrue(any(p['id'] == 'added_method' for p in prompts))

    def test_no_change_no_prompts(self):
        self.assertEqual([], reflections_for_change(self.source, self.source))

    def test_unparseable_is_fail_soft(self):
        self.assertEqual([], reflections_for_change('def (:', 'also bad ('))

    def test_caps_at_two(self):
        new = self.source.replace('Fraction Quest', 'X') \
            + '\n\ndef _extra():\n    return 2\n'
        self.assertLessEqual(len(reflections_for_change(self.source, new)), 2)


if __name__ == '__main__':
    unittest.main()
