import hashlib, io, json, os, re, uuid
from datetime import date, datetime
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import github_store

st.set_page_config(page_title='Manufacturing SPC & Daily Analysis',page_icon='📈',layout='wide')
ROOT=Path(__file__).parent
CFG=json.loads((ROOT/'config/forms.json').read_text(encoding='utf-8'))
USERS=json.loads((ROOT/'config/users.json').read_text(encoding='utf-8'))['users']
DATA=ROOT/'data/quality_readings.csv';LIMITS=ROOT/'data/spec_limits.csv'
PLANTS=['Maliya','Tirupati Unit 1','Tirupati Unit 2','Tirupati Unit 3'];SHIFTS=['A','B','C','General','Not provided']
DC=['Record ID','Plant','Department','Form ID','Form Title','Inspection Date','Shift','Parameter ID','Parameter','Sample No','Value','Text Value','Unit','Created At']
LC=['Plant','Department','Form ID','Parameter ID','Parameter','Size','LSL','USL','Target','Updated At']
st.markdown('''<style>.stApp{background:#f5faf6}.block-container{max-width:1450px;padding-top:1rem}.hero{background:linear-gradient(120deg,#102d20,#16803d);color:white;border-radius:20px;padding:1.25rem 1.5rem;margin-bottom:1rem}.note{background:#eef8f0;border:1px solid #cce4d1;border-radius:12px;padding:.8rem}.stButton>button,.stDownloadButton>button{border-radius:10px}</style>''',unsafe_allow_html=True)
for k in ('GITHUB_TOKEN','GITHUB_OWNER','GITHUB_REPO','GITHUB_BRANCH'):
    if k in st.secrets:os.environ[k]=str(st.secrets[k])

def empty_frame(cols):return pd.DataFrame(columns=cols)
def safe_csv(text,cols):
    if text is None or not str(text).strip():return empty_frame(cols)
    try:df=pd.read_csv(io.StringIO(text),dtype=str,keep_default_na=False)
    except (pd.errors.EmptyDataError,pd.errors.ParserError,UnicodeDecodeError):return empty_frame(cols)
    if len(df.columns)==1 and df.columns[0].strip()=='':return empty_frame(cols)
    for c in cols:
        if c not in df.columns:df[c]=''
    return df[cols]
def read_df(path,cols):
    remote=None
    try:remote=github_store.read_text(str(path.relative_to(ROOT)).replace('\\','/'))
    except Exception as e:st.warning(f'GitHub read unavailable; using repository copy. {e}')
    if remote is not None:return safe_csv(remote,cols)
    if not path.exists() or path.stat().st_size==0:return empty_frame(cols)
    try:return safe_csv(path.read_text(encoding='utf-8-sig'),cols)
    except Exception:return empty_frame(cols)
def save_df(path,df,msg):
    for c in (DC if path==DATA else LC):
        if c not in df.columns:df[c]=''
    text=df.to_csv(index=False);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
    try:github_store.write_text(str(path.relative_to(ROOT)).replace('\\','/'),text,msg)
    except Exception as e:raise RuntimeError(f'Local save succeeded but GitHub save failed: {e}')
def readings():return read_df(DATA,DC)
def limits():return read_df(LIMITS,LC)
def forms():return [(d,f) for d,v in CFG['departments'].items() for f in v['forms']]
def get_form(d,t):return next(f for dep,f in forms() if dep==d and f['title']==t)
def departments():
    d=st.session_state.get('user',{}).get('departments',[]);return list(CFG['departments']) if '*' in d else [x for x in d if x in CFG['departments']]
def choose(prefix):
    dep=st.selectbox('Department',departments(),key=prefix+'dep');titles=[f['title'] for d,f in forms() if d==dep];return dep,get_form(dep,st.selectbox('Form',titles,key=prefix+'form'))
def norm(v):return re.sub(r'[^a-z0-9]+','',str(v).strip().lower())
def scalar(v):
    if isinstance(v,pd.Series):v=v.dropna();return '' if v.empty else v.iloc[0]
    return v
def time_text(v):
    if hasattr(v,'strftime'):return v.strftime('%H:%M:%S')
    s=re.sub(r'\s+','',str(v)).upper().rstrip('.');s=re.sub(r'(?<=\d)\.(?=\d)',':',s);m=re.fullmatch(r'(\d{1,2}):(\d{2})(?::(\d{2}))?(AM|PM)?',s)
    if not m:return str(v).strip()
    h,mi,se,a=m.groups();h,mi,se=int(h),int(mi),int(se or 0);h=h+12 if a=='PM' and h<12 else 0 if a=='AM' and h==12 else h;return f'{h:02d}:{mi:02d}:{se:02d}'
def size_text(v):
    s=str(v).strip()
    if not s:return 'Not specified'
    m=re.search(r'\d+(?:\.\d+)?',s)
    if m and ('mm' in s.lower() or float(m.group())<50):return f'{float(m.group()):g} mm'
    return s.replace('*',' × ')

def parse_excel(up,form):
    try:x=pd.read_excel(up,sheet_name='Quality Entry',engine='openpyxl').dropna(how='all')
    except ValueError:x=pd.read_excel(up,sheet_name=0,engine='openpyxl').dropna(how='all')
    if x.empty:return []
    x=x.loc[:,~x.columns.astype(str).str.startswith('Unnamed:')];aliases={'date':'date','inspectiondate':'date','shift':'shift'}
    for p in form.get('metadata',[])+form['parameters']:aliases[norm(p['label'])]=p['id']
    aliases.update({'time':'inspection_time','supopename':'supervisor_operator_name','pcrno':'press_number','finalsize':'tile_size','batchnumber':'batch_number','bodycode':'body_code','silonumber':'silo_number','grlengthmm':'green_length_mm','grweidthmm':'green_width_mm','greenwidthmm':'green_width_mm','greendiagonal1mm':'green_diagonal_1_mm','greendiagonal2mm':'green_diagonal_2_mm','remarkscommentsifany':'remarks'})
    for i in range(2,14):aliases[norm(f'TH. {i}')]=f'thickness_{i-1}';aliases[norm(f'B.D {i}')]=f'bulk_density_{i-1}'
    aliases['bulkdensity13']='bulk_density_13';aliases['bulkdensity14']='bulk_density_14'
    mapped={}
    for c in x.columns:
        target=aliases.get(norm(c))
        if not target:continue
        s=x[c]
        if isinstance(s,pd.DataFrame):s=s.bfill(axis=1).iloc[:,0]
        mapped[target]=mapped[target].combine_first(s) if target in mapped else s
    x=pd.DataFrame(mapped)
    if 'date' not in x:raise ValueError('Date / Inspection Date column is required.')
    rows=[]
    for _,r in x.iterrows():
        d=pd.to_datetime(scalar(r.get('date','')),errors='coerce')
        if pd.isna(d):continue
        payload={'meta':{},'single':{},'groups':{}}
        for p in form.get('metadata',[]):
            v=scalar(r.get(p['id'],''))
            if v is None or pd.isna(v) or str(v).strip()=='':continue
            payload['meta'][p['id']]=time_text(v) if p['type']=='time' else size_text(v) if p['id']=='tile_size' else str(v).strip()
        for p in form['parameters']:
            if p['type']=='subgroup':
                vals=[]
                for i in range(1,p.get('max_samples',14)+1):
                    v=pd.to_numeric(scalar(r.get(f'{p["id"]}_{i}','')),errors='coerce')
                    if not pd.isna(v):vals.append(float(v))
                payload['groups'][p['id']]=vals
            else:
                v=pd.to_numeric(scalar(r.get(p['id'],'')),errors='coerce')
                if not pd.isna(v):payload['single'][p['id']]=float(v)
        sh=str(scalar(r.get('shift','Not provided'))).strip();rows.append((d.date(),sh if sh in SHIFTS else 'Not provided',payload))
    return rows

def append_record(dep,form,d,shift,payload):
    rid=str(uuid.uuid4());now=datetime.now().isoformat(timespec='seconds');rows=[]
    for p in form.get('metadata',[]):
        v=payload.get('meta',{}).get(p['id'],'')
        if v!='':rows.append([rid,st.session_state.plant,dep,form['id'],form['title'],d,shift,p['id'],p['label'],'','',v,p.get('unit',''),now])
    for p in form['parameters']:
        if p['type']=='subgroup':
            for i,v in enumerate(payload.get('groups',{}).get(p['id'],[]),1):
                if v is not None:rows.append([rid,st.session_state.plant,dep,form['id'],form['title'],d,shift,p['id'],p['label'],i,float(v),'',p.get('unit',''),now])
        else:
            v=payload.get('single',{}).get(p['id'])
            if v is not None:rows.append([rid,st.session_state.plant,dep,form['id'],form['title'],d,shift,p['id'],p['label'],'',float(v),'',p.get('unit',''),now])
    if not rows:raise ValueError('No usable values were found in this inspection.')
    save_df(DATA,pd.concat([readings(),pd.DataFrame(rows,columns=DC)],ignore_index=True),'Append SPC inspection')

def manual():
    st.subheader('Manual Inspection Entry');dep,form=choose('m')
    with st.form('manual'):
        a,b=st.columns(2);d=a.date_input('Inspection Date');shift=b.selectbox('Shift',SHIFTS);p={'meta':{},'single':{},'groups':{}}
        for f in form.get('metadata',[]):p['meta'][f['id']]=st.time_input(f['label'],value=None,key='m'+f['id']) if f['type']=='time' else st.text_input(f['label'],key='m'+f['id'])
        for f in form['parameters']:
            if f['type']=='subgroup':
                n=st.number_input(f'Number of {f["label"]} samples',2,f.get('max_samples',14),12,key='n'+f['id']);cs=st.columns(6);p['groups'][f['id']]=[cs[(i-1)%6].number_input(f'{f["label"]} {i}',value=None,key=f['id']+str(i)) for i in range(1,int(n)+1)]
            else:p['single'][f['id']]=st.number_input(f['label'],value=None,key='m'+f['id'])
        go=st.form_submit_button('Save Inspection',type='primary',use_container_width=True)
    if go:
        try:
            if 'tile_size' in p['meta']:p['meta']['tile_size']=size_text(p['meta']['tile_size'])
            append_record(dep,form,d,shift,p);st.success('Inspection saved locally and to shared storage.')
        except Exception as e:st.error(str(e))
def upload():
    st.subheader('Excel Upload');dep,form=choose('u');path=ROOT/'excel_templates'/f"{form['id']}.xlsx"
    if path.exists():st.download_button('Download Excel Template',path.read_bytes(),file_name=path.name)
    up=st.file_uploader('Upload completed Excel',type='xlsx')
    if up and st.button('Import Excel',type='primary'):
        try:
            rows=parse_excel(up,form)
            if not rows:raise ValueError('No valid rows found. Check the Date column and numeric values.')
            for d,sh,p in rows:append_record(dep,form,d,sh,p)
            st.success(f'{len(rows)} inspections imported and stored.')
        except Exception as e:st.error(f'Import failed: {e}')

def form_data(form):
    x=readings();return x[(x['Plant'].astype(str)==st.session_state.plant)&(x['Form ID'].astype(str)==form['id'])].copy()
def sizes(form):
    x=form_data(form);m=x[x['Parameter ID']=='tile_size'];vals=sorted({size_text(v) for v in m['Text Value'] if str(v).strip()});return vals or ['Not specified']
def parameter_data(form,param,size=None):
    x=form_data(form);mapping=dict(zip(x[x['Parameter ID']=='tile_size']['Record ID'].astype(str),x[x['Parameter ID']=='tile_size']['Text Value'].map(size_text)));x=x[x['Parameter ID']==param['id']].copy()
    if size is not None:x=x[x['Record ID'].astype(str).map(mapping).fillna('Not specified')==size]
    x['V']=pd.to_numeric(x['Value'],errors='coerce');x['N']=pd.to_numeric(x['Sample No'],errors='coerce');x['D']=pd.to_datetime(x['Inspection Date'],errors='coerce').dt.date;x['C']=pd.to_datetime(x['Created At'],errors='coerce');return x.dropna(subset=['V','D']).sort_values(['D','C','Record ID','N'])
def imr(v):
    x=pd.Series(v,dtype=float).dropna().reset_index(drop=True)
    if len(x)<2:return None
    mr=x.diff().abs().dropna();m=mr.mean();cl=x.mean();return x,cl,cl+2.66*m,cl-2.66*m,mr,m,3.267*m,0,m/1.128 if m>0 else 0
def xbarr(groups):
    g=[np.array(v,float) for v in groups if len(v)>=2]
    if len(g)<2 or len({len(v) for v in g})!=1:return None
    n=len(g[0]);const={2:(1.88,0,3.267,1.128),3:(1.023,0,2.574,1.693),4:(.729,0,2.282,2.059),5:(.577,0,2.114,2.326),6:(.483,0,2.004,2.534),7:(.419,.076,1.924,2.704),8:(.373,.136,1.864,2.847),9:(.337,.184,1.816,2.970),10:(.308,.223,1.777,3.078),11:(.285,.256,1.744,3.173),12:(.266,.284,1.716,3.258),13:(.249,.308,1.692,3.336),14:(.235,.329,1.671,3.407)}
    if n not in const:return None
    a,d3,d4,d2=const[n];means=np.array([v.mean() for v in g]);ranges=np.array([v.max()-v.min() for v in g]);cl=means.mean();rb=ranges.mean();return means,cl,cl+a*rb,cl-a*rb,ranges,rb,d4*rb,d3*rb,rb/d2 if rb>0 else 0,n
def chart(title,x,y,cl,u,l,unit):
    f=go.Figure(go.Scatter(x=x,y=y,mode='lines+markers',line=dict(color='#16803d',width=2.5)))
    for v,n,c,d in [(u,'UCL','#c43d32','dash'),(cl,'CL','#2563eb','dot'),(l,'LCL','#c43d32','dash')]:f.add_hline(y=v,line_color=c,line_dash=d,annotation_text=f'{n}: {v:.3f}')
    f.update_layout(title=title,xaxis_title='Observation / Date',yaxis_title=unit,height=430,margin=dict(b=100));f.update_xaxes(tickangle=-45);return f
def limit_key(param,size):return f"{param['id']}::{norm(size)}" if size else param['id']
def saved_limit(dep,form,param,size):
    x=limits();key=limit_key(param,size);m=x[(x.Plant==st.session_state.plant)&(x.Department==dep)&(x['Form ID']==form['id'])&(x['Parameter ID']==key)]
    if m.empty:return None,None
    a=pd.to_numeric(m.iloc[-1].LSL,errors='coerce');b=pd.to_numeric(m.iloc[-1].USL,errors='coerce');return (None if pd.isna(a) else float(a),None if pd.isna(b) else float(b))
def store_limit(dep,form,param,size,lsl,usl):
    x=limits();key=limit_key(param,size);same=(x.Plant==st.session_state.plant)&(x.Department==dep)&(x['Form ID']==form['id'])&(x['Parameter ID']==key);x=x[~same];row=[st.session_state.plant,dep,form['id'],key,param['label'],size or '',lsl,usl,(lsl+usl)/2,datetime.now().isoformat(timespec='seconds')];save_df(LIMITS,pd.concat([x,pd.DataFrame([row],columns=LC)],ignore_index=True),'Update specification limits')
def analysis(day=False):
    st.subheader('Day-wise Analysis' if day else 'Observation-wise SPC & Capability');dep,form=choose('d' if day else 'a');labels=[p['label'] for p in form['parameters']];name=st.selectbox('Parameter',labels,key='p'+str(day));param=next(p for p in form['parameters'] if p['label']==name);size=st.selectbox('Size / Thickness Grade',sizes(form),key='s'+str(day)) if param.get('size_specific') else None;x=parameter_data(form,param,size)
    if x.empty:st.info('No stored data for this selection. Upload or enter at least two observations.');return
    if param['type']=='subgroup':
        pairs=[]
        for (rid,d),g in x.groupby(['Record ID','D'],sort=False):
            vals=g.sort_values('N').V.tolist()
            if len(vals)>=2:pairs.append((d,vals))
        if day:
            q=pd.DataFrame({'D':[d for d,v in pairs],'M':[np.mean(v) for d,v in pairs]}).groupby('D',as_index=False).M.mean();labels=q.D.astype(str).tolist();res=imr(q.M.tolist())
        else:labels=[f'Observation {i}<br>{d.strftime("%d-%b-%Y")}' for i,(d,v) in enumerate(pairs,1)];res=xbarr([v for d,v in pairs])
    else:
        if day:q=x.groupby('D',as_index=False).V.mean();labels=q.D.astype(str).tolist();res=imr(q.V.tolist())
        else:labels=[f'Observation {i}<br>{d.strftime("%d-%b-%Y")}' for i,d in enumerate(x.D,1)];res=imr(x.V.tolist())
    if not res:st.warning('At least two complete observations with a consistent subgroup size are required.');return
    if param['type']=='subgroup' and not day:vals,cl,u,l,r,rcl,ru,rl,sigma,n=res;st.caption(f'X-bar R chart, subgroup size n={n}, size={size}')
    else:vals,cl,u,l,r,rcl,ru,rl,sigma=res
    l0,u0=saved_limit(dep,form,param,size);a,b=st.columns(2);lsl=a.number_input('LSL',value=l0,key='lsl'+limit_key(param,size)+str(day));usl=b.number_input('USL',value=u0,key='usl'+limit_key(param,size)+str(day))
    if lsl is not None and usl is not None and usl>lsl and sigma>0:
        cp=(usl-lsl)/(6*sigma);cpk=min((usl-cl)/(3*sigma),(cl-lsl)/(3*sigma));c1,c2,c3=st.columns(3);c1.metric('Cp',f'{cp:.3f}');c2.metric('Cpk',f'{cpk:.3f}');c3.metric('Mean',f'{cl:.3f}')
        if st.button('Save Specification Limits',key='save'+limit_key(param,size)+str(day)):store_limit(dep,form,param,size,lsl,usl);st.success('Limits saved.')
    st.plotly_chart(chart(f'{name}{" - "+size if size else ""}',labels,vals,cl,u,l,param.get('unit','')),use_container_width=True)
    if not day:
        rlabs=labels[1:] if len(labels)==len(r)+1 else labels[:len(r)];st.plotly_chart(chart(f'{name} Range',rlabs,r,rcl,ru,rl,param.get('unit','')),use_container_width=True)
def data_page():
    x=readings();x=x[(x.Plant==st.session_state.plant)&x.Department.isin(departments())];st.metric('Stored rows',len(x));st.dataframe(x.tail(1000),use_container_width=True,hide_index=True);st.download_button('Download Data CSV',x.to_csv(index=False).encode(),file_name='quality_readings.csv')
def login():
    st.markdown("<div class='hero'><h2>Manufacturing SPC & Daily Analysis</h2><div>Secure plant and department access</div></div>",unsafe_allow_html=True);_,c,_=st.columns([1.2,1,1.2])
    with c:
        with st.form('login'):
            plant=st.selectbox('Plant',PLANTS);dept=st.selectbox('Department',['Plant Administration']+list(CFG['departments']));uid=st.text_input('User ID');pwd=st.text_input('Password',type='password');go=st.form_submit_button('Login',type='primary',use_container_width=True)
        if go:
            u=USERS.get(uid.strip());ok=bool(u) and hashlib.sha256(pwd.encode()).hexdigest()==u['password_sha256'] and plant in u.get('plants',[u.get('plant')]);ok=ok and ((dept=='Plant Administration' and u.get('role')=='admin') or '*' in u.get('departments',[]) or dept in u.get('departments',[]))
            if ok:st.session_state.logged=True;st.session_state.user=u;st.session_state.plant=plant;st.rerun()
            else:st.error('Invalid login details.')

if not st.session_state.get('logged'):login();st.stop()
with st.sidebar:
    st.success(st.session_state.user['display_name']);st.caption('Plant: '+st.session_state.plant)
    if st.button('Logout',use_container_width=True):st.session_state.clear();st.rerun()
st.markdown("<div class='hero'><h2>Manufacturing SPC & Daily Analysis</h2><div>Reliable storage, Excel upload, control charts, Cp/Cpk and plant-wise analysis</div></div>",unsafe_allow_html=True)
page=st.sidebar.radio('Page',['Manual Entry','Excel Upload','Observation-wise Analysis','Day-wise Analysis','Data'])
{'Manual Entry':manual,'Excel Upload':upload,'Observation-wise Analysis':lambda:analysis(False),'Day-wise Analysis':lambda:analysis(True),'Data':data_page}[page]()
