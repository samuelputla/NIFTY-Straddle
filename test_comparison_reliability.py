import unittest,gzip,io,json,zipfile,tempfile,os
from pathlib import Path
from unittest.mock import patch
from comparison_runner import download_captures,read_capture
DAY='2026-11-04'
def archive(raw):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:z.writestr('comparison_capture_fixed_Current_Week.jsonl.gz',raw)
 return b.getvalue()
def journal():
 return gzip.compress(('\n'.join(json.dumps(x) for x in [dict(k='start',date=DAY,normal=True,version='comparison-v1',source='fixed_Current_Week'),dict(k='end',dropped=0,failed='')])+'\n').encode())
class Response:
 status_code=200
 def __init__(self,body=None,content=b''):self.body=body;self.content=content
 def json(self):return self.body
class Client:
 def __init__(self):self.headers={}
 def get(self,url,**kwargs):
  if '/workflows/rolling-' in url:return Response({'workflow_runs':[]})
  if '/workflows/' in url:return Response({'workflow_runs':[{'created_at':DAY+'T03:40:00Z','status':'completed','id':7}]})
  if '/runs/' in url:return Response({'artifacts':[{'name':'comparison-capture-bad','id':1,'size_in_bytes':100},{'name':'comparison-capture-good','id':2,'size_in_bytes':100}]})
  return Response(content=archive(journal()[:-6] if '/1/' in url else journal()))
class Tests(unittest.TestCase):
 def test_truncated_capture_does_not_abort_other_sources(self):
  with patch('comparison_runner.requests.Session',Client):sources,notes=download_captures(DAY,'fixture',set(),set())
  self.assertIn('fixed_Current_Week',sources);self.assertTrue(any('EOFError' in x for x in notes))
 def test_unfinalized_capture_is_closed_but_unavailable(self):
  from comparison_capture import Capture
  old=os.getcwd()
  with tempfile.TemporaryDirectory(dir=old) as folder:
   try:
    os.chdir(folder);c=Capture(DAY,'rolling');c._abandon();raw=c.path.read_bytes()
    self.assertTrue(gzip.decompress(raw))
    with self.assertRaises(ValueError):read_capture(raw,DAY,set(),set())
    before=raw;c.close();self.assertEqual(before,c.path.read_bytes())
   finally:os.chdir(old)
if __name__=='__main__':unittest.main()


