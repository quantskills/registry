import csv, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
from validate_migration_data import COLUMNS, validate

class MigrationDataTests(unittest.TestCase):
 def write(self, root, mutate=lambda rows,audit,waves: None):
  names=['skill-a','skill-b','agent-a']; inv={'sha256':'sha256:x','assets':[{'name':n} for n in names]}; (root/'i.json').write_text(json.dumps(inv))
  rows=[]; stage=[('data-ingestion','01','01.data-source-connectors'),('data-quality','01','01.warehouse-cache'),('feature-engineering','02','02.factor-generation')]
  for n,(s,c,sub) in zip(names,stage): rows.append(dict(zip(COLUMNS,[n,'agent' if n.startswith('agent') else 'skill',c,sub,s,s,'中文摘要内容','Useful reviewed summary','natural-language','approved','README.md'])))
  audit={'schema_version':'1.0.0','inventory_sha256':inv['sha256'],'items':[{'name':n,'declaration_readable':True,'structured_io_explicit':False,'candidate_mode':'natural-language','evidence_paths':['README.md'],'detected_formats':[],'detected_fields':[],'required_maintainer_decision':'none','waves':['agent-runtime' if n.startswith('agent') else 'non-structured-review'],'notes':''} for n in names]}; waves={'schema_version':'1.0.0','inventory_sha256':inv['sha256'],'waves':{'agent-runtime':['agent-a'],'non-structured-review':['skill-a','skill-b']}}
  mutate(rows,audit,waves)
  with (root/'a.csv').open('w',newline='',encoding='utf8') as f: w=csv.DictWriter(f,COLUMNS);w.writeheader();w.writerows(rows)
  (root/'x.json').write_text(json.dumps(audit));(root/'w.json').write_text(json.dumps(waves));return root/'i.json',root/'a.csv',root/'x.json',root/'w.json'
 def test_positive_and_negatives(self):
  cases=[lambda r,a,w:r.__setitem__(1,r[0]),lambda r,a,w:r[0].update(review_status='blocked'),lambda r,a,w:r[0].update(workflow_stages='risk|data-ingestion'),lambda r,a,w:a.update(inventory_sha256='bad'),lambda r,a,w:a['items'][0].update(candidate_mode='bad')]
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); args=self.write(p); self.assertEqual(validate(*args)['assets'],3)
   for mutate in cases:
    with self.subTest(mutate=mutate):
     args=self.write(p,mutate); self.assertRaises(ValueError,validate,*args); args=self.write(p,mutate); self.assertRaises(ValueError,validate,*args,True)
if __name__=='__main__': unittest.main()
