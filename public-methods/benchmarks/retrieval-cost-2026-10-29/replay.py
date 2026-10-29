import json,pathlib
R=pathlib.Path(__file__).resolve().parent;gold={t['id']:t for t in json.loads((R/'protocol/gold.json').read_text())['tasks']};summary={}
for p in sorted((R/'artifacts').iterdir()):
 arm,task=p.name.split('-');task=task.upper();s=summary.setdefault(arm,dict(input=0,output=0,cached=0,calls=0,decisions=0,strict_json=0))
 text=(p/'final.txt').read_text()
 try:a=json.loads(text);s['strict_json']+=1
 except ValueError:a=json.JSONDecoder().raw_decode(text.strip())[0]
 s['decisions']+=sum(type(a.get('decisions',{}).get(k)) is type(v) and a['decisions'][k]==v for k,v in gold[task]['decisions'].items())
 u={'input_tokens':0,'output_tokens':0,'cached_input_tokens':0}
 for line in (p/'model-receipts.jsonl').read_text().splitlines():
  x=json.loads(line);assert x['model']=='gpt-6-luna' and x['completed'];s['calls']+=1;v=x['usage'];u['input_tokens']+=v['input_tokens'];u['output_tokens']+=v['output_tokens'];u['cached_input_tokens']+=v.get('input_tokens_details',{}).get('cached_tokens',0)
 cli=json.loads((p/'cli-usage.json').read_text())[-1];assert all(cli[k]==v for k,v in u.items()),p.name
 s['input']+=u['input_tokens'];s['output']+=u['output_tokens'];s['cached']+=u['cached_input_tokens']
for arm,s in summary.items():s['total']=s['input']+s['output']
print(json.dumps(summary,indent=2))
