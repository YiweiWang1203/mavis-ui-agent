"""Injected two-slot diagnostic runner. Does not construct a client or launch runs."""
import copy
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch

from src.utils.bounded_plan_correction import (
    MODEL, ENVIRONMENT, require, correction_request, correction_invariants)
from src.utils.pipeline_trace import PipelineTrace
from scripts.region_tree_paired_runner import write, export_coder_html


def correction_transport(directory, run_id, *, dispatch=None):
    from src.utils.single_attempt_transport import SingleAttemptTransport, isolated_sdk_call
    class Once(SingleAttemptTransport):
        def __init__(self):
            super().__init__(directory, run_id, dispatch=dispatch or isolated_sdk_call)
            write(self.directory/'two_slot_policy.json', dict(
                max_slots=2, overrides_generic_transport_four_slot_capacity=True,
                allowed_arm='candidate', sequence=['architect_once_correction', 'coder_if_all_gates_pass'],
                retries=0, resume=False, failures_consume_slot=True))
            self.next_node = 'architect'
            self.gate_passed = False
            self.attempt_count = 0

        def permit_coder(self, gate):
            require(self.next_node == 'WAITING_GATE' and self.attempt_count == 1 and
                    gate.get('status') == 'ALL_PRE_CODER_GATES_PASS_NOT_SEMANTIC_ACCEPTANCE',
                    'CODER_GATE_NOT_PASSED')
            self.gate_passed = True
            self.next_node = 'coder'

        def _call(self, arm, node, request):
            require(arm == 'candidate' and node == self.next_node and self.attempt_count < 2,
                    'ONCE_ONLY_SLOT_OR_ARM_VIOLATION')
            require(node != 'coder' or self.gate_passed, 'CODER_BEFORE_GATES')
            self.next_node = None  # even a dispatch failure consumes the only attempt
            self.attempt_count += 1
            result = super()._call(arm, node, request)
            if node == 'architect':
                self.next_node = 'WAITING_GATE'
            return result
    return Once()


def run_correction(original_request, original_answer, vision, intent, out, transport, *, export_html=False):
    from src.agents import ui_architect, coder
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    request, diagnostics = correction_request(original_request, original_answer, vision, intent)
    write(out/'original_messages.json', original_request['messages'])
    with (out/'original_answer.txt').open('x', encoding='utf-8', newline='') as stream:
        stream.write(original_answer)
    write(out/'machine_feedback.json', diagnostics)
    write(out/'architect_request.json', request)
    before = json.loads(original_answer)
    dispatched = []

    def call(node, kwargs):
        expected = dict(model=MODEL, max_tokens=8192, timeout=600,
                        temperature=.3 if node == 'architect' else .2)
        require(all(kwargs.get(k) == v for k, v in expected.items()), 'REQUEST_POLICY_MISMATCH')
        require(node not in dispatched, 'DUPLICATE_NODE_REQUEST')
        if node == 'coder':
            require(dispatched == ['architect'] and transport.gate_passed, 'CODER_BEFORE_GATE')
            write(out/'coder_request.json', kwargs)
        else:
            require(not dispatched and kwargs == request, 'CORRECTION_REQUEST_MISMATCH')
        dispatched.append(node)
        started = time.monotonic()
        response = transport('candidate', node, kwargs)
        require(len(response.choices) == 1, 'SINGLE_CHOICE_REQUIRED')
        choice = response.choices[0]
        usage = getattr(response, 'usage', None)
        usage = usage.model_dump() if hasattr(usage, 'model_dump') else usage
        write(out/(node+'_response.json'), dict(content=choice.message.content,
              finish_reason=choice.finish_reason, usage=usage,
              elapsed_seconds=time.monotonic()-started, cost_currency=None, missing_cost_is_not_zero=True))
        require(choice.finish_reason == 'stop' and isinstance(choice.message.content, str) and
                bool(choice.message.content.strip()), 'NON_STOP_OR_EMPTY_ANSWER')
        return response

    result = dict(experiment='INDEPENDENT_HISTORICAL_ANSWER_ONCE_CORRECTION_NOT_PAIRED',
                  max_new_requests=2, browser='NOT_EXECUTED', source_coverage='NOT_EVALUATED',
                  semantic_acceptance='UNKNOWN', first_plan_success=False)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: call('coder', kwargs))))
    with patch.dict(os.environ, ENVIRONMENT), PipelineTrace(out/'trace', metadata={
            'experiment':result['experiment'], 'original_answer_is_frozen_not_a_new_initial_plan':True}):
        try:
            answer = call('architect', request).choices[0].message.content
            envelope = json.loads(answer)
            require(isinstance(envelope, dict) and set(envelope) == {'corrected_plan', 'relation_changes'},
                    'EXACT_CORRECTION_ENVELOPE_REQUIRED')
            corrected = envelope['corrected_plan']
            write(out/'corrected_model_plan.json', corrected)
            # Persist raw change decisions before validation; never erase a failed correction.
            write(out/'model_relation_decisions.json', envelope['relation_changes'])
            invariants = correction_invariants(before, corrected, envelope['relation_changes'], vision, intent)
            write(out/'field_and_relation_invariants.json', invariants)
            write(out/'corrected_machine_feedback.json', diagnose(corrected, vision, intent))
            # Exact original production path. No local repair or weakened validator.
            compiled = ui_architect.finalize_ui_state(copy.deepcopy(corrected), intent,
                                                      copy.deepcopy(vision), 'baseline')
            require(isinstance(compiled, dict) and not compiled.get('error') and compiled.get('elements'),
                    'PRODUCTION_COMPILE_FAILED')
            write(out/'ui_state.json', compiled)
            gate = dict(status='ALL_PRE_CODER_GATES_PASS_NOT_SEMANTIC_ACCEPTANCE',
                        production_gate='original finalize_ui_state / compile_region_tree',
                        invariants=invariants['status'], source_coverage='NOT_EVALUATED', semantic='UNKNOWN')
            write(out/'pre_coder_gate.json', gate)
            transport.permit_coder(gate)
            with patch.object(coder, '_get_openai_client', return_value=client), \
                    patch.object(coder, 'save_html_asset', return_value=None):
                rendered = coder.generate_frontend_code(compiled)
            require(isinstance(rendered, dict) and rendered.get('code'), 'CODER_CONTRACT_FAILED')
            if export_html:
                export_coder_html(out, rendered['code'])
            result.update(status='CORRECTION_AND_CODER_RETURNED_NOT_ACCEPTED',
                          once_correction_mechanical_pass=True)
        except Exception as exc:
            result.update(status='STOPPED_NO_RETRY', error_type=type(exc).__name__, reason=str(exc),
                          once_correction_mechanical_pass=(out/'pre_coder_gate.json').exists())
    result.update(new_requests_dispatched=len(dispatched), nodes=dispatched,
                  coder_dispatched='coder' in dispatched, html_exists=(out/'original_coder.html').exists())
    write(out/'summary.json', result)
    return result


def diagnose(state, vision, intent):
    from src.utils.region_plan_diagnostics import diagnose_region_plan
    return diagnose_region_plan(state, vision, intent)
