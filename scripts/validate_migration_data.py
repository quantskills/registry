#!/usr/bin/env python3
"""Fail-closed validator for reviewed catalog migration inputs."""
import argparse,csv,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
COLUMNS=['name','project_type','category','subcategory','primary_stage','workflow_stages','summary_zh','summary_en','interface_candidate','review_status','evidence']
STATUSES={'approved','needs-maintainer','blocked'}; MODES={'structured-existing','structured-remaining','non-structured-review','agent-runtime','core-chain'}
BAD=re.compile(r'\b(?:official|certified|guaranteed|profit|returns?|稳赚|保证收益)\b',re.I)
def load(p): return json.loads(Path(p).read_text(encoding='utf8'))
def validate(inventory,assignments,interfaces,waves,enforce=False):
 inv=load(inventory); names={x['name']:x for x in inv.get('assets',[])}
 with open(assignments,encoding='utf8',newline='') as f: rows=list(csv.DictReader(f)); got=list(rows[0]) if rows else COLUMNS
 if got!=COLUMNS or len(rows)!=len(names) or {r.get('name') for r in rows}!=set(names) or len({r.get('name') for r in rows})!=len(rows): raise ValueError('assignment join failed')
 tax=load(ROOT/'schema/taxonomy.v1.json'); subs={x['id']:cat for cat,v in tax['categories'].items() for x in v['subcategories']}; stages=set(tax['workflow_stages']); covered=set()
 for r in rows:
  pipe=r['workflow_stages'].split('|')
  if pipe!=sorted(set(pipe)) or r['primary_stage'] not in pipe or any(x not in stages for x in pipe) or subs.get(r['subcategory'])!=r['category'] or r['project_type']!=names[r['name']].get('project_type') or not r['summary_zh'].strip() or not r['summary_en'].strip() or r['summary_en'].lower().strip()==r['name'] or BAD.search(r['summary_zh']+' '+r['summary_en']) or r['review_status'] not in STATUSES: raise ValueError('invalid assignment')
  if enforce and r['review_status']!='approved': raise ValueError('unapproved assignment')
  covered.update(pipe)
 if covered!=stages: raise ValueError('stage coverage failed')
 data=load(interfaces); items=data.get('items'); w=load(waves); table=w.get('waves')
 if not isinstance(items,list) or not isinstance(table,dict) or {x.get('name') for x in items}!=set(names): raise ValueError('interface join failed')
 for item in items:
  if set(item)!={'name','declaration_readable','structured_explicit','candidate_mode','evidence_path','formats','fields','maintainer_decision','waves'} or not isinstance(item['waves'],list) or any(x not in table or item['name'] not in table[x] or x not in MODES for x in item['waves']): raise ValueError('invalid interface audit')
 for wave, members in table.items():
  if wave not in MODES or not isinstance(members,list) or len(members)!=len(set(members)) or not set(members)<=set(names): raise ValueError('invalid waves')
 return {'assets':len(rows),'approved':sum(r['review_status']=='approved' for r in rows),'structured':sum(x['structured_explicit'] for x in items)}
def main():
 p=argparse.ArgumentParser(); p.add_argument('--inventory',required=True);p.add_argument('--assignments',required=True);p.add_argument('--interfaces',required=True);p.add_argument('--waves',required=True);p.add_argument('--enforce',action='store_true');a=p.parse_args(); print(json.dumps(validate(a.inventory,a.assignments,a.interfaces,a.waves,a.enforce),sort_keys=True))
if __name__=='__main__': main()
