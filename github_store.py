import base64,os,requests

def configured():return all(os.getenv(k) for k in ('GITHUB_TOKEN','GITHUB_OWNER','GITHUB_REPO'))
def h():return {'Authorization':f"Bearer {os.environ['GITHUB_TOKEN']}",'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
def url(p):return f"https://api.github.com/repos/{os.environ['GITHUB_OWNER']}/{os.environ['GITHUB_REPO']}/contents/{p}"
def read_text(p):
 if not configured():return None
 r=requests.get(url(p),headers=h(),params={'ref':os.getenv('GITHUB_BRANCH','main')},timeout=30)
 if r.status_code==404:return None
 r.raise_for_status();return base64.b64decode(r.json()['content']).decode()
def write_text(p,text,msg):
 if not configured():return False
 branch=os.getenv('GITHUB_BRANCH','main')
 for _ in range(6):
  r=requests.get(url(p),headers=h(),params={'ref':branch},timeout=30);sha=None if r.status_code==404 else r.json()['sha'];body={'message':msg,'content':base64.b64encode(text.encode()).decode(),'branch':branch}
  if sha:body['sha']=sha
  q=requests.put(url(p),headers=h(),json=body,timeout=30)
  if q.status_code in (200,201):return True
 raise RuntimeError('GitHub update conflict. Retry.')
