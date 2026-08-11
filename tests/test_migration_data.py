import csv, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
from validate_migration_data import validate

class MigrationDataTests(unittest.TestCase):
 def test_rejects_unapproved_and_bad_stage(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); inv={'assets':[{'name':'skill-a','project_type':'skill'}]}; (p/'i.json').write_text(json.dumps(inv));
   cols='name,project_type,category,subcategory,primary_stage,workflow_stages,summary_zh,summary_en,interface_candidate,review_status,evidence'.split(',')
   with (p/'a.csv').open('w',newline='',encoding='utf8') as f: csv.DictWriter(f,cols).writeheader(); csv.DictWriter(f,cols).writerow(dict(zip(cols,['skill-a','skill','01','01.data-source-connectors','risk','data-ingestion','中文摘要有效','Generic skill-a','none','needs-maintainer','x'])))
   (p/'x.json').write_text(json.dumps({'items':[{'name':'skill-a','declaration_readable':True,'structured_explicit':False,'candidate_mode':'none','evidence_path':'x','formats':[],'fields':[],'maintainer_decision':'x','waves':['non-structured-review']}]})); (p/'w.json').write_text(json.dumps({'version':'1.0.0','waves':{'non-structured-review':['skill-a']}}))
   with self.assertRaises(ValueError): validate(p/'i.json',p/'a.csv',p/'x.json',p/'w.json',True)
