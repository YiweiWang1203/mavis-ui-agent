"""Compile explicit page-scope judgments without inventing boundary coordinates."""
from src.utils.closed_page_candidates import select_candidate


def select_with_scope(proposals, declaration):
    if not isinstance(declaration,dict) or set(declaration)!={'candidate_id','unresolved_reason','assessments'}:
        raise ValueError('Expected selection and complete scope assessments')
    index={r['id']:r for r in proposals['candidates']}
    assessments=declaration['assessments']
    if not isinstance(assessments,list):raise ValueError('Scope assessments must be a list')
    seen={}
    for r in assessments:
        if not isinstance(r,dict) or set(r)!={'candidate_id','scope','outside_ui_evidence','boundary_evidence'}:
            raise ValueError('Invalid scope assessment')
        key=r['candidate_id']
        if key not in index or key in seen:raise ValueError('Unknown or repeated assessed candidate')
        if r['scope'] not in {'whole_ui_page','internal_region','paper_or_background','uncertain'}:
            raise ValueError('Unknown scope')
        if not isinstance(r['outside_ui_evidence'],list) or any(not isinstance(s,str) or not s.strip() for s in r['outside_ui_evidence']):
            raise ValueError('Outside UI evidence must be a string list')
        if not isinstance(r['boundary_evidence'],str) or not r['boundary_evidence'].strip():
            raise ValueError('Scope requires boundary evidence')
        seen[key]=r
    if set(seen)!=set(index):raise ValueError('Missing candidate scope assessment')
    key=declaration['candidate_id']
    if key is not None:
        if key not in seen:raise ValueError('Unknown selected candidate')
        if seen[key]['scope']!='whole_ui_page' or seen[key]['outside_ui_evidence']:
            raise ValueError('Selected candidate does not satisfy whole-page scope')
    result=select_candidate(proposals,{k:declaration[k] for k in ['candidate_id','unresolved_reason']})
    result['scope_assessments']=assessments
    result['limits']='Self-reported evidence and local consistency checks do not establish visual correctness.'
    return result
