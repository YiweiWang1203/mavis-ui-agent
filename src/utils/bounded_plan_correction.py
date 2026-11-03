"""One historical-answer correction, not an automatic retry or semantic judge.

No SDK/client creation here. Original production compilation remains authoritative.
All messages come from frozen generation inputs, its original answer and mechanical
diagnostics. Review answers and evaluation references are not accepted as inputs.
"""
import copy
import json

from src.utils.region_plan_diagnostics import diagnose_region_plan
from src.utils.region_tree_contract import evidence

MODEL = 'Qwen/Qwen3-VL-32B-Instruct'
SPATIAL_FIELDS = frozenset({'parent', 'order', 'relation_status', 'sizing', 'evidence'})
ENVIRONMENT = dict(
    UI_PAIRED_RUN_POLICY='frozen_v1', UI_PAIRED_MODEL=MODEL,
    UI_NEUTRAL_VISUAL_MODE='neutral_v1', UI_STRUCTURE_MODE='baseline',
    UI_RENDERER_MODE='llm', UI_RELATION_SPECIALIST_MODE='off',
    UI_INPUT_SEMANTIC_AUDIT_MODE='off', UI_SEMANTIC_TYPE_MODE='off',
    UI_COORDINATE_RESPONSIBILITY_MODE='off', UI_RELATION_AGGREGATION_MODE='off',
    UI_FUSION_MODE='exact_id', UI_CODER_CONTRACT_MODE='baseline',
    UI_INPUT_CONTRACT_MODE='off', UI_REGION_TREE_MODE='region_tree_v1',
    UI_REGION_RELATION_MODE='relation_first_v1', CODER_PROD_MODEL=MODEL,
    CODER_MODEL=MODEL)

CORRECTION_INSTRUCTIONS = '''
INDEPENDENT BOUNDED DIAGNOSTIC: this is one authorized correction of a saved,
failed planning answer, not another fresh initial plan, automatic retry, or paired
comparison. Existing validation rules remain unchanged. The response envelope for
THIS request supersedes the original top-level output shape only:
{"corrected_plan": <complete plan under the original contract>,
 "relation_changes": [{"id": "<relation id>", "operation": "keep|modify|drop|downgrade|add",
 "reason": "<reason for this decision>", "evidence": [<original-contract source items>]}]}
Return JSON only. Supply one ledger row for each changed, dropped, downgraded or
added relation ID, with original-contract evidence plus a reason. Unchanged IDs
need no model ledger row: code derives keep from exact old/new JSON equivalence.
Optional unchanged-ID notes are retained as unvalidated audit annotations, never
as effective source evidence. Keep existing IDs for retained/modified propositions.
Code saves the exact old/new values; the ledger is not independent confirmation.
You may correct, withdraw or mark unknown an unsupported original proposition;
do not preserve incorrect relationships merely to pass a retention count. Explain
each change/withdrawal using the ORIGINAL input and its traceable sources. Quotes
must be unique exact continuous substrings, never joined with ellipses. Separate
noncontinuous quotes into separate source items. Model inference must be labeled
as such. No reference answers or independent reviewers' expectations are provided.
Business-object IDs, types, text, actions and all non-spatial fields must remain
byte-value equivalent as parsed JSON. Keep their array order and the original
page_meta/target viewport; the photograph size is not the target canvas size.
Only element parent/order/relation_status/sizing/evidence, organizational regions
and relation claims may change. The existing source-provenance, tree, order and
relation-consistency gates still apply. Do not silently delete content or controls.
Empty/all-unknown relationships or all-unknown object memberships stop before
Coder; clearing assertions is not a successful correction. A withdrawn/unknown
claim never counts as source coverage. Passing these mechanical gates does not
prove intent preservation, coverage, geometry, behavior or visual quality.
There is no second correction if this answer fails. Do not invent sources.
'''


def require(condition, code):
    if not condition:
        raise ValueError(code)


def unique_by_id(items, code):
    require(isinstance(items, list) and all(isinstance(x, dict) for x in items), code)
    ids = [x.get('id') for x in items]
    require(all(isinstance(x, str) and x for x in ids) and len(ids) == len(set(ids)), code)
    return dict(zip(ids, items))


def correction_request(original_request, original_answer, vision, intent):
    require(isinstance(original_request, dict), 'ORIGINAL_REQUEST_REQUIRED')
    messages = original_request.get('messages')
    require(isinstance(messages, list) and len(messages) == 2 and
            [m.get('role') for m in messages] == ['system', 'user'] and
            all(isinstance(m.get('content'), str) for m in messages), 'ORIGINAL_MESSAGES_REQUIRED')
    require(original_request.get('model') == MODEL, 'ORIGINAL_MODEL_MISMATCH')
    state = json.loads(original_answer)
    feedback = diagnose_region_plan(state, vision, intent)
    payload = dict(original_messages=copy.deepcopy(messages), original_answer=original_answer,
                   frozen_vision=copy.deepcopy(vision), frozen_intent=intent,
                   machine_diagnostics=feedback,
                   limits='Mechanical feedback only; no GT, review or desired layout supplied.')
    request = dict(model=MODEL, temperature=.3, max_tokens=8192, timeout=600,
                   response_format={'type': 'json_object'}, messages=[
                       {'role': 'system', 'content': messages[0]['content'] + CORRECTION_INSTRUCTIONS},
                       {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}])
    return request, feedback


def correction_invariants(before, after, changes, vision, intent):
    """Mechanical preservation/non-vacuity gates, NEVER source coverage scoring."""
    require(isinstance(before, dict) and isinstance(after, dict), 'PLAN_OBJECT_REQUIRED')
    allowed = {'elements', 'region_contract', 'relation_plan'}
    require({k: v for k, v in before.items() if k not in allowed} ==
            {k: v for k, v in after.items() if k not in allowed}, 'NON_LAYOUT_TOP_LEVEL_CHANGE')
    old_objects = unique_by_id(before.get('elements'), 'OLD_OBJECT_IDS_INVALID')
    new_objects = unique_by_id(after.get('elements'), 'NEW_OBJECT_IDS_INVALID')
    require(list(old_objects) == list(new_objects), 'OBJECT_ID_OR_ARRAY_ORDER_CHANGED')
    require(bool(old_objects), 'EMPTY_OBJECT_SET')
    field_rows = []
    for oid, original in old_objects.items():
        target = new_objects[oid]
        old_fixed = {k: v for k, v in original.items() if k not in SPATIAL_FIELDS}
        new_fixed = {k: v for k, v in target.items() if k not in SPATIAL_FIELDS}
        require(old_fixed == new_fixed, 'BUSINESS_ATTRIBUTE_CHANGED:' + oid)
        field_rows.append(dict(id=oid, non_spatial_fields_preserved=True,
                               spatial_changes={k: {'before': original.get(k), 'after': target.get(k)}
                                   for k in sorted(SPATIAL_FIELDS) if original.get(k) != target.get(k)}))
    require(any(x.get('relation_status') == 'proposed' for x in new_objects.values()),
            'ALL_UNKNOWN_OBJECT_MEMBERSHIPS')
    old_claims = unique_by_id(before.get('relation_plan', {}).get('relations'), 'OLD_RELATION_IDS_INVALID')
    new_claims = unique_by_id(after.get('relation_plan', {}).get('relations'), 'NEW_RELATION_IDS_INVALID')
    require(bool(new_claims), 'EMPTY_RELATION_ESCAPE')
    require(any(x.get('status') == 'proposed' for x in new_claims.values()), 'ALL_UNKNOWN_RELATION_ESCAPE')
    decisions = unique_by_id(changes, 'RELATION_LEDGER_IDS_INVALID')
    all_ids = set(old_claims) | set(new_claims)
    changed_ids = {cid for cid in all_ids if old_claims.get(cid) != new_claims.get(cid)}
    require(changed_ids <= set(decisions) <= all_ids, 'INCOMPLETE_OR_UNKNOWN_RELATION_LEDGER')
    ledger = []
    visual_ids = {x['id'] for x in vision['elements']}
    for cid in sorted(all_ids):
        old, new = old_claims.get(cid), new_claims.get(cid)
        operation = ('add' if old is None else 'drop' if new is None else 'keep' if old == new
                     else 'downgrade' if old.get('status') == 'proposed' and new.get('status') == 'unknown'
                     else 'modify')
        row = decisions.get(cid)
        if operation == 'keep':
            # Model notes cannot change the derived operation or become verified
            # sources. Preserve them verbatim, including invalid extra evidence.
            warnings = []
            annotation_check = 'NO_ANNOTATION_EVIDENCE'
            if row is not None and row.get('evidence'):
                try:
                    evidence(row['evidence'], intent, visual_ids)
                    annotation_check = 'VALID_FORMAT_LOCATION_ONLY_NOT_EFFECTIVE_SOURCE'
                except (ValueError, TypeError, KeyError) as exc:
                    annotation_check = 'INVALID_ANNOTATION_SOURCE_NOT_EFFECTIVE_SOURCE'
                    warnings.append(dict(code=str(exc), scope='annotation_only_not_production_claim'))
            if row is not None and row.get('operation') != 'keep':
                warnings.append(dict(code='DECLARED_OPERATION_DISAGREES_WITH_DERIVED_KEEP',
                                     scope='untrusted_annotation'))
            ledger.append(dict(id=cid, operation='keep', before=copy.deepcopy(old), after=copy.deepcopy(new),
                               reason='Code-derived exact old/new JSON equivalence', evidence=[],
                               audit_annotation_unvalidated=copy.deepcopy(row),
                               annotation_evidence_status='NOT_USED_AS_EFFECTIVE_SOURCE',
                               annotation_syntax_check=annotation_check, annotation_warnings=warnings,
                               semantic_support='UNKNOWN', source_coverage='NOT_EVALUATED_BY_MECHANICAL_GATE',
                               removed_or_unknown_not_coverage=new.get('status') == 'unknown'))
            continue
        require(set(row) == {'id', 'operation', 'reason', 'evidence'}, 'INVALID_CHANGE_LEDGER_FIELDS')
        require(row['operation'] == operation, 'MISREPORTED_RELATION_OPERATION:' + cid)
        require(isinstance(row['reason'], str) and bool(row['reason'].strip()), 'CHANGE_REASON_REQUIRED')
        resolved = evidence(row['evidence'], intent, visual_ids)
        ledger.append(dict(id=cid, operation=operation, before=copy.deepcopy(old), after=copy.deepcopy(new),
                           reason=row['reason'], evidence=resolved,
                           semantic_support='UNKNOWN', source_coverage='NOT_EVALUATED_BY_MECHANICAL_GATE',
                           removed_or_unknown_not_coverage=new is None or new.get('status') == 'unknown'))
    return dict(status='MECHANICAL_INVARIANTS_PASS_NOT_SEMANTIC_ACCEPTANCE',
                object_fields=field_rows, relation_changes=ledger,
                semantic_review='REQUIRED_INDEPENDENTLY', source_coverage='NOT_EVALUATED',
                behavior='NOT_EVALUATED', visual='NOT_EVALUATED')
