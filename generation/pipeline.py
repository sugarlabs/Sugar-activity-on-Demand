# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import hashlib
import inspect
import os
import time
from dataclasses import replace

from sugar3 import env

from generation.codegen import build_codegen_system_prompt
from generation.critic import run_critic_round
from llm.enhance import enhance_prompt
from llm.enhance import needs_enhancement
from generation.codegen import build_codegen_user_prompt
from generation.generator import apply_license_to_project
from generation.generator import build_plan
from generation.generator import create_prototype_activity
from generation.generator import enrich_plan
from generation.generator import normalize_plan
from generation.generator import package_project
from generation.generator import read_project_files
from generation.icons import request_icon_svg
from llm.providers import ProviderError
from llm.providers import get_configured_provider
from generation.prompts import build_system_prompt
from generation.prompts import build_user_prompt
from generation.rag import build_corpus
from generation.rag import search
from generation.refine import build_refine_system_prompt
from generation.refine import build_refine_user_prompt
from generation.refine import parse_search_replace
from generation.refine import apply_patches
from generation.repair_loop import RepairCheckResult
from generation.repair_loop import patches_match_uniquely
from generation.repair_loop import patches_replace_whole_file
from generation.repair_loop import repair_candidate
from generation.repair_loop import response_contains_only_patches
from generation.runtime_check import run_runtime_check
from generation.validator import validate_activity_source_for_request


class PipelineError(Exception):
    """Pipeline failure with optional preserved repair state."""

    def __init__(self, message, source='', repair_history=None,
                 diagnostics=None):
        Exception.__init__(self, message)
        self.source = source if isinstance(source, str) else ''
        self.repair_history = list(repair_history or ())
        self.diagnostics = diagnostics


_LOCAL_PROVIDER_NAMES = ('local', 'local-template')


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


_CODE_REPAIR_ATTEMPT_LIMIT = max(
    1, min(_env_int('AOD_CODE_REPAIR_ATTEMPT_LIMIT', 8), 50))


def generate_activity(spec, output_root=None, provider=None,
                      provider_name='default', use_rag=True,
                      validate_code=True,
                      progress_cb=None, pace=False, package_bundle=True,
                      template_fallback=False, enhance=True,
                      cancel_check=None):
    """Run prompt grounding, provider planning, and generation.

    ``template_fallback`` applies only when no provider candidate was produced
    at all.  Once activity.py exists, every failure repairs that exact source;
    an invalid candidate is never discarded for a template or a second full
    generation.
    """
    progress = _PipelineProgress(progress_cb, pace)

    selected_provider = provider
    provider_error = ''
    references = []
    provider_required = (
        selected_provider is not None or
        provider_name not in _LOCAL_PROVIDER_NAMES
    )

    if selected_provider is None and provider_name not in (
            'local', 'local-template'):
        try:
            selected_provider = get_configured_provider(provider_name)
        except ProviderError as error:
            provider_error = str(error)

    if provider_required and selected_provider is None:
        if provider_error:
            raise PipelineError(
                'Configured model is required for RAG generation: %s'
                % provider_error
            )
        raise PipelineError(
            'No configured model is available. Save an API key and choose '
            'a provider before generating.'
        )

    # Provider resolution must happen before enhancement.  Direct callers
    # commonly pass provider_name instead of a provider object; the old order
    # silently skipped enhancement for those otherwise-identical requests.
    original_prompt = spec.prompt
    prompt_was_enhanced = False
    if selected_provider is not None and enhance and \
            needs_enhancement(spec.prompt):
        progress.report('enhancing', 0.03,
                        'Making your idea crystal clear...')
        enhanced_text, prompt_was_enhanced = enhance_prompt(
            selected_provider, spec.prompt, spec)
        if prompt_was_enhanced:
            spec = replace(spec, prompt=enhanced_text)
            progress.report(
                'enhancing', 0.05,
                'Refined your idea into a clear brief',
                metadata={'enhanced_prompt': enhanced_text})

    progress.report('planning', 0.06,
                    'Reading the prompt and classroom goal')

    if selected_provider is not None:
        use_rag = True

    if selected_provider is not None:
        progress.report('planning', 0.16,
                        'Preparing Sugar example context for the model')
    else:
        progress.report('planning', 0.16,
                        'Drafting local activity structure')
        local_plan = build_plan(spec)

    if use_rag:
        if selected_provider is not None:
            progress.report('grounding', 0.24,
                            'Retrieving Sugar activity examples for context')
            template_filter = ''
            reference_limit = 10
        else:
            progress.report('grounding', 0.24,
                            'Searching Sugar activity patterns')
            template_filter = local_plan['template']
            reference_limit = 4
        corpus = build_corpus()
        references = search(
            spec.prompt,
            limit=reference_limit,
            template=template_filter,
            corpus=corpus,
        )
        progress.report('grounding', 0.34,
                        'Selecting useful Sugar API and interaction patterns')

    if selected_provider is not None:
        system_prompt = build_system_prompt(spec, references)
        user_prompt = build_user_prompt(spec)
        progress.report('provider', 0.43,
                        'Asking the configured model to plan from RAG context')
        plan_error = None
        for plan_attempt in (1, 2):
            try:
                provider_plan = selected_provider.generate_plan(
                    system_prompt,
                    user_prompt,
                )
                plan = normalize_plan(spec, provider_plan)
                provider_used = selected_provider.name
                model_used = selected_provider.model
                plan_error = None
                progress.report('provider', 0.52,
                                'Checking the model plan')
                break
            except ValueError as error:
                # A malformed plan response is usually a one-off; one
                # fresh attempt is cheap compared to failing the job.
                plan_error = error
                if plan_attempt == 1:
                    progress.report(
                        'provider', 0.45,
                        'Model plan was malformed; asking once more')
            except ProviderError as error:
                # Transient network failures were already retried at the
                # HTTP layer, so what reaches here is not worth repeating.
                plan_error = error
                break
        if plan_error is not None:
            provider_error = _redact_provider_error(
                plan_error,
                selected_provider,
            )
            if not template_fallback:
                raise PipelineError(
                    'Provider did not answer: %s' % provider_error
                )
            # Provider unavailable but caller asked for graceful degradation:
            # build the activity from the local template so the user still
            # gets something usable without burning further API credits.
            progress.report(
                'provider', 0.46,
                'Provider did not answer; using local template instead',
            )
            plan = build_plan(spec)
            provider_used = 'local'
            model_used = ''
            selected_provider = None
    else:
        plan = local_plan
        provider_used = 'local'
        model_used = ''
        progress.report('provider', 0.43,
                        'Using the local activity builder')

    if output_root is None:
        output_root = env.get_profile_path(os.path.join('aod', 'projects'))

    plan = enrich_plan(spec, plan, references)
    plan = dict(plan)
    plan['provider'] = provider_used
    plan['model'] = model_used
    if prompt_was_enhanced:
        plan['original_prompt'] = original_prompt
        plan['enhanced_prompt'] = spec.prompt
    if provider_error:
        plan['provider_fallback_reason'] = provider_error

    activity_source = None
    plan['code_source'] = 'template'
    if selected_provider is not None and provider_used != 'local':
        generated = _generate_activity_source_with_provider(
            selected_provider,
            spec,
            plan,
            references,
            progress,
            validate_code=validate_code,
            cancel_check=cancel_check,
        )
        activity_source, code_error, code_attempts, repair_history, \
            failed_source = generated
        plan['codegen_attempts'] = code_attempts
        plan['repair_history'] = repair_history
        plan['repair_attempts'] = len([
            event for event in repair_history
            if event.get('attempt', 0) > 0
        ])
        if activity_source:
            plan['code_source'] = 'provider'
            plan['source_hash'] = _source_hash(activity_source)
            plan['original_source_hash'] = (
                repair_history[0].get('active_source_hash_before')
                if repair_history else plan['source_hash']
            )
            if plan['repair_attempts']:
                plan['repair_status'] = 'repaired'
            else:
                plan['repair_status'] = 'clean'
            plan['codegen_provider'] = selected_provider.name
            plan['codegen_model'] = selected_provider.model
            if validate_code:
                progress.report(
                    'generating', 0.68,
                    'Reviewing the code for weak spots...')
                # Static validation is cheap; re-run it to hand the
                # critic the accepted source's warnings as context.
                accepted_report = validate_activity_source_for_request(
                    activity_source, spec, plan)
                critic_source = activity_source
                activity_source = run_critic_round(
                    selected_provider,
                    spec,
                    plan,
                    activity_source,
                    warnings=accepted_report.warnings,
                )
                if activity_source != critic_source:
                    critic_event = {
                        'attempt': 0,
                        'outcome': 'critic_patch_passed',
                        'active_source_hash_before': _source_hash(
                            critic_source),
                        'proposed_source_hash': _source_hash(activity_source),
                        'active_source_hash_after': _source_hash(
                            activity_source),
                        'patch_count': int(
                            str(plan.get('critic', 'patched:0')).split(':')[-1]
                        ),
                        'rolled_back': False,
                    }
                    repair_history.append(critic_event)
                    progress.report_immediate(
                        'generating', 0.69,
                        'Critic repair passed every check', {
                            'draft_activity_source': activity_source,
                            'repair_event': critic_event,
                        })
                plan['source_hash'] = _source_hash(activity_source)
        elif code_error:
            # A returned candidate is never discarded.  Local template
            # fallback remains available only when the provider failed before
            # producing any source at all; invalid source must stay in the
            # repair path and is persisted through progress metadata.
            if template_fallback and not failed_source:
                plan['codegen_fallback_reason'] = code_error
                plan['code_source'] = 'template_after_codegen_failure'
                progress.report(
                    'generating', 0.58,
                    'Provider code failed validation; using local '
                    'template instead',
                )
            else:
                raise PipelineError(
                    'Provider could not repair activity code: %s'
                    % code_error,
                    source=failed_source,
                    repair_history=repair_history,
                )
        elif template_fallback:
            # Provider only supports planning, not code generation, and the
            # caller allowed graceful degradation.  Fall back to the local
            # template renderer.
            plan['codegen_fallback_reason'] = (
                'Provider does not support activity source generation; '
                'using template renderer.'
            )
        else:
            # Symmetry with the code_error branch: a provider that cannot
            # produce any source fails loudly rather than silently shipping a
            # template the caller did not ask for.
            raise PipelineError(
                'Configured provider does not support activity source '
                'generation and template fallback is disabled.'
            )

    if selected_provider is not None and provider_used != 'local' \
            and not plan.get('icon_svg'):
        progress.report('generating', 0.72,
                        'Drawing an icon for your activity...')
        icon_svg = request_icon_svg(selected_provider, spec, plan)
        if icon_svg:
            plan['icon_svg'] = icon_svg
            plan['icon_source'] = 'ai'
        else:
            plan['icon_source'] = 'generated'

    progress.report('generating', 0.74,
                    'Expanding the plan into activity screens')
    result = create_prototype_activity(
        spec,
        output_root,
        plan=plan,
        package_bundle=False,
        activity_source=activity_source,
    )
    result.provider = provider_used
    result.model = model_used

    progress.report('assembling', 0.78,
                    'Assembling the activity project')
    plan_path = os.path.join(result.project_path, 'aod_plan.json')
    with open(plan_path, 'w', encoding='utf-8') as plan_file:
        json.dump(result.plan, plan_file, indent=2, sort_keys=True)
        plan_file.write('\n')

    if package_bundle:
        progress.report('packaging', 0.88,
                        'Packaging the XO bundle')
        package_generation_result(result)

    progress.report('ready', 1.0, 'Activity project is ready')
    return result


def package_generation_result(result):
    """Build the XO bundle for an already generated project."""
    if result.bundle_path and os.path.isfile(result.bundle_path):
        return result.bundle_path

    result.bundle_path = package_project(result.project_path)
    plan_path = os.path.join(result.project_path, 'aod_plan.json')
    with open(plan_path, 'w', encoding='utf-8') as plan_file:
        json.dump(result.plan, plan_file, indent=2, sort_keys=True)
        plan_file.write('\n')
    result.files = read_project_files(result.project_path)
    return result.bundle_path


def reapply_generation_license(result, license_id):
    """Switch a generated activity to ``license_id`` before packaging.

    Rewrites the license artifacts on disk, refreshes the in-memory file
    mapping, and invalidates any previously built bundle so the next
    :func:`package_generation_result` call repackages with the new license.
    """
    if result.spec.license_id == license_id and result.bundle_path:
        return result

    result.spec.license_id = license_id
    result.files = apply_license_to_project(
        result.project_path, result.spec, result.plan)
    source = result.files.get('activity.py', '')
    if source:
        result.plan['source_hash'] = _source_hash(source)
    plan_path = os.path.join(result.project_path, 'aod_plan.json')
    with open(plan_path, 'w', encoding='utf-8') as plan_file:
        json.dump(result.plan, plan_file, indent=2, sort_keys=True)
        plan_file.write('\n')
    result.files = read_project_files(result.project_path)
    result.bundle_path = ''
    return result


def _progress(callback, stage, fraction, message, metadata=None):
    if callback is not None:
        try:
            if metadata is None:
                callback(stage, fraction, message)
            else:
                callback(stage, fraction, message, metadata)
        except TypeError:
            callback(stage, fraction, message)


class _PipelineProgress:
    """Progress reporter with optional UI pacing for real service jobs."""

    def __init__(self, callback, pace=False):
        self._callback = callback
        self._pace = pace
        self._fraction = 0.0

    def report(self, stage, fraction, message, metadata=None):
        fraction = max(self._fraction, float(fraction))
        self._fraction = fraction
        _progress(self._callback, stage, fraction, message, metadata)
        if not self._pace:
            return

        end_time = time.time() + 0.15
        while time.time() < end_time:
            time.sleep(0.05)
            _progress(self._callback, stage, fraction, message)

    def report_immediate(self, stage, fraction, message, metadata=None):
        """Report progress without the pacing sleep.

        Used for streaming token updates where blocking the response
        thread would slow down how fast new tokens arrive.
        """
        fraction = max(self._fraction, float(fraction))
        self._fraction = fraction
        _progress(self._callback, stage, fraction, message, metadata)


def _redact_provider_error(error, provider):
    message = str(error)
    for secret in _provider_secrets(provider):
        message = message.replace(secret, '[redacted]')
    return message


def _redact_source_credentials(source, provider):
    """Remove a provider credential before source reaches logs or disk."""
    if not isinstance(source, str):
        return source, False
    redacted = source
    for secret in _provider_secrets(provider):
        redacted = redacted.replace(secret, '[redacted]')
    return redacted, redacted != source


def _provider_secrets(provider):
    secrets = []
    for name in ('_api_key', 'api_key'):
        value = getattr(provider, name, '')
        if isinstance(value, str) and value:
            secrets.append(value)
    return secrets


_STREAM_REPORT_INTERVAL_SECONDS = 0.08


def _make_codegen_stream_callback(progress, attempt, provider=None):
    """Build a stream callback that forwards partial codegen text to the UI.

    The callback is debounced so the UI is not repainted on every single
    token; intermediate updates land at most once per ~80ms. The first
    and final chunks are always reported so the preview lights up
    immediately and reflects the final draft.
    """
    state = {'last_emit': 0.0, 'last_text': ''}

    def report_partial(partial_text):
        if not isinstance(partial_text, str):
            return
        safe_partial, _redacted = _redact_source_credentials(
            partial_text, provider)
        state['last_text'] = safe_partial
        report_partial.last_text = safe_partial
        now = time.time()
        if now - state['last_emit'] < _STREAM_REPORT_INTERVAL_SECONDS:
            return
        state['last_emit'] = now
        progress.report_immediate(
            'generating',
            0.58,
            'Streaming activity.py from the model '
            '(%d chars)' % len(partial_text),
            {
                'draft_activity_source': safe_partial,
                'codegen_attempt': attempt,
                'codegen_streaming': True,
            },
        )

    report_partial.last_text = ''
    return report_partial


_CODE_SIZE_TOKENS = {
    'compact': 6000,
    'standard': 14000,
    'full': None,
}


def _generate_activity_source_with_provider(
        provider, spec, plan, references, progress, validate_code=True,
        cancel_check=None):
    generate_source = getattr(provider, 'generate_activity_source', None)
    if not callable(generate_source):
        return None, '', 0, [], ''

    code_size = getattr(spec, 'code_size', 'standard')
    max_output_tokens = _CODE_SIZE_TOKENS.get(code_size)

    system_prompt = build_codegen_system_prompt(
        spec, plan, references, code_size=code_size)
    user_prompt = build_codegen_user_prompt(spec, plan)
    progress.report('generating', 0.56,
                    'Asking the model to write activity.py once')
    stream_callback = _make_codegen_stream_callback(progress, 1, provider)
    generation_error = ''
    try:
        source = _request_initial_activity_source(
            generate_source,
            system_prompt,
            user_prompt,
            stream_callback,
            max_output_tokens,
        )
    except ProviderError as error:
        generation_error = _redact_provider_error(error, provider)
        source = getattr(stream_callback, 'last_text', '')
        if not source:
            return None, generation_error, 1, [], ''
    except ValueError as error:
        generation_error = _redact_provider_error(error, provider)
        source = getattr(stream_callback, 'last_text', '')
        if not source:
            return None, generation_error, 1, [], ''
    except Exception as error:
        if type(error).__name__ == 'JobCancelled':
            raise
        generation_error = _redact_provider_error(error, provider)
        source = getattr(stream_callback, 'last_text', '')
        if not source:
            return None, generation_error, 1, [], ''

    if not isinstance(source, str) or not source.strip():
        streamed_source = getattr(stream_callback, 'last_text', '')
        if isinstance(streamed_source, str) and streamed_source.strip():
            source = streamed_source
            generation_error = generation_error or (
                'Provider returned an empty final result after streaming '
                'activity.py.')
        else:
            return None, 'Model returned an empty activity.py.', 1, [], ''

    source, credential_redacted = _redact_source_credentials(
        source, provider)

    progress.report(
        'generating', 0.64,
        ('Preserving the streamed activity.py for repair'
         if generation_error else 'Model returned the initial activity.py'), {
            'draft_activity_source': source,
            'initial_activity_source': True,
            'codegen_attempt': 1,
        })

    if not validate_code:
        return source, '', 1, [], ''

    passed, diagnostics = _check_activity_candidate(source, spec, plan)
    if generation_error:
        diagnostics.setdefault('warnings', []).append(
            'The provider call ended with an error after returning source: '
            + generation_error)
    if credential_redacted:
        diagnostics.setdefault('warnings', []).append(
            'Credential material in the provider response was redacted '
            'before the candidate was persisted.')
    if passed:
        plan['runtime_check'] = diagnostics.get('runtime_detail', 'passed')
        plan['verification_status'] = diagnostics.get('stage', 'passed')
        return source, '', 1, [], ''

    initial_event = {
        'attempt': 0,
        'outcome': 'initial_candidate_rejected',
        'active_source_hash_before': _source_hash(source),
        'proposed_source_hash': _source_hash(source),
        'active_source_hash_after': _source_hash(source),
        'diagnostics': diagnostics,
        'rolled_back': False,
    }
    progress.report(
        'generating', 0.65,
        'Initial code failed its checks; repairing the same file', {
            'repair_event': initial_event,
            'repair_diagnostics': diagnostics,
            'draft_activity_source': source,
        })

    repair = _repair_existing_source(
        provider, spec, plan, source, diagnostics, progress,
        cancel_check=cancel_check)
    history = [initial_event] + [
        _persistable_repair_event(event, provider)
        for event in repair.history
    ]
    if repair.success:
        final_diagnostics = repair.diagnostics
        if isinstance(final_diagnostics, dict):
            plan['runtime_check'] = final_diagnostics.get(
                'runtime_detail', 'passed')
            plan['verification_status'] = final_diagnostics.get(
                'stage', 'passed')
        return repair.source, '', 1, history, ''

    error = '%s: %s' % (
        repair.reason,
        _diagnostics_text(
            _redact_repair_value(repair.diagnostics, provider)),
    )
    return None, error, 1, history, repair.source


def _request_initial_activity_source(generate_source, system_prompt,
                                     user_prompt, stream_callback,
                                     max_output_tokens):
    """Call a provider once without masking provider-internal TypeErrors."""
    kwargs = {}
    try:
        signature = inspect.signature(generate_source)
    except (TypeError, ValueError):
        signature = None

    if signature is not None:
        parameters = signature.parameters
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        stream_parameter = parameters.get('stream_callback')
        if accepts_kwargs or (
                stream_parameter is not None and
                stream_parameter.kind != inspect.Parameter.POSITIONAL_ONLY):
            kwargs['stream_callback'] = stream_callback
        token_parameter = parameters.get('max_output_tokens')
        if accepts_kwargs or (
                token_parameter is not None and
                token_parameter.kind != inspect.Parameter.POSITIONAL_ONLY):
            kwargs['max_output_tokens'] = max_output_tokens
    return generate_source(system_prompt, user_prompt, **kwargs)


def _check_activity_candidate(source, spec, plan):
    """Return a structured, stage-aware acceptance result for one source."""
    try:
        report = validate_activity_source_for_request(source, spec, plan)
    except (TypeError, ValueError) as error:
        return False, {
            'stage': 'static_validation',
            'errors': ['Validator could not inspect the source: %s' % error],
            'warnings': [],
        }

    if not report.valid:
        return False, {
            'stage': 'static_validation',
            'errors': list(report.errors),
            'warnings': list(report.warnings),
        }

    runtime_ok, runtime_detail = run_runtime_check(
        source, getattr(spec, 'name', 'Generated Activity'))
    if not runtime_ok:
        return False, {
            'stage': 'runtime_check',
            'errors': [runtime_detail],
            'warnings': list(report.warnings),
            'runtime_detail': runtime_detail,
        }
    if runtime_detail.startswith('skipped:'):
        return True, {
            'stage': 'runtime_unverified',
            'errors': [],
            'warnings': [
                'Runtime verification was unavailable; static validation '
                'passed but execution remains unverified.'
            ] + list(report.warnings),
            'runtime_detail': runtime_detail,
        }
    return True, {
        'stage': 'passed',
        'errors': [],
        'warnings': list(report.warnings),
        'runtime_detail': runtime_detail,
    }


def _repair_existing_source(provider, spec, plan, source, diagnostics,
                            progress, validate_code=True, goal='',
                            cancel_check=None):
    """Patch one existing source transactionally; never generate a new one.

    ``goal`` is forwarded to the repair prompt so a rejected refinement can be
    re-applied instead of only its diagnostics being fixed.  ``cancel_check``
    lets a caller stop the loop promptly on cancellation.
    """
    diagnostics = _redact_repair_value(diagnostics, provider)
    best = {
        'score': _diagnostic_score(diagnostics),
    }

    def verify_candidate(candidate):
        if validate_code:
            passed, candidate_diagnostics = _check_activity_candidate(
                candidate, spec, plan)
        else:
            passed = True
            candidate_diagnostics = {
                'stage': 'passed',
                'errors': [],
                'warnings': ['Validation disabled by caller.'],
                'runtime_detail': 'skipped: validation disabled',
            }
        candidate_diagnostics = _redact_repair_value(
            candidate_diagnostics, provider)
        score = _diagnostic_score(candidate_diagnostics)
        improved = score > best['score']
        # Runtime failures have no reliable ordering without explicit harness
        # phases.  A different traceback is not necessarily progress (it can
        # be a worse startup crash or timeout), so only a higher gate score or
        # a fully passing candidate is committed.
        accept_candidate = bool(passed or improved)
        if accept_candidate:
            best['score'] = score
            progress.report_immediate(
                'generating', 0.66,
                'Committed an improved repair candidate', {
                    'draft_activity_source': candidate,
                    'repair_diagnostics': candidate_diagnostics,
                })
        return RepairCheckResult(
            passed=passed,
            diagnostics=candidate_diagnostics,
            accept_candidate=accept_candidate,
        )

    def repair_event(event):
        safe_event = _redact_repair_value(event, provider)
        progress.report_immediate(
            'generating', 0.66,
            _repair_event_message(safe_event),
            {'repair_event': safe_event},
        )

    return repair_candidate(
        provider,
        source,
        diagnostics,
        verify_candidate,
        max_attempts=_CODE_REPAIR_ATTEMPT_LIMIT,
        event_callback=repair_event,
        goal=goal,
        cancel_check=cancel_check,
    )


def _diagnostic_score(diagnostics):
    if not isinstance(diagnostics, dict):
        return 0
    stage = diagnostics.get('stage')
    if stage == 'passed':
        return 3000
    if stage == 'runtime_check':
        return 2000
    if stage == 'runtime_unverified':
        return 2500
    errors = diagnostics.get('errors') or ()
    return 1000 - len(errors)


def _source_hash(source):
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def _diagnostics_text(diagnostics):
    if isinstance(diagnostics, str):
        return diagnostics
    try:
        return json.dumps(diagnostics, sort_keys=True)
    except (TypeError, ValueError):
        return str(diagnostics)


def _redact_repair_value(value, provider):
    if isinstance(value, str):
        for secret in _provider_secrets(provider):
            value = value.replace(secret, '[redacted]')
        return value
    if isinstance(value, dict):
        return {
            str(key): _redact_repair_value(item, provider)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_repair_value(item, provider) for item in value]
    return value


def _persistable_repair_event(event, provider):
    """Strip source fragments while retaining a verifiable repair audit."""
    safe = _redact_repair_value(dict(event), provider)
    patches = safe.pop('patches', [])
    safe['patch_count'] = len(patches) if isinstance(patches, list) else 0
    if isinstance(patches, list):
        safe['patch_hashes'] = [
            hashlib.sha256(json.dumps(
                patch, sort_keys=True).encode('utf-8')).hexdigest()
            for patch in patches if isinstance(patch, dict)
        ]
    return safe


def _repair_event_message(event):
    outcome = event.get('outcome', 'repair_attempt')
    attempt = event.get('attempt', 0)
    if outcome == 'passed':
        return 'Repair attempt %d passed every check' % attempt
    if outcome == 'intermediate_committed':
        return 'Repair attempt %d made progress; checking again' % attempt
    return 'Repair attempt %d was rejected (%s)' % (attempt, outcome)


def refine_activity(spec, current_source, current_plan, output_root,
                    provider=None, provider_name='default',
                    validate_code=True,
                    progress_cb=None, pace=False,
                    package_bundle=False, cancel_check=None):
    """Refine one existing activity.py without ever regenerating the file.

    The requested edit and any follow-up fixes are exact SEARCH/REPLACE
    transactions.  Invalid, ambiguous, unsafe, or crashing patches are
    rolled back and repaired against the same source lineage.
    """
    progress = _PipelineProgress(progress_cb, pace)
    selected_provider = provider
    if selected_provider is None and provider_name not in (
            'local', 'local-template'):
        try:
            selected_provider = get_configured_provider(provider_name)
        except ProviderError as error:
            raise PipelineError(
                'Configured model is required for refinement: %s' % error
            )

    if selected_provider is None:
        raise PipelineError(
            'A configured model is required for refinement.'
        )

    if output_root is None:
        output_root = env.get_profile_path(os.path.join('aod', 'projects'))

    refinement_request = spec.prompt
    plan_context = json.dumps({
        'template': current_plan.get('template', ''),
        'activity_kind': current_plan.get('activity_kind', ''),
        'interaction_model': current_plan.get('interaction_model', ''),
    }, indent=2)

    progress.report('generating', 0.30,
                    'Asking the model for targeted edits', {
                        'draft_activity_source': current_source,
                        'initial_activity_source': True,
                    })

    generate_text = getattr(selected_provider, 'generate_text', None)
    patched_source = None
    patch_accepted = False
    diagnostics = None
    repair_history = []
    refine_method = 'search_replace'
    if callable(generate_text):
        try:
            response = generate_text(
                build_refine_system_prompt(),
                build_refine_user_prompt(
                    current_source,
                    refinement_request,
                    plan_context=plan_context,
                ),
            )
        except Exception as error:
            response = None
            diagnostics = {
                'stage': 'refinement_request',
                'errors': [_redact_provider_error(error, selected_provider)],
                'warnings': [],
                'refinement_request': refinement_request,
            }
    else:
        response = None
        diagnostics = {
            'stage': 'refinement_request',
            'errors': [
                'Provider does not support raw SEARCH/REPLACE repair.'
            ],
            'warnings': [],
            'refinement_request': refinement_request,
        }

    if response is not None:
        response, leaked_credential = _redact_source_credentials(
            response, selected_provider)
        if leaked_credential:
            response = None
            diagnostics = {
                'stage': 'refinement_patch',
                'errors': [
                    'Provider response contained credential material and '
                    'was refused.'
                ],
                'warnings': [],
                'refinement_request': refinement_request,
            }

    if response is not None:
        if not response_contains_only_patches(response):
            patches = None
            diagnostics = {
                'stage': 'refinement_patch',
                'errors': [
                    'Refinement response must contain only exact '
                    'SEARCH/REPLACE blocks.'
                ],
                'warnings': [],
                'refinement_request': refinement_request,
            }
        else:
            try:
                patches = parse_search_replace(response)
            except ValueError as error:
                patches = None
                diagnostics = {
                    'stage': 'refinement_patch',
                    'errors': [str(error)],
                    'warnings': [],
                    'refinement_request': refinement_request,
                }

        if patches is None:
            diagnostics = diagnostics or {
                'stage': 'refinement_patch',
                'errors': [
                    'FULLREGEN was refused; the existing file must be '
                    'changed with focused patches.'
                ],
                'warnings': [],
                'refinement_request': refinement_request,
            }
            progress.report(
                'generating', 0.40,
                'Whole-file replacement refused; requesting a repair patch')
        elif patches_replace_whole_file(current_source, patches):
            diagnostics = {
                'stage': 'refinement_patch',
                'errors': [
                    'The edit attempted to replace most or all of '
                    'activity.py. Whole-file regeneration is forbidden.'
                ],
                'warnings': [],
                'refinement_request': refinement_request,
            }
            progress.report(
                'generating', 0.42,
                'Whole-file edit refused; requesting focused patches')
        elif not patches_match_uniquely(current_source, patches):
            diagnostics = {
                'stage': 'refinement_patch',
                'errors': [
                    'Every SEARCH block must match exactly one location in '
                    'the current source.'
                ],
                'warnings': [],
                'refinement_request': refinement_request,
            }
            progress.report(
                'generating', 0.42,
                'Edit anchors were ambiguous; requesting corrected patches')
        else:
            progress.report(
                'generating', 0.55,
                'Applying %d targeted edits' % len(patches),
            )
            patched, applied, failed = apply_patches(
                current_source, patches)
            if failed > 0 or applied == 0:
                diagnostics = {
                    'stage': 'refinement_patch',
                    'errors': [
                        '%d edits matched and %d failed; the transaction was '
                        'rolled back.' % (applied, failed)
                    ],
                    'warnings': [],
                    'refinement_request': refinement_request,
                }
                progress.report(
                    'generating', 0.58,
                    '%d edits matched, %d failed; rolling back and repairing'
                    % (applied, failed),
                )
            else:
                patched_source = patched
                if validate_code:
                    passed, diagnostics = _check_activity_candidate(
                        patched_source, spec, current_plan)
                else:
                    passed = True
                    diagnostics = {
                        'stage': 'passed',
                        'errors': [],
                        'warnings': ['Validation disabled by caller.'],
                        'runtime_detail': 'skipped: validation disabled',
                    }
                if passed:
                    patch_accepted = True
                    repair_history.append({
                        'attempt': 0,
                        'outcome': 'refinement_patch_passed',
                        'active_source_hash_before': _source_hash(
                            current_source),
                        'proposed_source_hash': _source_hash(patched_source),
                        'active_source_hash_after': _source_hash(
                            patched_source),
                        'patch_count': len(patches),
                        'diagnostics': diagnostics,
                        'rolled_back': False,
                    })
                    progress.report(
                        'generating', 0.70,
                        'Targeted edits passed every check', {
                            'draft_activity_source': patched_source,
                            'repair_event': repair_history[-1],
                            'repair_diagnostics': diagnostics,
                        })
                else:
                    progress.report(
                        'generating', 0.60,
                        'Targeted edits need repair; keeping the same file', {
                            'draft_activity_source': patched_source,
                            'repair_diagnostics': diagnostics,
                        })

    if not patch_accepted:
        # A cleanly-applied but gate-failing edit already carries the
        # requested change, so repair continues from that candidate instead of
        # discarding it.  Only when no patch could be applied at all do we fall
        # back to the parent, and even then the repair loop is told the
        # requested change (goal) so it can re-derive it rather than silently
        # fixing unrelated diagnostics.  A failed repair still raises, so a
        # gate-failing candidate never becomes a saved revision.
        repair_base = (
            patched_source if patched_source is not None else current_source)
        rejection = {
            'attempt': 0,
            'outcome': 'refinement_patch_rejected',
            'active_source_hash_before': _source_hash(current_source),
            'proposed_source_hash': (
                _source_hash(patched_source) if patched_source else None),
            'active_source_hash_after': _source_hash(repair_base),
            'diagnostics': diagnostics or {
                'stage': 'refinement_patch',
                'errors': ['No usable patch response was returned.'],
                'warnings': [],
                'refinement_request': refinement_request,
            },
            'rolled_back': repair_base == current_source,
        }
        repair_history.append(rejection)
        progress.report(
            'generating', 0.62,
            'Debugging the refinement without regenerating activity.py', {
                'repair_event': rejection,
                'repair_diagnostics': rejection['diagnostics'],
                'draft_activity_source': repair_base,
            })
        repair = _repair_existing_source(
            selected_provider,
            spec,
            current_plan,
            repair_base,
            rejection['diagnostics'],
            progress,
            validate_code=validate_code,
            goal=refinement_request,
            cancel_check=cancel_check,
        )
        repair_history.extend(
            _persistable_repair_event(event, selected_provider)
            for event in repair.history
        )
        if not repair.success:
            raise PipelineError(
                'Refinement repair stopped without regenerating the file: '
                '%s: %s' % (
                    repair.reason,
                    _diagnostics_text(_redact_repair_value(
                        repair.diagnostics, selected_provider)),
                ),
                source=repair.source,
                repair_history=repair_history,
                diagnostics=_redact_repair_value(
                    repair.diagnostics, selected_provider),
            )
        if repair.source == current_source:
            raise PipelineError(
                'Refinement repair only reverted to the parent source; the '
                'requested change remains unresolved. The parent was '
                'preserved and was not regenerated.'
            )
        patched_source = repair.source
        diagnostics = repair.diagnostics
        refine_method = 'repair_loop'

    plan = dict(current_plan)
    plan['code_source'] = 'provider'
    plan['refine_method'] = refine_method
    plan['parent_source_hash'] = _source_hash(current_source)
    plan['original_source_hash'] = current_plan.get(
        'original_source_hash', plan['parent_source_hash'])
    plan['source_hash'] = _source_hash(patched_source)
    plan['repair_history'] = (
        list(current_plan.get('repair_history') or []) + repair_history
    )[-100:]
    plan['repair_attempts'] = len([
        event for event in repair_history if event.get('attempt', 0) > 0
    ])
    plan['repair_status'] = 'repaired' if plan['repair_attempts'] else 'clean'
    if isinstance(diagnostics, dict):
        plan['runtime_check'] = diagnostics.get(
            'runtime_detail', plan.get('runtime_check', ''))
        plan['verification_status'] = diagnostics.get(
            'stage', plan.get('verification_status', ''))
    plan['codegen_provider'] = selected_provider.name
    plan['codegen_model'] = selected_provider.model

    progress.report('generating', 0.80,
                    'Assembling the refined project')
    result = create_prototype_activity(
        spec,
        output_root,
        plan=plan,
        package_bundle=False,
        activity_source=patched_source,
    )
    result.provider = selected_provider.name
    result.model = selected_provider.model

    plan_path = os.path.join(result.project_path, 'aod_plan.json')
    with open(plan_path, 'w', encoding='utf-8') as plan_file:
        json.dump(result.plan, plan_file, indent=2, sort_keys=True)
        plan_file.write('\n')

    if package_bundle:
        progress.report('packaging', 0.95, 'Packaging the XO bundle')
        package_generation_result(result)

    progress.report('ready', 1.0, 'Refined activity is ready')
    return result
