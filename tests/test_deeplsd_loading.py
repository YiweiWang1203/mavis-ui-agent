"""A failed checkpoint must never expose an uninitialized detector."""
from contextlib import nullcontext
from types import SimpleNamespace
import pytest
from scripts.run_paper_line_probe import load_official_deeplsd


pytest.importorskip('omegaconf')


def test_checkpoint_failure_does_not_initialize_detector():
    def fail(*args, **kwargs):
        assert kwargs['weights_only'] is True
        raise ValueError('invalid checkpoint')
    torch = SimpleNamespace(load=fail, serialization=SimpleNamespace(safe_globals=lambda _: nullcontext()))
    def forbidden(*args):
        pytest.fail('Detector initialized despite failed checkpoint')
    with pytest.raises(ValueError, match='invalid checkpoint'):
        load_official_deeplsd(torch, forbidden, 'checkpoint', 'cpu')


def test_strict_parameter_mismatch_is_not_returned():
    class Detector:
        def eval(self): return self
        def to(self, device): return self
        def load_state_dict(self, state, strict):
            assert strict is True
            raise RuntimeError('parameter mismatch')
    torch = SimpleNamespace(load=lambda *a, **k: {'model': {}},
                            serialization=SimpleNamespace(safe_globals=lambda _: nullcontext()))
    with pytest.raises(RuntimeError, match='parameter mismatch'):
        load_official_deeplsd(torch, lambda _: Detector(), 'checkpoint', 'cpu')
