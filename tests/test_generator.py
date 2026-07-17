# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import hashlib
import json
import shutil
import tempfile
import unittest

from generation.generator import create_prototype_activity
from generation.generator import infer_template
from core.spec import ActivitySpec
from generation.validator import validate_bundle
from generation.validator import validate_project


class TestAodGenerator(unittest.TestCase):

    def setUp(self):
        self.output_root = tempfile.mkdtemp(prefix='aod-generator-test-')

    def tearDown(self):
        shutil.rmtree(self.output_root)

    def test_infers_templates_from_prompt(self):
        cases = (
            ('Draw and paint a picture', 'creation', 'canvas'),
            ('Create a chess board activity', 'games', 'chess'),
            ('Create a carrom activity for two students', 'games', 'carrom'),
            ('Write a collaborative story', 'creation', 'narrative'),
            ('Make a multiplication quiz', 'logic_math', 'quiz'),
            ('Build a pattern grid game', 'games', 'grid'),
            ('Create a word counting tool', 'tools_utils', 'utility'),
            ('Make a black and white pattern board', 'games', 'grid'),
            ('Write a story about a king and queen', 'creation',
             'narrative'),
            ('Create a science vocabulary practice quiz', 'logic_math',
             'quiz'),
            ('Build a classroom timer for group rotations', 'tools_utils',
             'utility'),
            ('Design a habitat map drawing activity', 'creation', 'canvas'),
        )
        for prompt, category, expected in cases:
            spec = ActivitySpec(
                'Demo',
                prompt,
                category,
                'MIT',
            )
            self.assertEqual(expected, infer_template(spec))

    def test_all_templates_generate_valid_projects(self):
        for template in (
                'canvas', 'carrom', 'chess', 'grid', 'narrative', 'quiz',
                'utility'):
            spec = ActivitySpec(
                name='%s Demo' % template.title(),
                prompt='Create a %s learning activity.' % template,
                category='creation',
                license_id='MIT',
                template=template,
            )
            result = create_prototype_activity(spec, self.output_root)
            self.assertTrue(validate_project(result.project_path).valid)
            self.assertTrue(validate_bundle(result.bundle_path).valid)
            self.assertTrue(os.path.isfile(result.bundle_path))
            self.assertIn(
                "gi.require_version('Gtk', '3.0')",
                result.files['activity.py'],
            )

    def test_chess_prompt_generates_playable_board_template(self):
        spec = ActivitySpec(
            name='Chess Club',
            prompt='Create a chess activity for two students.',
            category='games',
            license_id='MIT',
        )
        result = create_prototype_activity(spec, self.output_root)

        self.assertEqual('chess', result.plan['template'])
        self.assertIn('_starting_board', result.files['activity.py'])
        self.assertIn('_can_move', result.files['activity.py'])
        self.assertIn(
            'Move log will appear here.', result.files['activity.py'])
        self.assertTrue(validate_project(result.project_path).valid)

    def test_carrom_prompt_generates_turn_taking_board_template(self):
        spec = ActivitySpec(
            name='Carrom Partners',
            prompt=(
                'Generate a carrom activity where two students take turns, '
                'aim the striker, pocket coins, track fouls, and save the '
                'match.'
            ),
            category='games',
            license_id='MIT',
        )
        result = create_prototype_activity(spec, self.output_root)

        self.assertEqual('carrom', result.plan['template'])
        self.assertIn('_draw_carrom_board', result.files['activity.py'])
        self.assertIn('Pocket queen', result.files['activity.py'])
        self.assertIn('Switch turn', result.files['activity.py'])
        self.assertTrue(validate_project(result.project_path).valid)

    def test_chess_refinement_can_hide_move_tracking(self):
        spec = ActivitySpec(
            name='Clean Chess',
            prompt='Create a chess activity and remove move tracking history.',
            category='games',
            license_id='MIT',
            template='chess',
        )
        result = create_prototype_activity(spec, self.output_root)

        self.assertFalse(result.plan['chess_show_move_log'])
        self.assertIn('self._show_move_log = False',
                      result.files['activity.py'])
        self.assertIn('Clean board mode',
                      result.files['activity.py'])
        self.assertTrue(validate_project(result.project_path).valid)

    def test_utility_prompts_generate_matching_tool_modes(self):
        cases = (
            (
                'Build a classroom timer for group rotations.',
                'timer',
                '_tick_timer',
            ),
            (
                'Create a tally counter for science observations.',
                'counter',
                '_change_count',
            ),
            (
                'Create a word counting tool for draft revision.',
                'word_counter',
                '_update_count',
            ),
        )
        for prompt, mode, source_marker in cases:
            spec = ActivitySpec(
                name='Utility Demo',
                prompt=prompt,
                category='tools_utils',
                license_id='MIT',
            )
            result = create_prototype_activity(spec, self.output_root)

            self.assertEqual('utility', result.plan['template'])
            self.assertEqual(mode, result.plan['utility_mode'])
            self.assertIn(source_marker, result.files['activity.py'])
            self.assertTrue(validate_project(result.project_path).valid)

    def test_license_metadata_is_consistent(self):
        spec = ActivitySpec(
            'License Demo',
            'Create a writing activity.',
            'creation',
            'BSD-3-Clause',
            template='narrative',
        )
        result = create_prototype_activity(spec, self.output_root)
        self.assertIn(
            'license = BSD-3-Clause',
            result.files['activity/activity.info'],
        )
        self.assertIn(
            '# SPDX-License-Identifier: BSD-3-Clause',
            result.files['activity.py'],
        )

    def test_reapply_license_rewrites_bundle_artifacts(self):
        from generation.pipeline import reapply_generation_license

        spec = ActivitySpec(
            'License Switch',
            'Create a writing activity.',
            'creation',
            'MIT',
            template='narrative',
        )
        result = create_prototype_activity(spec, self.output_root)
        self.assertIn('MIT License', result.files['LICENSE'])
        self.assertIn(
            '# SPDX-License-Identifier: MIT',
            result.files['activity.py'],
        )
        self.assertTrue(os.path.isfile(result.bundle_path))

        reapply_generation_license(result, 'BSD-3-Clause')

        self.assertEqual('BSD-3-Clause', result.spec.license_id)
        self.assertEqual('', result.bundle_path)
        self.assertIn('BSD 3-Clause License', result.files['LICENSE'])
        self.assertIn(
            'license = BSD-3-Clause',
            result.files['activity/activity.info'],
        )
        self.assertIn(
            '# SPDX-License-Identifier: BSD-3-Clause',
            result.files['activity.py'],
        )
        self.assertNotIn(
            '# SPDX-License-Identifier: MIT',
            result.files['activity.py'],
        )
        expected_hash = hashlib.sha256(
            result.files['activity.py'].encode('utf-8')).hexdigest()
        self.assertEqual(expected_hash, result.plan['source_hash'])
        with open(os.path.join(result.project_path, 'aod_plan.json'),
                  encoding='utf-8') as plan_file:
            self.assertEqual(expected_hash,
                             json.load(plan_file)['source_hash'])
        with open(os.path.join(result.project_path, 'LICENSE'),
                  encoding='utf-8') as license_file:
            self.assertIn('BSD 3-Clause License', license_file.read())
        self.assertTrue(validate_project(result.project_path).valid)


class TestActivityInfoMetadata(unittest.TestCase):

    def setUp(self):
        self.output_root = tempfile.mkdtemp(prefix='aod-info-test-')

    def tearDown(self):
        shutil.rmtree(self.output_root)

    def _info(self, spec):
        result = create_prototype_activity(spec, self.output_root)
        return result.files['activity/activity.info']

    def test_version_is_stable_semantic_not_timestamp(self):
        info = self._info(ActivitySpec(
            'Version Demo', 'Make a counting activity.', 'logic_math', 'MIT'))
        self.assertIn('activity_version = 1\n', info)

    def test_two_student_board_seats_two_participants(self):
        info = self._info(ActivitySpec(
            'Chess Club', 'Create a chess board for two students.',
            'games', 'MIT'))
        self.assertIn('max_participants = 2\n', info)

    def test_single_user_activity_seats_one(self):
        info = self._info(ActivitySpec(
            'Quiz Time', 'Make a multiplication quiz.', 'logic_math', 'MIT'))
        self.assertIn('max_participants = 1\n', info)

    def test_tags_include_area_and_word_bank(self):
        info = self._info(ActivitySpec(
            'Chess Club', 'Create a chess board for two students.',
            'games', 'MIT'))
        tags_line = [
            line for line in info.splitlines() if line.startswith('tags =')
        ][0]
        self.assertIn('Education', tags_line)
        self.assertIn('Games', tags_line)

    def test_normalize_preserves_explicit_version(self):
        from generation.generator import build_plan
        from generation.generator import normalize_plan
        spec = ActivitySpec('Keep Ver', 'Make a quiz.', 'logic_math', 'MIT')
        base = build_plan(spec)
        self.assertEqual(1, base['activity_version'])
        bumped = dict(base)
        bumped['activity_version'] = 7
        self.assertEqual(7, normalize_plan(spec, bumped)['activity_version'])

    def test_project_includes_valid_translation_template(self):
        spec = ActivitySpec('Po Demo', 'Make a quiz.', 'logic_math', 'MIT')
        result = create_prototype_activity(spec, self.output_root)
        pot_path = os.path.join(result.project_path, 'po', 'PoDemo.pot')
        self.assertTrue(os.path.isfile(pot_path))
        with open(pot_path, encoding='utf-8') as pot_file:
            content = pot_file.read()
        self.assertIn('msgid ""', content)
        self.assertIn('Content-Type: text/plain; charset=UTF-8', content)
        # Packaging still succeeds with the po/ directory present.
        self.assertTrue(os.path.isfile(result.bundle_path))

    def test_extract_translatable_strings_dedupes_in_order(self):
        from generation.generator import _extract_translatable_strings
        source = 'a = _("Hello")\nb = _("World")\nc = _("Hello")\nd = 1\n'
        self.assertEqual(
            ['Hello', 'World'], _extract_translatable_strings(source))
        self.assertEqual([], _extract_translatable_strings('def broken('))
