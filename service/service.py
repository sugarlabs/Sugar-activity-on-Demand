# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import hashlib
import logging
import os
import threading
import time

from llm.credentials import AODCredentialStore
from llm.credentials import CredentialStoreError
from llm.credentials import known_provider_names
from generation.generator import restore_generation_result
from service.jobs import AODJob
from service.jobs import AODJobStore
from service.jobs import STATUS_FAILED
from service.jobs import STATUS_FINISHED
from service.jobs import STATUS_GENERATING
from service.jobs import STATUS_GROUNDING
from service.jobs import STATUS_PACKAGING
from service.jobs import STATUS_PLANNING
from service.jobs import STATUS_PROVIDER
from service.jobs import STATUS_QUEUED
from service.jobs import STATUS_VALIDATING
from llm.providers import create_provider
from llm.providers import get_default_provider_name
from llm.providers import get_local_provider_name
from llm.providers import get_provider_statuses
from llm.providers import normalize_provider_name
from generation.pipeline import generate_activity
from service.queue import AODJobQueue
from service.sessions import AODMessage
from service.sessions import AODRevision
from service.sessions import AODSessionStore
from service.sessions import ROLE_ASSISTANT
from service.sessions import ROLE_USER
from service.sessions import TYPE_ERROR
from service.sessions import TYPE_PROMPT
from service.sessions import TYPE_RESULT
from service.sessions import TYPE_STATUS


class JobCancelled(Exception):
    pass


class AODService:
    """Local backend service for generated Sugar activities."""

    def __init__(self, job_store=None, worker_count=1,
                 credential_store=None, session_store=None):
        self._store = job_store or AODJobStore()
        self._credential_store = credential_store or AODCredentialStore()
        self._session_store = session_store or AODSessionStore()
        self._lock = threading.RLock()
        self._callbacks = {}
        self._jobs = {}
        self._provider_overrides = {}
        self._job_providers = {}
        self._last_progress_save = 0.0
        self._load_jobs()
        self._queue = AODJobQueue(self._run_job, worker_count=worker_count)

    def submit_activity(self, spec, provider_name='default', use_rag=True,
                        validate_code=True, output_root=None, callback=None,
                        session_id='', parent_revision_id='',
                        user_prompt=None, enhance=True):
        errors = spec.validate()
        if errors:
            raise ValueError('\n'.join(errors))

        provider_name = normalize_provider_name(provider_name)
        if provider_name == 'default':
            provider_name = self.preferred_provider_name()
        session = self._ensure_session(spec, session_id)
        prompt_text = user_prompt or spec.prompt
        job = AODJob.create(
            spec,
            provider_name=provider_name,
            use_rag=use_rag,
            validate_code=validate_code,
            output_root=output_root,
            session_id=session.session_id,
            parent_revision_id=parent_revision_id,
            user_prompt=prompt_text,
            enhance=enhance,
        )
        if callback is not None:
            self.watch(job.job_id, callback)

        with self._lock:
            self._jobs[job.job_id] = job
            provider = self._provider_overrides.get(provider_name)
            if provider is None:
                provider = self._load_saved_provider(provider_name)
            if provider is not None:
                self._job_providers[job.job_id] = provider
            self._store.save(job)

        self._record_user_prompt(session.session_id, job, prompt_text)
        self._notify(job)
        self._queue.submit(job)
        return job

    def resume_repair(self, failed_job_id, callback=None):
        """Continue repairing the preserved draft of a failed job.

        Seeds a fresh job from the failed job's draft, diagnostics, and plan
        and runs it through the repair-only path.  Returns the new job, or
        ``None`` when there is no draft to continue from.
        """
        source_job = self.get_job(failed_job_id)
        if source_job is None:
            source_job = self._store.load(failed_job_id)
        if source_job is None or not source_job.draft_activity_source:
            return None

        job = AODJob.create(
            source_job.spec,
            provider_name=source_job.provider_name,
            use_rag=source_job.use_rag,
            validate_code=source_job.validate_code,
            output_root=source_job.output_root or None,
            session_id=source_job.session_id,
            user_prompt=source_job.user_prompt or source_job.spec.prompt,
            enhance=False,
            # Keep the revision lineage: the repaired result is still a
            # child of the revision the failed refinement was editing.
            parent_revision_id=source_job.parent_revision_id,
        )
        job.is_resume = True
        job.draft_activity_source = source_job.draft_activity_source
        job.original_activity_source = (
            source_job.original_activity_source
            or source_job.draft_activity_source)
        job.repair_diagnostics = dict(source_job.repair_diagnostics or {})
        job.repair_plan = dict(source_job.repair_plan or {})
        job.repair_history = list(source_job.repair_history or [])

        if callback is not None:
            self.watch(job.job_id, callback)

        with self._lock:
            self._jobs[job.job_id] = job
            provider = self._provider_overrides.get(job.provider_name)
            if provider is None:
                provider = self._load_saved_provider(job.provider_name)
            if provider is not None:
                self._job_providers[job.job_id] = provider
            self._store.save(job)

        if job.session_id:
            # Leave a transcript record, mirroring submit_activity's status
            # half; without it the session jumps from the failure straight
            # to a finished result with no trace of the continuation.
            self._session_store.append_messages(job.session_id, [
                AODMessage.create(
                    ROLE_ASSISTANT,
                    'Continuing repair of the failed draft...',
                    message_type=TYPE_STATUS,
                    job_id=job.job_id,
                ),
            ])
        self._notify(job)
        self._queue.submit(job)
        return job

    def watch(self, job_id, callback):
        with self._lock:
            self._callbacks.setdefault(job_id, []).append(callback)

    def unwatch(self, job_id, callback=None):
        with self._lock:
            if job_id not in self._callbacks:
                return
            if callback is None:
                del self._callbacks[job_id]
                return
            self._callbacks[job_id] = [
                item for item in self._callbacks[job_id]
                if item != callback
            ]
            if not self._callbacks[job_id]:
                del self._callbacks[job_id]

    def get_job(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self):
        with self._lock:
            return sorted(
                self._jobs.values(),
                key=lambda job: job.created_at,
                reverse=True,
            )

    def get_session(self, session_id):
        return self._session_store.load(session_id)

    def list_sessions(self):
        return self._session_store.list_sessions()

    def cancel_job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.is_terminal():
                return False
            job.request_cancel()
            if job.status == STATUS_QUEUED:
                job.cancel()
            self._store.save(job)
        self._notify(job)
        return True

    def provider_statuses(self):
        statuses = get_provider_statuses()
        with self._lock:
            overrides = dict(self._provider_overrides)

        for status in statuses:
            provider = overrides.get(status['name'])
            # Derived from the store's own registry so the two lists can
            # never drift again: the old hardcoded tuple omitted
            # 'openrouter', so a saved OpenRouter key (the default
            # provider!) never showed as configured in the picker.
            credentials = self._credential_store.provider_status(
                status['name']
            ) if status['name'] in known_provider_names() else {}
            ollama_configured = status['name'] == 'ollama' and any((
                credentials.get('model'),
                credentials.get('endpoint'),
            ))
            if provider is not None:
                status['available'] = True
                status['configured'] = True
                status['model'] = provider.model
                status['reason'] = ''
            elif credentials.get('has_api_key') or ollama_configured:
                status['available'] = True
                status['configured'] = True
                status['model'] = credentials.get('model') or status['model']
                status['reason'] = ''
        return statuses

    def configure_provider(self, provider_name, api_key=None, model=None,
                           endpoint=None, persist=False):
        provider_name = normalize_provider_name(provider_name)
        if persist:
            self._credential_store.save_provider(
                provider_name,
                api_key=api_key,
                model=model,
                endpoint=endpoint,
            )

        saved = self._credential_store.load_provider(provider_name)
        provider = create_provider(
            provider_name,
            api_key=api_key or saved['api_key'] or None,
            model=model or saved['model'] or None,
            endpoint=endpoint or saved['endpoint'] or None,
        )
        if provider is None:
            return None
        return self.register_provider(provider)

    def provider_credential_status(self, provider_name):
        provider_name = normalize_provider_name(provider_name)
        return self._credential_store.provider_status(provider_name)

    def remove_provider_api_key(self, provider_name):
        provider_name = normalize_provider_name(provider_name)
        removed = self._credential_store.remove_api_key(provider_name)
        self.clear_provider(provider_name)
        return removed

    def register_provider(self, provider):
        provider_name = normalize_provider_name(provider.name)
        if provider_name in ('default', 'local-template'):
            raise ValueError(
                'Only concrete LLM providers can be registered.'
            )
        if not callable(getattr(provider, 'generate_plan', None)):
            raise TypeError('Provider must define generate_plan().')

        with self._lock:
            self._provider_overrides[provider_name] = provider
        return provider

    def clear_provider(self, provider_name):
        provider_name = normalize_provider_name(provider_name)
        with self._lock:
            self._provider_overrides.pop(provider_name, None)

    def has_runtime_provider(self, provider_name):
        provider_name = normalize_provider_name(provider_name)
        with self._lock:
            return provider_name in self._provider_overrides

    def preferred_local_provider_name(self):
        if self.has_runtime_provider('ollama'):
            return 'ollama'
        ollama = self._credential_store.provider_status('ollama')
        if ollama['model'] or ollama['endpoint']:
            return 'ollama'
        return get_local_provider_name()

    def preferred_provider_name(self):
        saved_provider = \
            self._credential_store.get_default_provider_name()
        if saved_provider:
            return saved_provider
        return get_default_provider_name()

    def resolve_provider(self, provider_name='default'):
        """Return a ready provider for interactive use, or None.

        Mirrors how generation resolves a provider so callers (e.g. the
        guided questions/plan flow) see the same one that will build the
        activity: expand 'default', then prefer a runtime override, then
        a saved API key from the credential store, then environment
        configuration.  Returns None for the local template (no model).
        """
        name = normalize_provider_name(provider_name)
        if name == 'default':
            name = normalize_provider_name(self.preferred_provider_name())
        if name in ('local-template', 'local'):
            return None
        with self._lock:
            override = self._provider_overrides.get(name)
        if override is not None:
            return override
        saved = self._load_saved_provider(name)
        if saved is not None:
            return saved
        try:
            return create_provider(name)
        except Exception:
            return None

    def shutdown(self, wait=True):
        self._queue.shutdown(wait=wait)

    # Terminal jobs kept on disk (and loaded at startup); each record
    # embeds full draft/original sources, so an unbounded store grows
    # startup cost, memory, and flash wear forever.
    _JOB_RETENTION_LIMIT = 50

    def _load_jobs(self):
        jobs = self._store.list_jobs()

        # list_jobs is newest-first; prune terminal records beyond the
        # cap, but never a failed job whose draft is still resumable via
        # 'Continue repairing'.
        terminal_seen = 0
        pruned = []
        for job in jobs:
            if not job.is_terminal():
                continue
            terminal_seen += 1
            if terminal_seen <= self._JOB_RETENTION_LIMIT:
                continue
            if job.status == STATUS_FAILED and job.draft_activity_source:
                continue
            pruned.append(job)
        for job in pruned:
            self._store.delete(job.job_id)
        pruned_ids = {job.job_id for job in pruned}

        for job in jobs:
            if job.job_id in pruned_ids:
                continue
            if not job.is_terminal():
                job.fail('Sugar restarted before this job finished.')
                self._store.save(job)
                self._record_failed_message(job)
            elif job.status == STATUS_FINISHED:
                try:
                    job.result = restore_generation_result(
                        job.spec,
                        job.result_summary,
                    )
                except (OSError, TypeError, ValueError):
                    logging.exception(
                        'Could not restore Activity-on-Demand result'
                    )
                    job.result = None
                if job.result is None:
                    # Demote in memory only: a transient miss (e.g. the
                    # output volume not mounted yet at startup) must not
                    # permanently destroy a finished record on disk.  The
                    # next startup retries the restore and self-heals when
                    # the artifacts are back.
                    job.status = STATUS_FAILED
                    job.stage = STATUS_FAILED
                    job.error = (
                        'Generated activity artifacts are no longer available.'
                    )
                    job.message = job.error
            self._jobs[job.job_id] = job

    def _ensure_session(self, spec, session_id=''):
        if session_id:
            session = self._session_store.load(session_id)
            if session is not None:
                return session
        return self._session_store.create_session(spec)

    def _record_user_prompt(self, session_id, job, prompt_text):
        message = AODMessage.create(
            ROLE_USER,
            prompt_text,
            message_type=TYPE_PROMPT,
            job_id=job.job_id,
        )
        status = AODMessage.create(
            ROLE_ASSISTANT,
            'Generating Sugar activity...',
            message_type=TYPE_STATUS,
            job_id=job.job_id,
        )
        self._session_store.append_messages(session_id, [message, status])

    def _run_job(self, job):
        try:
            self._run_job_inner(job)
        finally:
            with self._lock:
                self._job_providers.pop(job.job_id, None)

    def _load_saved_provider(self, provider_name):
        if provider_name not in ('gemini', 'openai', 'openrouter',
                                 'deepseek', 'qwen', 'moonshot', 'opencode',
                                 'opencode-go', 'freemodel', 'claude',
                                 'ollama'):
            return None

        try:
            saved = self._credential_store.load_provider(provider_name)
            if provider_name != 'ollama' and not saved['api_key']:
                return None
            if provider_name == 'ollama' and not (
                    saved['model'] or saved['endpoint']):
                return None

            return create_provider(
                provider_name,
                api_key=saved['api_key'] or None,
                model=saved['model'] or None,
                endpoint=saved['endpoint'] or None,
            )
        except (CredentialStoreError, TypeError, ValueError):
            logging.exception(
                'Could not load saved Activity-on-Demand provider'
            )
            return None

    def _run_job_inner(self, job):
        if job.cancel_requested:
            self._mark_cancelled(job)
            return

        job.mark_started()
        self._set_progress(
            job,
            STATUS_PLANNING,
            STATUS_PLANNING,
            0.0,
            'Starting generation',
        )

        try:
            with self._lock:
                provider = self._job_providers.get(job.job_id)
            if job.is_resume:
                result = self._run_resume_job(job, provider)
            elif job.parent_revision_id:
                result = self._run_refinement_job(job, provider)
            else:
                result = generate_activity(
                    job.spec,
                    output_root=job.output_root or None,
                    provider=provider,
                    provider_name=job.provider_name,
                    use_rag=job.use_rag,
                    validate_code=job.validate_code,
                    progress_cb=lambda stage, fraction, message, metadata=None:
                        self._pipeline_progress(
                            job,
                            stage,
                            fraction,
                            message,
                            metadata,
                        ),
                    pace=True,
                    package_bundle=False,
                    enhance=job.enhance,
                    cancel_check=lambda: job.cancel_requested,
                )
        except JobCancelled:
            self._mark_cancelled(job)
            return
        except Exception as error:
            if job.cancel_requested:
                # Cancellation during the repair loop can surface as a pipeline
                # error rather than JobCancelled; honour the cancel instead of
                # reporting a spurious failure.
                self._mark_cancelled(job)
                return
            logging.exception('Activity-on-Demand job failed')
            self._mark_failed(job, error)
            return
        except BaseException as error:
            logging.exception(
                'Activity-on-Demand worker received fatal signal')
            self._mark_failed(job, error)
            raise

        if job.cancel_requested:
            self._mark_cancelled(job)
            return

        with self._lock:
            job.finish(result)
            revision = AODRevision.create(
                job.job_id,
                job.user_prompt or job.spec.prompt,
                job.result_summary,
                parent_revision_id=job.parent_revision_id,
            )
            job.result_summary['session_id'] = job.session_id
            job.result_summary['revision_id'] = revision.revision_id
            revision.result_summary = dict(job.result_summary)
            self._store.save(job)
        self._record_finished_revision(job, revision)
        self._notify(job)

    def _pipeline_progress(self, job, stage, fraction, message,
                           metadata=None):
        if job.cancel_requested:
            raise JobCancelled()

        if job.is_terminal():
            return

        status = _status_for_pipeline_stage(stage)
        self._set_progress(job, status, stage, fraction, message, metadata)

    def _run_refinement_job(self, job, provider):
        """Run a refinement using repair-only SEARCH/REPLACE transactions.

        Every refinement edits the parent source with SEARCH/REPLACE blocks.
        A local-template job cannot understand an arbitrary edit request, so
        it fails explicitly instead of silently replacing the parent with a
        newly rendered activity.
        """
        from generation.pipeline import refine_activity
        from generation.pipeline import PipelineError

        session = self._session_store.load(job.session_id)
        if session is None:
            raise PipelineError(
                'Could not find the session for refinement.'
            )

        parent_revision = None
        for rev in session.revisions:
            if rev.revision_id == job.parent_revision_id:
                parent_revision = rev
                break
        if parent_revision is None:
            raise PipelineError(
                'Could not find the parent revision for refinement.'
            )

        summary = parent_revision.result_summary or {}
        project_path = summary.get('project_path', '')
        if not project_path:
            raise PipelineError(
                'Parent revision has no project path.'
            )

        source_path = os.path.join(project_path, 'activity.py')
        try:
            with open(source_path, encoding='utf-8') as f:
                current_source = f.read()
        except OSError:
            raise PipelineError(
                'Could not read the current activity.py for refinement.'
            )

        actual_source_hash = hashlib.sha256(
            current_source.encode('utf-8')).hexdigest()

        if job.provider_name in ('local', 'local-template') and \
                provider is None:
            self._pipeline_progress(
                job,
                'generating',
                0.10,
                'Preserving the parent source; patch repair needs a model',
                {
                    'draft_activity_source': current_source,
                    'initial_activity_source': True,
                },
            )
            raise PipelineError(
                'Refinement needs a configured model that supports patch '
                'repair. The existing activity was preserved and was not '
                'regenerated.'
            )

        plan_path = os.path.join(project_path, 'aod_plan.json')
        try:
            with open(plan_path, encoding='utf-8') as f:
                current_plan = json.load(f)
        except (OSError, ValueError):
            current_plan = {}

        expected_source_hash = current_plan.get(
            'source_hash', summary.get('source_hash', ''))
        if expected_source_hash and actual_source_hash != expected_source_hash:
            raise PipelineError(
                'Parent activity.py changed after its revision was saved. '
                'Refinement stopped to preserve source lineage.'
            )

        return refine_activity(
            job.spec,
            current_source,
            current_plan,
            job.output_root or None,
            provider=provider,
            provider_name=job.provider_name,
            progress_cb=lambda stage, fraction, message, metadata=None:
                self._pipeline_progress(
                    job, stage, fraction, message, metadata),
            pace=True,
            package_bundle=False,
            validate_code=job.validate_code,
            cancel_check=lambda: job.cancel_requested,
        )

    def _run_resume_job(self, job, provider):
        """Continue repairing a preserved failed draft (repair-only)."""
        from generation.pipeline import resume_repair

        return resume_repair(
            job.spec,
            job.draft_activity_source,
            job.repair_diagnostics or None,
            output_root=job.output_root or None,
            provider=provider,
            provider_name=job.provider_name,
            current_plan=job.repair_plan or None,
            validate_code=job.validate_code,
            progress_cb=lambda stage, fraction, message, metadata=None:
                self._pipeline_progress(
                    job, stage, fraction, message, metadata),
            pace=True,
            package_bundle=False,
            cancel_check=lambda: job.cancel_requested,
        )

    def _set_progress(self, job, status, stage, progress, message,
                      metadata=None):
        with self._lock:
            previous_status = job.status
            previous_stage = job.stage
            significant = False
            job.update_progress(status, stage, progress, message)
            if isinstance(metadata, dict):
                draft_source = metadata.get('draft_activity_source')
                if isinstance(draft_source, str) and draft_source:
                    job.draft_activity_source = draft_source
                    if metadata.get('initial_activity_source') and \
                            not job.original_activity_source:
                        job.original_activity_source = draft_source
                        significant = True
                enhanced = metadata.get('enhanced_prompt')
                if isinstance(enhanced, str) and enhanced:
                    job.enhanced_prompt = enhanced
                    significant = True
                repair_event = metadata.get('repair_event')
                if isinstance(repair_event, dict):
                    # Keep diagnostics bounded: repair histories are useful
                    # after a failed job, but must not grow without limit on
                    # a long-running repair session.
                    job.repair_history.append(dict(repair_event))
                    job.repair_history = job.repair_history[-100:]
                    significant = True
                repair_diagnostics = metadata.get('repair_diagnostics')
                if isinstance(repair_diagnostics, dict):
                    job.repair_diagnostics = dict(repair_diagnostics)
                    significant = True
            # Persist on state changes, repair/draft milestones, or about
            # once a second.  Streaming reports every ~80ms (plus paced
            # duplicates) with the full partial source in metadata, and
            # serializing the whole job to disk on each tick is O(n^2)
            # bytes written per generation, real flash wear, and lock
            # contention for every UI poll.  All terminal paths (finish,
            # _mark_failed, _mark_cancelled) still save unconditionally,
            # so at most ~1s of a partial stream is at risk on a hard
            # crash.
            now = time.monotonic()
            if (significant
                    or status != previous_status
                    or stage != previous_stage
                    or now - self._last_progress_save >= 1.0):
                self._store.save(job)
                self._last_progress_save = now
        self._notify(job)

    def _mark_failed(self, job, error):
        with self._lock:
            preserved_source = getattr(error, 'source', '')
            if isinstance(preserved_source, str) and preserved_source:
                job.draft_activity_source = preserved_source
                if not job.original_activity_source:
                    job.original_activity_source = preserved_source
            diagnostics = getattr(error, 'diagnostics', None)
            if isinstance(diagnostics, dict):
                job.repair_diagnostics = dict(diagnostics)
            plan = getattr(error, 'plan', None)
            if isinstance(plan, dict):
                # Preserve the failed plan so "Continue repairing" keeps the
                # same bundle_id and version lineage instead of re-planning.
                job.repair_plan = dict(plan)
            history = getattr(error, 'repair_history', None)
            if isinstance(history, list) and not job.repair_history:
                job.repair_history = [
                    dict(event) for event in history[-100:]
                    if isinstance(event, dict)
                ]
            job.fail(error)
            self._store.save(job)
        self._record_failed_message(job)
        self._notify(job)

    def _mark_cancelled(self, job):
        with self._lock:
            job.cancel()
            self._store.save(job)
        self._notify(job)

    def _notify(self, job):
        with self._lock:
            callbacks = list(self._callbacks.get(job.job_id, ()))

        for callback in callbacks:
            try:
                callback(job)
            except Exception:
                logging.exception('Activity-on-Demand callback failed')

    def _record_finished_revision(self, job, revision):
        if not job.session_id:
            return

        summary = job.result_summary
        provider = summary.get('provider', job.provider_name)
        model = summary.get('model', '')
        if model:
            provider = '%s / %s' % (provider, model)

        message = AODMessage.create(
            ROLE_ASSISTANT,
            ('Generated "%(name)s" with %(provider)s. '
             'This revision is ready to preview, refine, export, or '
             'install.') % {
                 'name': summary.get('activity_name', job.spec.name),
                 'provider': provider,
             },
            message_type=TYPE_RESULT,
            job_id=job.job_id,
            revision_id=revision.revision_id,
        )
        self._session_store.append_revision_and_message(
            job.session_id, revision, message)

    def _record_failed_message(self, job):
        if not job.session_id:
            return

        message = AODMessage.create(
            ROLE_ASSISTANT,
            'Generation failed: %s' % job.error,
            message_type=TYPE_ERROR,
            job_id=job.job_id,
        )
        self._session_store.append_message(job.session_id, message)


def _status_for_pipeline_stage(stage):
    statuses = {
        'planning': STATUS_PLANNING,
        'grounding': STATUS_GROUNDING,
        'provider': STATUS_PROVIDER,
        'generating': STATUS_GENERATING,
        'validating': STATUS_VALIDATING,
        'assembling': STATUS_PACKAGING,
        'packaging': STATUS_PACKAGING,
        'ready': STATUS_PACKAGING,
    }
    return statuses.get(stage, STATUS_GENERATING)


_service = None
_service_lock = threading.Lock()


def get_service():
    global _service
    with _service_lock:
        if _service is None:
            _service = AODService()
        return _service
