"""Zero-model engineering compatibility fixtures, NOT historical replay/UI score."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.agents.ui_architect import finalize_ui_state
from src.agents.coder import read_coder_prompt
from src.utils.pipeline_trace import PipelineTrace


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,required=True,help='JSON list with case_id,vision_path,state_path,transcript_path,run_identity')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    os.environ.update(UI_REGION_TREE_MODE='region_tree_v1',UI_NEUTRAL_VISUAL_MODE='neutral_v1',UI_STRUCTURE_MODE='baseline',UI_RENDERER_MODE='llm',UI_CODER_CONTRACT_MODE='baseline')
    results=[]
    for row in read(args.sources):
        case=args.out/row['case_id'];case.mkdir()
        files={k:Path(row[k]) for k in ('vision_path','state_path','transcript_path')}
        vision=read(files['vision_path']);historic=read(files['state_path']);intent=files['transcript_path'].read_text(encoding='utf-8-sig')
        # Deliberately synthetic organizational assignments exercise generic
        # compiler paths. They are NOT inferred/approved semantic answers.
        fixture={'page_meta':copy.deepcopy(historic['page_meta']),'elements':copy.deepcopy(vision['elements'])}
        ev=[{'source':'model_inference','reason':'synthetic compatibility fixture, not a case relationship prediction or user confirmation'}]
        size={'basis_px':'auto','grow':1,'shrink':1,'cross':'stretch'}
        root={'id':'region_fixture_root','kind':'semantic_region','parent':None,'evidence':[{'source':'system_root'}],
              'layout':{'direction':'row','gap_px':8,'padding_px':0,'overflow':'visible'}}
        groups=[{'id':'region_fixture_'+x,'kind':'semantic_region','parent':root['id'],'order':i,'evidence':copy.deepcopy(ev),'sizing':copy.deepcopy(size),
                 'layout':{'direction':'column','gap_px':4,'padding_px':0,'overflow':'auto'}} for i,x in enumerate(['a','b'])]
        fixture['region_contract']={'version':'region-tree-v1','root_id':root['id'],'regions':[root]+groups,
             'objects':[{'id':item['id'],'parent':groups[i%2]['id'],'order':i//2,'evidence':copy.deepcopy(ev),'sizing':copy.deepcopy(size)} for i,item in enumerate(fixture['elements'])]}
        write(case/'fixture_before.json',fixture)
        result={'case_id':row['case_id'],'kind':'synthetic engineering fixture over real historical visual IDs, NOT semantic/UI evaluation',
                'source_run_identity':row['run_identity'],'source_files':{k:{'path':str(p.resolve()),'sha256':sha(p)} for k,p in files.items()},'model_calls':0,'new_pages':0}
        try:
            with PipelineTrace(case/'trace',metadata={'fixture_only':True,'source_run':row['run_identity']}):
                compiled=finalize_ui_state(fixture,intent,vision,'baseline')
            write(case/'fixture_after.json',compiled)
            result.update(engineering_status='PASS',old_objects_preserved=compiled['elements']==fixture['elements'],
                          object_count=len(compiled['elements']),semantic_quality='NOT_EVALUATED',browser='NOT_EXECUTED',
                          coder_contract_present='region_layout' in read_coder_prompt())
        except Exception as exc:result.update(engineering_status='BLOCKED',reason=str(exc))
        write(case/'result.json',result);results.append(result)
    write(args.out/'summary.json',{'scope':'zero-call engineering compatibility only','results':results,'model_calls':0,'new_pages':0})
    print(json.dumps([{'case':r['case_id'],'engineering':r['engineering_status']} for r in results]))


if __name__=='__main__':main()
