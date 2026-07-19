# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import hashlib
import json
import shutil
import tempfile
import threading
import unittest
import zipfile

from llm.credentials import AODCredentialStore
from llm.providers import ProviderError
from generation.generator import enrich_plan
from generation.pipeline import package_generation_result
from service.jobs import AODJob
from service.jobs import AODJobStore
from service.jobs import STATUS_CANCELLED
from service.jobs import STATUS_FAILED
from service.jobs import STATUS_FINISHED
from service.jobs import STATUS_GENERATING
from service.sessions import AODSessionStore
from service.sessions import ROLE_ASSISTANT
from service.sessions import ROLE_USER
from service.sessions import TYPE_RESULT
from service.service import AODService
from core.spec import ActivitySpec
from generation.templates import render_activity_source


class TestAodService(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='aod-service-test-')
        self.project_root = os.path.join(self.root, 'projects')
        self.job_root = os.path.join(self.root, 'jobs')
        self.session_root = os.path.join(self.root, 'sessions')
        self.store = AODJobStore(self.job_root)
        self.session_store = AODSessionStore(self.session_root)
        self.secret_backend = _MemorySecretBackend()
        self.credential_store = AODCredentialStore(
            os.path.join(self.root, 'credentials'),
            secret_backend=self.secret_backend,
        )
        self.service = AODService(
            self.store,
            worker_count=1,
            credential_store=self.credential_store,
            session_store=self.session_store,
        )

    def tearDown(self):
        self.service.shutdown()
        shutil.rmtree(self.root)

    def test_submit_activity_runs_job_and_persists_summary(self):
        events = []
        spec = ActivitySpec(
            'Queue Demo',
            'Create a quiz about queues.',
            'logic_math',
            'MIT',
            template='quiz',
        )

        job = self.service.submit_activity(
            spec,
            provider_name='local-template',
            output_root=self.project_root,
            callback=lambda updated: events.append(updated.status),
        )
        finished = self._wait_for_terminal(job.job_id)

        self.assertEqual(STATUS_FINISHED, finished.status)
        self.assertTrue(os.path.isdir(finished.result.project_path))
        self.assertEqual('', finished.result.bundle_path)
        self.assertIn(STATUS_FINISHED, events)

        persisted = self.store.load(job.job_id)
        self.assertEqual(STATUS_FINISHED, persisted.status)
        self.assertEqual(
            finished.result.bundle_id,
            persisted.result_summary['bundle_id'],
        )
        session = self.service.get_session(finished.session_id)
        self.assertIsNotNone(session)
        self.assertEqual(finished.result_summary['revision_id'],
                         session.active_revision_id)
        self.assertEqual(1, len(session.revisions))
        self.assertEqual(ROLE_USER, session.messages[0].role)
        self.assertTrue(any(
            message.role == ROLE_ASSISTANT and
            message.message_type == TYPE_RESULT and
            message.revision_id == session.active_revision_id
            for message in session.messages
        ))

    def test_unwatch_removes_bound_method_callback(self):
        observer = _Observer()
        self.service.watch('job-id', observer.callback)
        self.service.unwatch('job-id', observer.callback)
        self.assertNotIn('job-id', self.service._callbacks)

    def test_repair_state_is_persisted_without_losing_original_source(self):
        spec = ActivitySpec(
            'Repair State', 'Create a quiz.', 'logic_math', 'MIT')
        job = AODJob.create(spec, provider_name='openai')
        self.service._set_progress(
            job,
            STATUS_GENERATING,
            'generating',
            0.5,
            'Repairing',
            {
                'draft_activity_source': 'original source\n',
                'initial_activity_source': True,
                'repair_event': {
                    'attempt': 1,
                    'outcome': 'verification_rejected',
                },
                'repair_diagnostics': {
                    'stage': 'static_validation',
                    'errors': ['broken'],
                },
            },
        )
        self.service._set_progress(
            job,
            STATUS_GENERATING,
            'generating',
            0.4,
            'Out-of-order callback',
        )
        self.assertEqual(0.5, job.progress)
        # A committed repair candidate always arrives with its repair
        # event (see the pipeline's verify_candidate); bare draft ticks
        # are streaming updates and are intentionally not persisted on
        # every callback.
        self.service._set_progress(
            job,
            STATUS_GENERATING,
            'generating',
            0.6,
            'Repair improved',
            {
                'draft_activity_source': 'improved source\n',
                'repair_event': {
                    'attempt': 2,
                    'outcome': 'improved_committed',
                },
            },
        )

        persisted = self.store.load(job.job_id)
        self.assertEqual('original source\n',
                         persisted.original_activity_source)
        self.assertEqual('improved source\n',
                         persisted.draft_activity_source)
        self.assertEqual('verification_rejected',
                         persisted.repair_history[0]['outcome'])
        self.assertEqual('static_validation',
                         persisted.repair_diagnostics['stage'])

    def test_job_round_trips_resume_fields(self):
        spec = ActivitySpec('Round Trip', 'Create a quiz.', 'logic_math',
                            'MIT')
        job = AODJob.create(spec, provider_name='openai')
        job.is_resume = True
        job.repair_plan = {'bundle_id': 'org.sugarlabs.aod.Demo1234567890'}
        self.store.save(job)
        restored = self.store.load(job.job_id)
        self.assertTrue(restored.is_resume)
        self.assertEqual('org.sugarlabs.aod.Demo1234567890',
                         restored.repair_plan['bundle_id'])

    def test_resume_repair_finishes_from_preserved_draft(self):
        from generation.generator import enrich_plan
        from generation.templates import render_activity_source

        provider = _ResumeRepairProvider()
        self.service.register_provider(provider)
        spec = ActivitySpec(
            'Resume Demo', 'Create a quiz.', 'logic_math', 'MIT',
            template='quiz')
        good = render_activity_source(
            spec, enrich_plan(spec, {'template': 'quiz'}))
        draft = good.replace(
            'class GeneratedActivity(activity.Activity):',
            'class GeneratedActivity(object):')

        failed = AODJob.create(spec, provider_name='openai',
                               output_root=self.project_root)
        failed.draft_activity_source = draft
        failed.repair_diagnostics = {
            'stage': 'static_validation',
            'errors': ['Generated source must define exactly one Activity '
                       'subclass.'],
            'warnings': [],
        }
        failed.repair_plan = enrich_plan(spec, {'template': 'quiz'})
        failed.fail('Provider could not repair activity code.')
        self.store.save(failed)
        with self.service._lock:
            self.service._jobs[failed.job_id] = failed

        resumed = self.service.resume_repair(failed.job_id)
        self.assertIsNotNone(resumed)
        self.assertTrue(resumed.is_resume)

        finished = self._wait_for_terminal(resumed.job_id)
        self.assertEqual(STATUS_FINISHED, finished.status)
        self.assertIn('class GeneratedActivity(activity.Activity):',
                      finished.result.files['activity.py'])

    def test_resume_repair_without_draft_returns_none(self):
        spec = ActivitySpec('No Draft', 'Create a quiz.', 'logic_math', 'MIT')
        failed = AODJob.create(spec, provider_name='openai')
        failed.fail('failed before any draft')
        self.store.save(failed)
        with self.service._lock:
            self.service._jobs[failed.job_id] = failed
        self.assertIsNone(self.service.resume_repair(failed.job_id))

    def test_finished_job_restores_result_after_service_restart(self):
        spec = ActivitySpec(
            'Restore Demo',
            'Create a writing activity.',
            'creation',
            'MIT',
            template='narrative',
        )
        job = self.service.submit_activity(
            spec,
            provider_name='local-template',
            output_root=self.project_root,
        )
        finished = self._wait_for_terminal(job.job_id)
        self.assertEqual(STATUS_FINISHED, finished.status)

        self.service.shutdown()
        self.service = AODService(
            self.store,
            worker_count=1,
            credential_store=self.credential_store,
            session_store=self.session_store,
        )
        restored = self.service.get_job(job.job_id)

        self.assertEqual(STATUS_FINISHED, restored.status)
        self.assertIsNotNone(restored.result)
        self.assertEqual(
            finished.result.bundle_id,
            restored.result.bundle_id,
        )
        self.assertIn('activity.py', restored.result.files)

    def test_missing_artifacts_mark_restored_job_failed(self):
        spec = ActivitySpec(
            'Missing Demo',
            'Create a simple quiz.',
            'logic_math',
            'MIT',
            template='quiz',
        )
        job = self.service.submit_activity(
            spec,
            provider_name='local-template',
            output_root=self.project_root,
        )
        finished = self._wait_for_terminal(job.job_id)
        shutil.rmtree(finished.result.project_path)

        self.service.shutdown()
        self.service = AODService(
            self.store,
            worker_count=1,
            credential_store=self.credential_store,
            session_store=self.session_store,
        )
        restored = self.service.get_job(job.job_id)

        self.assertEqual(STATUS_FAILED, restored.status)
        self.assertIsNone(restored.result)
        self.assertIn('no longer available', restored.error)

    def test_runtime_provider_runs_without_persisting_its_secret(self):
        secret = 'aod-session-secret-must-not-be-saved'
        provider = _RuntimeProvider(secret)
        self.service.register_provider(provider)
        spec = ActivitySpec(
            'Runtime Provider Demo',
            'Create a teamwork quiz.',
            'logic_math',
            'MIT',
            template='quiz',
        )

        job = self.service.submit_activity(
            spec,
            provider_name='openai',
            use_rag=False,
            output_root=self.project_root,
        )
        finished = self._wait_for_terminal(job.job_id)

        self.assertEqual(STATUS_FINISHED, finished.status)
        self.assertEqual('openai', finished.result.provider)
        self.assertEqual('runtime-test', finished.result.model)
        self.assertFalse(
            self.service.has_runtime_provider('not-configured')
        )

        job_path = os.path.join(self.job_root, job.job_id + '.json')
        with open(job_path, encoding='utf-8') as job_file:
            persisted_job = job_file.read()
        self.assertNotIn(secret, persisted_job)
        for contents in finished.result.files.values():
            self.assertNotIn(secret, contents)
        package_generation_result(finished.result)
        with zipfile.ZipFile(finished.result.bundle_path) as bundle:
            for filename in bundle.namelist():
                self.assertNotIn(
                    secret.encode('utf-8'),
                    bundle.read(filename),
                )

    def test_runtime_provider_is_reported_as_configured(self):
        self.service.register_provider(_RuntimeProvider('session-secret'))

        statuses = {
            status['name']: status
            for status in self.service.provider_statuses()
        }
        self.assertTrue(statuses['openai']['configured'])
        self.assertEqual('runtime-test', statuses['openai']['model'])

    def test_resolve_provider_returns_runtime_override(self):
        provider = _RuntimeProvider('session-secret')
        self.service.register_provider(provider)
        self.assertIs(provider, self.service.resolve_provider('openai'))

    def test_resolve_provider_uses_saved_api_key(self):
        self.service.configure_provider(
            'openai', api_key='saved-key', model='saved-model', persist=True)
        resolved = self.service.resolve_provider('openai')
        self.assertIsNotNone(resolved)
        self.assertEqual('openai', resolved.name)

    def test_resolve_provider_none_for_local_and_unconfigured(self):
        self.assertIsNone(self.service.resolve_provider('local-template'))
        self.assertIsNone(self.service.resolve_provider('openai'))

    def test_saved_provider_settings_load_after_service_restart(self):
        secret = 'saved-service-secret'
        provider = self.service.configure_provider(
            'openai',
            api_key=secret,
            model='saved-model',
            endpoint='https://example.test/v1/chat/completions',
            persist=True,
        )
        self.assertEqual('saved-model', provider.model)

        self.service.shutdown()
        self.service = AODService(
            self.store,
            worker_count=1,
            credential_store=self.credential_store,
            session_store=self.session_store,
        )
        restored = self.service.configure_provider('openai')

        self.assertEqual('saved-model', restored.model)
        self.assertEqual(secret, restored._api_key)
        self.assertEqual('openai', self.service.preferred_provider_name())

    def test_remove_saved_provider_key_clears_runtime_provider(self):
        self.service.configure_provider(
            'gemini',
            api_key='remove-service-secret',
            persist=True,
        )
        self.assertTrue(self.service.has_runtime_provider('gemini'))

        self.assertTrue(self.service.remove_provider_api_key('gemini'))
        self.assertFalse(self.service.has_runtime_provider('gemini'))
        status = self.service.provider_credential_status('gemini')
        self.assertFalse(status['has_api_key'])

    def test_refinement_job_appends_revision_to_existing_session(self):
        first = ActivitySpec(
            'Draw Together',
            'Create an activity where two learners draw together.',
            'creation',
            'MIT',
            template='canvas',
        )
        first_job = self.service.submit_activity(
            first,
            provider_name='local-template',
            output_root=self.project_root,
            user_prompt=first.prompt,
        )
        first_finished = self._wait_for_terminal(first_job.job_id)
        self.assertEqual(STATUS_FINISHED, first_finished.status)

        second = ActivitySpec(
            'Draw Together',
            'Refine the existing activity. Add a switch-student button.',
            'creation',
            'MIT',
            template='canvas',
        )
        self.service.register_provider(_RefinementProvider())
        second_job = self.service.submit_activity(
            second,
            provider_name='openai',
            output_root=self.project_root,
            session_id=first_finished.session_id,
            parent_revision_id=first_finished.result_summary['revision_id'],
            user_prompt='Add a switch-student button.',
        )
        second_finished = self._wait_for_terminal(second_job.job_id)
        self.assertEqual(STATUS_FINISHED, second_finished.status)

        first_source = first_finished.result.files['activity.py']
        second_source = second_finished.result.files['activity.py']
        self.assertIn('# switch-student repair marker', second_source)
        self.assertEqual(
            hashlib.sha256(first_source.encode('utf-8')).hexdigest(),
            second_finished.result_summary['parent_source_hash'],
        )

        session = self.service.get_session(first_finished.session_id)
        self.assertEqual(2, len(session.revisions))
        self.assertEqual(
            first_finished.result_summary['revision_id'],
            session.revisions[1].parent_revision_id,
        )
        self.assertEqual(
            second_finished.result_summary['revision_id'],
            session.active_revision_id,
        )

    def test_local_refinement_fails_with_parent_source_preserved(self):
        spec = ActivitySpec(
            'Preserve Local', 'Create a writing activity.', 'creation',
            'MIT', template='narrative')
        first_job = self.service.submit_activity(
            spec,
            provider_name='local-template',
            output_root=self.project_root,
        )
        first = self._wait_for_terminal(first_job.job_id)
        self.assertEqual(STATUS_FINISHED, first.status)

        second_job = self.service.submit_activity(
            spec,
            provider_name='local-template',
            output_root=self.project_root,
            session_id=first.session_id,
            parent_revision_id=first.result_summary['revision_id'],
            user_prompt='Add another writing prompt.',
        )
        second = self._wait_for_terminal(second_job.job_id)

        self.assertEqual(STATUS_FAILED, second.status)
        self.assertEqual(first.result.files['activity.py'],
                         second.original_activity_source)
        self.assertEqual(first.result.files['activity.py'],
                         second.draft_activity_source)
        self.assertIn('was not regenerated', second.error)

    def test_refinement_rejects_parent_source_lineage_mismatch(self):
        spec = ActivitySpec(
            'Lineage Check', 'Create a writing activity.', 'creation',
            'MIT', template='narrative')
        first_job = self.service.submit_activity(
            spec,
            provider_name='local-template',
            output_root=self.project_root,
        )
        first = self._wait_for_terminal(first_job.job_id)
        source = first.result.files['activity.py']
        expected_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
        plan_path = os.path.join(first.result.project_path, 'aod_plan.json')
        with open(plan_path, encoding='utf-8') as plan_file:
            plan = json.load(plan_file)
        plan['source_hash'] = expected_hash
        with open(plan_path, 'w', encoding='utf-8') as plan_file:
            json.dump(plan, plan_file)
        with open(os.path.join(first.result.project_path, 'activity.py'),
                  'a', encoding='utf-8') as source_file:
            source_file.write('\n# external-tamper\n')

        self.service.register_provider(_RefinementProvider())
        second_job = self.service.submit_activity(
            spec,
            provider_name='openai',
            output_root=self.project_root,
            session_id=first.session_id,
            parent_revision_id=first.result_summary['revision_id'],
        )
        second = self._wait_for_terminal(second_job.job_id)

        self.assertEqual(STATUS_FAILED, second.status)
        self.assertIn('source lineage', second.error)

    def test_pipeline_error_after_cancel_is_reported_as_cancelled(self):
        # A cancellation that surfaces as a pipeline error (e.g. raised out of
        # the repair loop or a provider call after cancel) must be recorded as
        # cancelled, not as a spurious failure.
        started = threading.Event()
        release = threading.Event()

        class _CancelAwareProvider:
            name = 'openai'
            label = 'OpenAI'
            model = 'cancel-1'

            def generate_plan(self, system_prompt, user_prompt, timeout=45):
                started.set()
                release.wait(5)
                raise ProviderError('provider failed after cancel')

        self.service.register_provider(_CancelAwareProvider())
        spec = ActivitySpec(
            'Cancel Demo', 'Create a quiz.', 'logic_math', 'MIT')
        job = self.service.submit_activity(
            spec, provider_name='openai', output_root=self.project_root)

        self.assertTrue(started.wait(5))
        self.service.cancel_job(job.job_id)
        release.set()

        finished = self._wait_for_terminal(job.job_id)
        self.assertEqual(STATUS_CANCELLED, finished.status)

    def _wait_for_terminal(self, job_id):
        # Event-driven wait via the service's own watch() hook: returns
        # the instant the job finishes, so suite load can't push a
        # healthy job past a polling budget.  The generous deadline is a
        # true hang detector, not a performance bet.
        import threading

        done = threading.Event()

        def on_update(updated):
            if updated.is_terminal():
                done.set()

        self.service.watch(job_id, on_update)
        try:
            job = self.service.get_job(job_id)
            if job is not None and job.is_terminal():
                return job
            if not done.wait(timeout=60):
                self.fail('Timed out waiting for AOD job to finish.')
        finally:
            self.service.unwatch(job_id, on_update)
        return self.service.get_job(job_id)


class _Observer:

    def callback(self, job):
        pass


class _RuntimeProvider:
    name = 'openai'
    label = 'OpenAI'
    model = 'runtime-test'

    def __init__(self, api_key):
        self._api_key = api_key

    def generate_plan(self, system_prompt, user_prompt, timeout=45):
        return {
            'template': 'quiz',
            'summary': 'A runtime-provider quiz.',
            'learner_goal': 'Practice teamwork.',
            'learner_steps': ['Choose', 'Discuss', 'Share'],
            'word_bank': ['team', 'answer'],
        }

    def generate_activity_source(self, system_prompt, user_prompt,
                                 timeout=90):
        spec = ActivitySpec(
            'Runtime Provider Demo',
            'Create a teamwork quiz.',
            'logic_math',
            'MIT',
            template='quiz',
        )
        return render_activity_source(
            spec,
            enrich_plan(spec, self.generate_plan('', '')),
        )


class _RefinementProvider:
    name = 'openai'
    label = 'OpenAI'
    model = 'repair-test'

    def generate_plan(self, system_prompt, user_prompt, timeout=45):
        return {}

    def generate_text(self, system_prompt, user_prompt, timeout=120,
                      stream_callback=None):
        if 'editing an existing Sugar activity' not in system_prompt:
            raise AssertionError('Expected refinement patch prompt')
        return (
            '<<<<<<< SEARCH\n'
            'class GeneratedActivity(activity.Activity):\n'
            '=======\n'
            'class GeneratedActivity(activity.Activity):\n'
            '    # switch-student repair marker\n'
            '>>>>>>> REPLACE'
        )


class _ResumeRepairProvider:
    name = 'openai'
    label = 'OpenAI'
    model = 'resume-test'

    def generate_plan(self, system_prompt, user_prompt, timeout=45):
        return {}

    def generate_text(self, system_prompt, user_prompt, timeout=120,
                      stream_callback=None):
        return (
            '<<<<<<< SEARCH\n'
            'class GeneratedActivity(object):\n'
            '=======\n'
            'class GeneratedActivity(activity.Activity):\n'
            '>>>>>>> REPLACE'
        )


class _MemorySecretBackend:

    def __init__(self):
        self.values = {}

    def store(self, provider_name, api_key):
        self.values[provider_name] = api_key
        return True

    def lookup(self, provider_name):
        return self.values.get(provider_name)

    def clear(self, provider_name):
        return self.values.pop(provider_name, None) is not None
