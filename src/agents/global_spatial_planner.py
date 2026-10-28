"""One bounded spatial observation of the same input image and immutable objects."""
import base64
import json
from pathlib import Path
from src.utils.global_spatial_contract import compile_global_spatial


def plan_global_spatial(state, intent, image_path, model, client):
    prompt = (Path(__file__).resolve().parents[1]/'prompts/global_spatial.md').read_text(encoding='utf-8')
    url = 'data:image/jpeg;base64,'+base64.b64encode(Path(image_path).read_bytes()).decode('ascii')
    client.stage = 'global_spatial_planner'
    nodes = [{'id':e['id'],'type':e['type'],'text':e.get('text') or ''} for e in state['elements']]
    response = client.chat.completions.create(model=model,temperature=0,max_tokens=8192,timeout=600,
        response_format={'type':'json_object'},messages=[{'role':'system','content':prompt},
            {'role':'user','content':[{'type':'text','text':json.dumps({'original_intent':intent,
                'viewport':state['page_meta']['viewport'],'immutable_objects':nodes},ensure_ascii=False)},
                {'type':'image_url','image_url':{'url':url}}]}])
    if response.choices[0].finish_reason == 'length':
        raise ValueError('Spatial plan truncated; no retry')
    declaration = json.loads(response.choices[0].message.content)
    # Preserve model proposals before compilation, including invalid proposals.
    (client.output/'spatial_proposal.json').write_text(json.dumps(declaration,ensure_ascii=False,indent=2),encoding='utf-8')
    return compile_global_spatial(state,intent,declaration)
