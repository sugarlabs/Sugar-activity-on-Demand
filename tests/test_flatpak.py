# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import shutil
import tarfile
import tempfile
import unittest

from exports.flatpak import flatpak_app_id
from exports.flatpak import package_flatpak
from exports.flatpak import render_flatpak_manifest
from generation.generator import create_prototype_activity
from core.spec import ActivitySpec


class TestAodFlatpak(unittest.TestCase):

    def setUp(self):
        self.output_root = tempfile.mkdtemp(prefix='aod-flatpak-test-')

    def tearDown(self):
        shutil.rmtree(self.output_root)

    def _make_result(self):
        spec = ActivitySpec(
            name='Flatpak Demo',
            prompt='Create a writing activity.',
            category='creation',
            license_id='MIT',
            template='narrative',
        )
        return create_prototype_activity(spec, self.output_root)

    def test_app_id_matches_bundle_id(self):
        result = self._make_result()
        self.assertEqual(result.plan['bundle_id'],
                         flatpak_app_id(result.plan))

    def test_manifest_targets_gnome_runtime(self):
        result = self._make_result()
        app_id = flatpak_app_id(result.plan)
        manifest = render_flatpak_manifest(result.spec, result.plan, app_id)

        self.assertEqual(app_id, manifest['app-id'])
        self.assertEqual('org.gnome.Platform', manifest['runtime'])
        self.assertEqual('org.gnome.Sdk', manifest['sdk'])
        self.assertEqual('sugar-activity-run', manifest['command'])
        module_names = [module['name'] for module in manifest['modules']]
        self.assertIn('sugar-toolkit-gtk3', module_names)
        self.assertIn('activity', module_names)

    def test_package_flatpak_exports_buildable_sources(self):
        result = self._make_result()
        export = package_flatpak(result)

        # flatpak-builder is not assumed present in CI, so the fallback
        # source bundle is what we can deterministically verify.
        self.assertIn(export['kind'], ('source', 'flatpak'))
        self.assertTrue(os.path.isfile(export['source_path']))
        self.assertTrue(export['source_path'].endswith('.tar.gz'))
        self.assertEqual(result.plan['bundle_id'], export['app_id'])

        app_id = export['app_id']
        with tarfile.open(export['source_path'], 'r:gz') as tar:
            names = tar.getnames()
            manifest_member = None
            for name in names:
                if name.endswith('%s.json' % app_id):
                    manifest_member = name
                    break
            self.assertIsNotNone(manifest_member)
            manifest = json.loads(
                tar.extractfile(manifest_member).read().decode('utf-8'))

        self.assertEqual(app_id, manifest['app-id'])

        base = os.path.basename(manifest_member).rsplit('/', 1)[-1]
        self.assertTrue(base.endswith('.json'))
        joined = '\n'.join(names)
        self.assertIn('build.sh', joined)
        self.assertIn('README.md', joined)
        self.assertIn('sugar-activity-run', joined)
        self.assertIn('activity-src/activity.py', joined)

    def test_malicious_bundle_id_falls_back_to_safe_id(self):
        # A provider/LLM-supplied bundle_id must never reach a filename or
        # shell verbatim; invalid ids fall back to a safe deterministic id.
        result = self._make_result()
        for evil in ('../../evil', 'org.x"; rm -rf $HOME; echo "', '../pwn',
                     'no-dots-here', '9.starts.with.digit', '', 'a/b/c',
                     'org.looks.valid\n', 'org.looks.valid\nrm -rf /'):
            result.plan['bundle_id'] = evil
            app_id = flatpak_app_id(result.plan)
            self.assertTrue(app_id.startswith('org.sugarlabs.aod.'))
            self.assertRegex(app_id, r'^[A-Za-z0-9_.]+$')

    def test_valid_bundle_id_is_preserved(self):
        result = self._make_result()
        result.plan['bundle_id'] = 'org.sugarlabs.aod.MyThing1234'
        self.assertEqual('org.sugarlabs.aod.MyThing1234',
                         flatpak_app_id(result.plan))

    def test_malicious_bundle_id_does_not_escape_staging(self):
        result = self._make_result()
        result.plan['bundle_id'] = '../../../pwned'
        export = package_flatpak(result)

        flatpak_root = os.path.abspath(
            result.project_path.rstrip(os.sep) + '-flatpak')
        with tarfile.open(export['source_path'], 'r:gz') as tar:
            for name in tar.getnames():
                self.assertNotIn('..', name.split('/'))
        # No manifest written outside the intended flatpak staging area.
        self.assertFalse(os.path.exists(
            os.path.join(os.path.dirname(flatpak_root), 'pwned.json')))

    def test_export_reports_builder_availability(self):
        result = self._make_result()
        export = package_flatpak(result)
        self.assertIn('builder_available', export)
        self.assertIsInstance(export['builder_available'], bool)

    def test_export_always_includes_a_reason_field(self):
        result = self._make_result()
        export = package_flatpak(result)
        self.assertIn('reason', export)
        self.assertIsInstance(export['reason'], str)
        # A source-only export must explain why; a built .flatpak need not.
        if export['kind'] == 'source':
            self.assertTrue(export['reason'])

    def test_build_failure_surfaces_reason_and_keeps_sources(self):
        import exports.flatpak as flatpak_module
        result = self._make_result()
        original_available = flatpak_module.flatpak_builder_available
        original_build = flatpak_module._build_flatpak_bundle
        flatpak_module.flatpak_builder_available = lambda: True
        flatpak_module._build_flatpak_bundle = (
            lambda *args: (None, 'flatpak-builder could not build the '
                                 'bundle: manifest error'))
        try:
            export = package_flatpak(result)
        finally:
            flatpak_module.flatpak_builder_available = original_available
            flatpak_module._build_flatpak_bundle = original_build
        self.assertEqual('source', export['kind'])
        self.assertIn('manifest error', export['reason'])
        self.assertTrue(os.path.isfile(export['source_path']))

    def test_package_flatpak_does_not_pollute_xo_project(self):
        result = self._make_result()
        package_flatpak(result)

        # Flatpak artifacts must live in a sibling directory so they never
        # end up inside the .xo bundle built from the project directory.
        for root, _dirs, filenames in os.walk(result.project_path):
            for filename in filenames:
                self.assertFalse(filename.endswith('.tar.gz'))
                self.assertNotEqual(filename, 'build.sh')
