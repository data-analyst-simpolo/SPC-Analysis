import hashlib, io, json, os, re, uuid
from datetime import date, datetime
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import github_store

st.set_page_config(page_title='Manufacturing SPC Portal',page_icon='📈',layout='wide')
ROOT=Path(__file__).parent
CONFIG=json.loads((ROOT/'config/forms.json').read_text(encoding='utf-8'))
USERS=json.loads((ROOT/'config/users.json').read_text(encoding='utf-8'))['users']
DATA=ROOT/'data/quality_readings.csv'; LIMITS=ROOT/'data/spec_limits.csv'
COLS=['Record ID','Plant','Department','Form ID','Form Title','Inspection Date','Shift','Parameter ID','Parameter','Value','Text Value','Unit','Created At']
PLANTS=['Maliya','Tirupati Unit 1','Tirupati Unit 2','Tirupati Unit 3']
SHIFTS=['A','B','C','General','Not provided']
st.markdown('''<style>.stApp{background:#f5faf6}.block-container{max-width:1450px;padding-top:1.1rem}.hero{background:linear-gradient(125deg,#102d20,#16803d);color:white;border-radius:22px;padding:1.3rem 1.55rem;margin-bottom:1rem;box-shadow:0 12px 30px rgba(16,45,32,.14)}.login{max-width:570px;margin:3vh auto;background:white;border:1px solid #d7e5db;border-radius:24px;padding:1.5rem;box-shadow:0 20px 52px rgba(16,45,32,.15)}.brand{background:linear-gradient(125deg,#102d20,#16803d);color:white;border-radius:18px;padding:1.25rem;margin-bottom:1rem}.chip{display:inline-block;background:#e8f7eb;color:#166534;border-radius:999px;padding:.28rem .7rem;font-weight:800;font-size:.75rem}.stButton>button,.stDownloadButton>button{border-radius:10px}</style>''',unsafe_allow_html=True)
for k in ('GITHUB_TOKEN','GITHUB_OWNER','GITHUB_REPO','GITHUB_BRANCH'):
    if k in st.secrets:os.environ[k]=str(st.secrets[k])

def allowed_depts():
    d=st.session_state.get('user',{}).get('departments',[]);return list(CONFIG['departments']) if '*' in d else [x for x in d if x in CONFIG['departments']]
def login_page():
    st.markdown("<div class='login'><div class='brand'><span class='chip'>MANUFACTURING EXCELLENCE</span><h2 style='margin:.65rem 0 .2rem'>SPC & Daily Analysis Portal</h2><div style='opacity:.85'>Secure plant and department access</div></div></div>",unsafe_allow_html=True)
    _,c,_=st.columns([1.2,1,1.2])
    with c:
        with st.form('login'):
            plant=st.selectbox('Plant',PLANTS);department=st.selectbox('Department',['Plant Administration']+list(CONFIG['departments']));user=st.text_input('User ID');password=st.text_input('Password',type='password');go=st.form_submit_button('Secure Login',type='primary',use_container_width=True)
        if go:
            u=USERS.get(user.strip());ok=bool(u) and hashlib.sha256(password.encode()).hexdigest()==u.get('password_sha256') and plant in u.get('plants',[])
            ok=ok and ((department=='Plant Administration' and u.get('role')=='admin') or department in u.get('departments',[]) or '*' in u.get('departments',[]))
            if ok:st.session_state.logged=True;st.session_state.user=u;st.session_state.plant=plant;st.rerun()
            else:st.error('Invalid plant, department, user ID or password.')
        st.caption('Default credentials are documented in README_DEPLOY.md. Change them before production use.')
def read_csv(path,cols):
    text=github_store.read_text(str(path.relative_to(ROOT)).replace('\\','/'))
    if text is not None:df=pd.read_csv(io.StringIO(text))
    elif path.exists():df=pd.read_csv(path)
    else:df=pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:df[c]=''
    return df[cols]
def write_csv(path,df,msg):
    text=df.to_csv(index=False);path.write_text(text,encoding='utf-8');github_store.write_text(str(path.relative_to(ROOT)).replace('\\','/'),text,msg)
def readings():return read_csv(DATA,COLS)
def flat_forms():return [(d,f) for d,x in CONFIG['departments'].items() for f in x['forms']]
def get_form(d,t):return next(f for dep,f in flat_forms() if dep==d and f['title']==t)
def norm(x):return re.sub(r'[^a-z0-9]+','',str(x).strip().lower())
def first_scalar(v):
    if isinstance(v,pd.Series):
        z=v.dropna();return '' if z.empty else z.iloc[0]
    return v
def clean_time(v):
    v=first_scalar(v)
    if v is None or (not isinstance(v,(list,tuple,dict)) and pd.isna(v)):return ''
    if hasattr(v,'strftime'):return v.strftime('%H:%M:%S')
    raw=re.sub(r'\s+','',str(v).strip()).upper().rstrip('.');raw=re.sub(r'(?<=\d)[.](?=\d)',':',raw)
    m=re.fullmatch(r'(\d{1,2}):(\d{2})(?::(\d{2}))?(AM|PM)?',raw)
    if m:
        h,mi,se,suf=m.groups();h,mi,se=int(h),int(mi),int(se or 0)
        if suf=='PM' and h<12:h+=12
        if suf=='AM' and h==12:h=0
        if 0<=h<24 and 0<=mi<60 and 0<=se<60:return f'{h:02d}:{mi:02d}:{se:02d}'
    parsed=pd.to_datetime(raw,errors='coerce');return str(v).strip() if pd.isna(parsed) else parsed.strftime('%H:%M:%S')

def parse_excel(upload,form):
    raw=pd.read_excel(upload,sheet_name='Quality Entry',engine='openpyxl').dropna(how='all');raw=raw.loc[:,~raw.columns.astype(str).str.startswith('Unnamed:')]
    aliases={norm('Inspection Date'):'Inspection Date',norm('Shift'):'Shift'}
    for p in form.get('metadata',[])+form['parameters']:aliases[norm(p['label'])]=p['id']
    aliases.update({'date':'Inspection Date','time':'inspection_time','supopename':'supervisor_operator_name','pcrno':'press_number','finalsize':'tile_size','batchnumber':'batch_number','bodycode':'body_code','silonumber':'silo_number','grlengthmm':'green_length_mm','grweidthmm':'green_width_mm','greenwidthmm':'green_width_mm','greendiagonal1mm':'green_diagonal_1_mm','greendiagonal2mm':'green_diagonal_2_mm','bulkdensity13':'bulk_density_13_extra','bulkdensity14':'bulk_density_14','remarkscommentsifany':'remarks'})
    for i in range(2,14):aliases[norm(f'TH. {i}')]=f'thickness_{i}';aliases[norm(f'B.D {i}')]=f'bulk_density_{i}'
    mapped={}
    for original in raw.columns:
        target=aliases.get(norm(original))
        if not target:continue
        series=raw[original]
        if isinstance(series,pd.DataFrame):series=series.bfill(axis=1).iloc[:,0]
        mapped[target]=mapped[target].combine_first(series) if target in mapped else series
    x=pd.DataFrame(mapped,index=raw.index)
    if 'Inspection Date' not in x.columns:raise ValueError('Inspection Date / Date column is required.')
    fields={p['id']:p for p in form.get('metadata',[])+form['parameters']};out=[]
    for _,r in x.iterrows():
        d=pd.to_datetime(first_scalar(r.get('Inspection Date','')),errors='coerce')
        if pd.isna(d):continue
        shift=first_scalar(r.get('Shift','Not provided'));shift='Not provided' if shift is None or pd.isna(shift) or str(shift).strip() not in SHIFTS else str(shift).strip();vals={}
        for pid,p in fields.items():
            if pid not in x.columns:continue
            v=first_scalar(r.get(pid,''))
            if v is None or (not isinstance(v,(list,tuple,dict)) and pd.isna(v)) or v=='':continue
            if pid=='inspection_time':v=clean_time(v)
            elif p['type']=='number':
                v=pd.to_numeric(v,errors='coerce')
                if pd.isna(v):continue
                v=float(v)
            else:v=str(v).strip().replace('\\*','*')
            vals[pid]=v
        out.append((d.date(),shift,vals))
    if not out:raise ValueError('No valid inspection rows were found in the Excel file.')
    return out

def save_record(dep,form,d,shift,values):
    rid=str(uuid.uuid4());now=datetime.now().isoformat(timespec='seconds');rows=[]
    for p in form.get('metadata',[])+form['parameters']:
        v=values.get(p['id'])
        if v is None or v=='':continue
        rows.append({'Record ID':rid,'Plant':st.session_state.plant,'Department':dep,'Form ID':form['id'],'Form Title':form['title'],'Inspection Date':str(d),'Shift':shift,'Parameter ID':p['id'],'Parameter':p['label'],'Value':v if p['type']=='number' else '','Text Value':clean_time(v) if p['type']=='time' else ('' if p['type']=='number' else str(v)),'Unit':p.get('unit',''),'Created At':now})
    write_csv(DATA,pd.concat([readings(),pd.DataFrame(rows)],ignore_index=True),'Append SPC inspection')
def widget(p,key):
    if p['type']=='number':return st.number_input(p['label'],value=None,key=key)
    if p['type']=='time':return st.time_input(p['label'],value=None,key=key)
    return st.text_input(p['label'],key=key)
def wide(form):
    x=readings();x=x[(x['Plant'].astype(str).eq(st.session_state.plant)) & x['Form ID'].eq(form['id'])]
    if x.empty:return pd.DataFrame()
    b=x.groupby('Record ID').first()[['Inspection Date','Shift','Created At']];n=x.assign(N=pd.to_numeric(x['Value'],errors='coerce')).pivot_table(index='Record ID',columns='Parameter ID',values='N',aggfunc='first');t=x.pivot_table(index='Record ID',columns='Parameter ID',values='Text Value',aggfunc='first');return b.join(n,rsuffix='_n').join(t,rsuffix='_t').reset_index()
def imr(v):
    x=pd.Series(v,dtype=float).dropna().reset_index(drop=True)
    if len(x)<2:return None
    mr=x.diff().abs().dropna();m=mr.mean();cl=x.mean();return x,cl,cl+2.66*m,cl-2.66*m,mr,m,3.267*m,0
def xbarr(a):
    a=np.array(a,float);a=a[~np.isnan(a).all(1)]
    if len(a)<2:return None
    means=np.nanmean(a,1);ranges=np.nanmax(a,1)-np.nanmin(a,1);n=int(np.nanmedian(np.sum(~np.isnan(a),1)));a2,d3,d4=(.373,.136,1.864) if n<=8 else (.266,.284,1.716);xb=means.mean();rb=ranges.mean();return means,xb,xb+a2*rb,xb-a2*rb,ranges,rb,d4*rb,d3*rb
def figure(title,x,y,cl,u,l,unit):
    f=go.Figure(go.Scatter(x=x,y=y,mode='lines+markers',line=dict(color='#16803d',width=2.5),marker=dict(size=7,color='#16803d')))
    for v,n,c,d in [(u,'UCL','#c53b31','dash'),(cl,'CL','#2563eb','dot'),(l,'LCL','#c53b31','dash')]:f.add_hline(y=v,line_color=c,line_dash=d,annotation_text=f'{n}: {v:.2f}')
    f.update_layout(title=title,xaxis_title='Observation / Inspection Date',yaxis_title=unit,height=430,margin=dict(b=100),paper_bgcolor='white',plot_bgcolor='#fbfdfb');f.update_xaxes(tickangle=-45,automargin=True);return f
def items(form):
    out=[];groups=[]
    for p in form['parameters']:
        if p.get('chart_group'):
            if p['chart_group'] not in groups:groups.append(p['chart_group'])
        else:out.append(('p',p['label'],p))
    for g in groups:out.append(('g',g,{'chart_group':g,'unit':next(p['unit'] for p in form['parameters'] if p.get('chart_group')==g)}))
    return out
def series(form,item,day,start=None,end=None):
    x=wide(form)
    if x.empty:return None
    x['Date']=pd.to_datetime(x['Inspection Date']).dt.date;x['Created']=pd.to_datetime(x['Created At']);x=x.sort_values(['Date','Created','Record ID'])
    if start:x=x[x.Date>=start]
    if end:x=x[x.Date<=end]
    if item[0]=='p':
        p=item[2];x['M']=pd.to_numeric(x.get(p['id']),errors='coerce');x=x.dropna(subset=['M'])
        if day:x=x.groupby('Date',as_index=False).M.mean();return x.Date.astype(str).tolist(),x.M.tolist(),p.get('unit','')
        return [f'Observation {i}<br>{d.strftime("%d-%b-%Y")}' for i,d in enumerate(x.Date,1)],x.M.tolist(),p.get('unit','')
    ids=[p['id'] for p in form['parameters'] if p.get('chart_group')==item[2]['chart_group']];m=x.reindex(columns=ids).apply(pd.to_numeric,errors='coerce');ok=m.notna().sum(1)>=2;x=x[ok];m=m[ok]
    if day:x['M']=m.mean(1).values;x=x.groupby('Date',as_index=False).M.mean();return x.Date.astype(str).tolist(),x.M.tolist(),item[2]['unit']
    return [f'Observation {i}<br>{d.strftime("%d-%b-%Y")}' for i,d in enumerate(x.Date,1)],m.to_numpy(),item[2]['unit']
def choose(prefix):
    dep=st.selectbox('Department',allowed_depts(),key=prefix+'dep');titles=[f['title'] for d,f in flat_forms() if d==dep];return dep,get_form(dep,st.selectbox('Form',titles,key=prefix+'form'))
def entry_page():
    st.subheader('Manual Inspection Entry');dep,form=choose('e')
    with st.form('entry'):
        a,b=st.columns(2);d=a.date_input('Inspection Date');shift=b.selectbox('Shift',SHIFTS);values={};cols=st.columns(3)
        for i,p in enumerate(form.get('metadata',[])+form['parameters']):
            with cols[i%3]:values[p['id']]=widget(p,form['id']+p['id'])
        submit=st.form_submit_button('Save Inspection',type='primary',use_container_width=True)
    if submit:save_record(dep,form,d,shift,values);st.success('Inspection saved successfully.')
def upload_page():
    st.subheader('Excel Upload');dep,form=choose('u');template=ROOT/'excel_templates'/f"{form['id']}.xlsx";st.download_button('Download Excel Template',template.read_bytes(),file_name=template.name,use_container_width=True);up=st.file_uploader('Upload completed Excel',type='xlsx')
    if up and st.button('Import Excel',type='primary'):
        try:
            rows=parse_excel(up,form)
            for d,shift,values in rows:save_record(dep,form,d,shift,values)
            st.success(f'{len(rows)} inspections imported successfully from {up.name}.')
        except Exception as e:st.error(f'Import failed: {e}')
def analysis(day=False):
    st.subheader('Day-wise Analysis' if day else 'Observation-wise Control Charts')
    if day:st.info('One point is shown per date. Subgroups use the daily average of inspection subgroup averages, followed by a daily I-MR chart.')
    _,form=choose('d' if day else 'o');its=items(form);names=[x[1] for x in its];it=its[names.index(st.selectbox('Parameter / Subgroup',names))];start=end=None
    if day:a,b=st.columns(2);start=a.date_input('From Date',date.today().replace(day=1));end=b.date_input('To Date',date.today())
    r=series(form,it,day,start,end)
    if not r:st.warning('No usable readings are available.');return
    x,v,unit=r;calc=xbarr(v) if it[0]=='g' and not day else imr(v)
    if not calc:st.warning('At least two observations or dates are required.');return
    vals,cl,u,l,ranges,rcl,ru,rl=calc;st.plotly_chart(figure(f'{it[1]} - {"Day-wise" if day else "Observation-wise"}',x,vals,cl,u,l,unit),use_container_width=True)
    if not day:st.plotly_chart(figure(it[1]+' - Range',x[1:] if len(x)==len(ranges)+1 else x[:len(ranges)],ranges,rcl,ru,rl,unit),use_container_width=True)
def data_page():
    st.subheader('Data & Specification Limits');x=readings();x=x[(x.Plant.astype(str).eq(st.session_state.plant)) & x.Department.isin(allowed_depts())];st.metric('Stored rows',len(x));st.dataframe(x.tail(300),use_container_width=True,hide_index=True);st.download_button('Download Readings CSV',x.to_csv(index=False).encode(),file_name='quality_readings.csv')
    lim=pd.read_csv(LIMITS);edit=st.data_editor(lim,num_rows='dynamic',use_container_width=True)
    if st.button('Save Specification Limits'):write_csv(LIMITS,edit,'Update limits');st.success('Limits saved.')

if not st.session_state.get('logged'):login_page();st.stop()
with st.sidebar:
    st.success(st.session_state.user['display_name']);st.caption('Plant: '+st.session_state.plant)
    if st.button('Logout',use_container_width=True):st.session_state.clear();st.rerun()
st.markdown('<div class="hero"><h2>Manufacturing SPC & Daily Analysis</h2><div>Observation-wise SPC, one-point-per-day analysis, Excel upload and firing-zone monitoring</div></div>',unsafe_allow_html=True)
page=st.sidebar.radio('Page',['Manual Entry','Excel Upload','Observation-wise Analysis','Day-wise Analysis','Data & Limits'])
{'Manual Entry':entry_page,'Excel Upload':upload_page,'Observation-wise Analysis':lambda:analysis(False),'Day-wise Analysis':lambda:analysis(True),'Data & Limits':data_page}[page]()
