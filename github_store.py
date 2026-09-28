import base64,io,pandas as pd,requests,streamlit as st
PATH='data/quality_readings.csv';COLS=['Record ID','Plant','Department','Form ID','Form Title','Inspection Date','Shift','Parameter ID','Parameter','Value','Text Value','Unit','Created At']
def h():return {'Authorization':f"Bearer {st.secrets['GITHUB_TOKEN']}",'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
def u():return f"https://api.github.com/repos/{st.secrets['GITHUB_OWNER']}/{st.secrets['GITHUB_REPO']}/contents/{PATH}"
def read_data():
 r=requests.get(u(),headers=h(),params={'ref':st.secrets.get('GITHUB_BRANCH','main')},timeout=30);r.raise_for_status();p=r.json();df=pd.read_csv(io.BytesIO(base64.b64decode(p['content'])))
 for c in COLS:
  if c not in df:df[c]=''
 return df[COLS],p['sha']
def append_rows(rows,msg):
 df,sha=read_data();df=pd.concat([df,pd.DataFrame(rows)],ignore_index=True);content=base64.b64encode(df[COLS].to_csv(index=False).encode()).decode();r=requests.put(u(),headers=h(),json={'message':msg,'content':content,'sha':sha,'branch':st.secrets.get('GITHUB_BRANCH','main')},timeout=30);r.raise_for_status()
