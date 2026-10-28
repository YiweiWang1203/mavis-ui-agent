"""Predeclared permutations independent of page correctness."""
import copy


def permutation_arms(proposals):
    base=copy.deepcopy(proposals)
    ids=[r['id'] for r in base['candidates']]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate candidate identity')
    labels=copy.deepcopy(base)
    mapping={}
    for row,new_id in zip(labels['candidates'],reversed(ids)):
        original=row['id'];row['id']=new_id;mapping[new_id]=original
    reverse=copy.deepcopy(base);reverse['candidates'].reverse()
    return {'baseline_order':base,'labels_reverse':labels,'order_reverse':reverse}, {
        'baseline_order':{i:i for i in ids},'labels_reverse':mapping,'order_reverse':{i:i for i in ids}}
