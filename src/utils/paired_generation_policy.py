"""Explicit shared policy for both paired arms; default-off preserves legacy."""
import os

def active():
    mode=os.getenv('UI_PAIRED_RUN_POLICY','off')
    if mode not in {'off','frozen_v1'}:raise ValueError('INVALID_PAIRED_POLICY')
    return mode=='frozen_v1'

def request_options(node, candidate=False):
    result={'temperature':{'architect':0.3,'coder':0.2}[node]}
    if active():
        model=os.environ.get('UI_PAIRED_MODEL')
        if not model:raise ValueError('PAIRED_MODEL_REQUIRED')
        result['model']=model
    if active() or candidate:result.update(max_tokens=8192,timeout=600)
    return result
