"""Bounded provider boundary used by the main UI nodes, not an experiment runner."""
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace
import time

from src.utils.single_attempt_transport import isolated_sdk_call, write_new

ACTIVE = ContextVar('main_model_runtime', default=None)
MODEL = 'Qwen/Qwen3-VL-32B-Instruct'


def main_client(stage):
    runtime = ACTIVE.get()
    return runtime.client(stage) if runtime else None


def architect_review_enabled():
    runtime = ACTIVE.get()
    return runtime is None or runtime.profile != "source_relation_arm2"


def note_rejected_architect_repair(diagnostic):
    runtime = ACTIVE.get()
    if (runtime is None or runtime.profile != "semantic7" or runtime.failed
            or runtime.used[-1:] != ["architect_repair"] or runtime.architect_repair_rejected):
        raise RuntimeError("UNAUTHORIZED_ARCHITECT_REPAIR_FALLBACK")
    write_new(runtime.folder / "architect_repair_rejected.json", diagnostic)
    runtime.architect_repair_rejected = True


def note_vision_repair(feedback):
    runtime = ACTIVE.get()
    if runtime:
        if runtime.failed or runtime.used != ['vision_initial'] or runtime.repair_reason is not None:
            raise RuntimeError('UNAUTHORIZED_VISION_REPAIR')
        runtime.repair_reason = feedback
        write_new(runtime.folder / 'vision_repair_trigger.json', feedback)


class MainModelRuntime:
    def __init__(self, output, dispatch=None, *, profile="baseline4"):
        limits = {"baseline4": 4, "semantic7": 7, "audit1": 1,
                  "repair_probe_control1": 1, "repair_probe_feedback2": 2,
                  "source_relation_extract1": 1, "source_relation_arm2": 2}
        if profile not in limits:
            raise ValueError("UNKNOWN_RUNTIME_PROFILE")
        self.profile = profile
        self.limit = limits[profile]
        self.folder = Path(output)
        self.folder.mkdir(parents=True, exist_ok=False)
        self.dispatch = dispatch or isolated_sdk_call
        self.used = []
        self.repair_reason = None
        self.failed = False
        self.architect_repair_rejected = False

    def __enter__(self):
        self.token = ACTIVE.set(self)
        return self

    def __exit__(self, *args):
        ACTIVE.reset(self.token)

    def client(self, stage):
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kwargs: self.create(stage, **kwargs))))

    def create(self, stage, **kwargs):
        if self.failed:
            raise RuntimeError('PRIOR_REQUEST_FAILED_NO_RETRY')
        if stage == 'vision':
            slot = 'vision_initial' if not self.used else 'vision_repair'
        else:
            slot = stage
        if stage not in ('vision', 'architect', 'semantic_audit', 'architect_repair', 'semantic_reaudit',
                         'coder', 'source_relation_extract') or slot in self.used or len(self.used) >= self.limit:
            raise RuntimeError('MAIN_STAGE_ALREADY_CONSUMED_OR_UNAUTHORIZED')
        expected = ('vision' if not self.used else
                    'vision' if self.used == ['vision_initial'] and self.repair_reason is not None else
                    'coder' if self.used[-1] == 'architect' else 'architect')
        if self.profile == "audit1":
            allowed = {"semantic_audit"}
        elif self.profile == "repair_probe_control1":
            allowed = {"coder"}
        elif self.profile == "repair_probe_feedback2":
            allowed = {"coder"} if self.used else {"architect_repair"}
        elif self.profile == "source_relation_extract1":
            allowed = {"source_relation_extract"}
        elif self.profile == "source_relation_arm2":
            allowed = {"coder"} if self.used else {"architect"}
        elif self.profile == "semantic7" and self.used:
            successors = {
                "architect": {"semantic_audit"},
                "semantic_audit": {"architect_repair", "coder"},
                "architect_repair": {"coder"} if self.architect_repair_rejected else {"semantic_reaudit"},
                "semantic_reaudit": {"coder"},
            }
            allowed = successors.get(self.used[-1], {expected})
        else:
            allowed = {expected}
        if stage not in allowed:
            raise RuntimeError('MAIN_STAGE_ORDER_VIOLATION')
        if kwargs.get('model') != MODEL:
            raise RuntimeError('MAIN_MODEL_CONFIGURATION_MISMATCH')
        self.used.append(slot)  # Claim before dispatch; failure consumes the slot.
        request = {**kwargs, 'max_tokens': 8192, 'timeout': 600}
        write_new(self.folder / (slot + '_request.json'), request)
        terminal = {'stage': stage, 'slot': slot, 'usage': None, 'currency_cost': None,
                    'automatic_retries': 0, 'dispatch_attempts': 1}
        start = time.monotonic()
        try:
            diagnostics = self.folder / (slot + '_stages')
            diagnostics.mkdir()
            packet = self.dispatch(request, deadline=600, diagnostics_directory=diagnostics)
            write_new(self.folder / (slot + '_response.json'), packet)
            if not packet.get('ok'):
                raise RuntimeError('PROVIDER_' + str(packet.get('error_type', 'UNKNOWN')))
            response = packet['response']
            terminal.update(usage=response.get('usage'), provider_response_id=response.get('id'))
            choices = response.get('choices', [])
            if len(choices) != 1 or choices[0].get('finish_reason') != 'stop':
                raise RuntimeError('INCOMPLETE_MODEL_RESPONSE')
            text = choices[0].get('message', {}).get('content')
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError('EMPTY_MODEL_RESPONSE')
            terminal['status'] = 'RETURNED_NOT_USER_ACCEPTANCE'
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text),
                finish_reason='stop')], usage=response.get('usage'))
        except BaseException as error:
            self.failed = True
            terminal.update(status='FAILED_NO_RETRY', error_type=type(error).__name__)
            raise
        finally:
            terminal['elapsed_seconds'] = time.monotonic() - start
            write_new(self.folder / (slot + '_terminal.json'), terminal)
