import base64, os, requests

def configured():
    return all(os.getenv(k) for k in ('GITHUB_TOKEN','GITHUB_OWNER','GITHUB_REPO'))

def _headers():
    return {'Authorization':f"Bearer {os.environ['GITHUB_TOKEN']}",'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}

def _url(path):
    return f"https://api.github.com/repos/{os.environ['GITHUB_OWNER']}/{os.environ['GITHUB_REPO']}/contents/{path}"

def read_text(path):
    if not configured(): return None
    r=requests.get(_url(path),headers=_headers(),params={'ref':os.getenv('GITHUB_BRANCH','main')},timeout=30)
    if r.status_code==404:return None
    r.raise_for_status();return base64.b64decode(r.json()['content']).decode('utf-8')

def write_text(path,text,message='Update SPC data'):
    if not configured(): return False
    branch=os.getenv('GITHUB_BRANCH','main')
    for _ in range(8):
        current=requests.get(_url(path),headers=_headers(),params={'ref':branch},timeout=30)
        sha=None if current.status_code==404 else current.json().get('sha')
        body={'message':message,'content':base64.b64encode(text.encode('utf-8')).decode('ascii'),'branch':branch}
        if sha:body['sha']=sha
        result=requests.put(_url(path),headers=_headers(),json=body,timeout=30)
        if result.status_code in (200,201):return True
        if result.status_code not in (409,422):result.raise_for_status()
    raise RuntimeError('GitHub update conflict. Please retry.')
