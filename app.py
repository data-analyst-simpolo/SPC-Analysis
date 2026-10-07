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
CONFIG=json.loads((ROOT/'config/forms.json').read_text(encoding='utf-8'))
USERS=json.loads((ROOT/'config/users.json').read_text(encoding='utf-8'))['users']
DATA_PATH=ROOT/'data/quality_readings.csv'; LIMITS_PATH=ROOT/'data/spec_limits.csv'
COLS=['Record ID','Plant','Department','Form ID','Form Title','Inspection Date','Shift','Parameter ID','Parameter','Value','Text Value','Unit','Created At']
SHIFTS=['A','B','C','General','Not provided']
st.markdown('''<style>.stApp{background:#f6faf7}.block-container{max-width:1450px;padding-top:1rem}.hero{background:linear-gradient(115deg,#102c20,#16803d);color:white;padding:1.2rem 1.5rem;border-radius:18px;margin-bottom:1rem}.login-head{background:linear-gradient(115deg,#102c20,#16803d);color:white;padding:1.25rem;border-radius:20px;margin-bottom:1rem}.login-card{background:white;border:1px solid #d6e5da;border-radius:22px;padding:1.2rem;box-shadow:0 18px 42px rgba(16,44,32,.12)}</style>''',unsafe_allow_html=True)
for k in ('GITHUB_TOKEN','GITHUB_OWNER','GITHUB_REPO','GITHUB_BRANCH'):
    if k in st.secrets:os.environ[k]=str(st.secrets[k])

def departments():
    ds=st.session_state.get('user',{}).get('departments',[])
    return list(CONFIG['departments']) if '*' in ds else [d for d in ds if d in CONFIG['departments']]

def login():
    st.markdown("<div class='login-head'><div style='font-size:12px;font-weight:800;letter-spacing:1px'>MANUFACTURING EXCELLENCE</div><h1 style='margin:.35rem 0'>SPC & Daily Analysis Portal</h1><div>Secure plant and department access</div></div>",unsafe_allow_html=True)
    _,c,_=st.columns([1.2,1,1.2])
    with c:
        st.markdown("<div class='login-card'>",unsafe_allow_html=True)
        with st.form('login'):
            plant=st.selectbox('Plant',['Maliya']);dept=st.selectbox('Department',['Plant Administration']+list(CONFIG['departments']))
            username=st.text_input('Username');password=st.text_input('Password',type='password');go=st.form_submit_button('Secure Login',type='primary',use_container_width=True)
        st.markdown('</div>',unsafe_allow_html=True)
        if go:
            u=USERS.get(username.strip());ok=u and hashlib.sha256(password.encode()).hexdigest()==u['password_sha256'] and plant==u['plant']
            if ok and dept=='Plant Administration':ok=u['role']=='admin'
            if ok and dept!='Plant Administration':ok='*' in u['departments'] or dept in u['departments']
            if ok:st.session_state.logged=True;st.session_state.user=u;st.rerun()
            else:st.error('Invalid plant, department, username or password.')
        st.caption('Change the default passwords in config/users.json before deployment.')

def read_csv(path,columns):
    remote=github_store.read_text(str(path.relative_to(ROOT)).replace('\\','/'))
    if remote is not None:df=pd.read_csv(io.StringIO(remote))
    elif path.exists():df=pd.read_csv(path)
    else:df=pd.DataFrame(columns=columns)
    for c in columns:
        if c not in df:df[c]=''
    return df[columns]
def write_csv(path,df,msg):
    text=df.to_csv(index=False);path.write_text(text,encoding='utf-8');github_store.write_text(str(path.relative_to(ROOT)).replace('\\','/'),text,msg)
def readings():return read_csv(DATA_PATH,COLS)
def forms():return [(d,f) for d,x in CONFIG['departments'].items() for f in x['forms']]
def get_form(d,t):return next(f for dep,f in forms() if dep==d and f['title']==t)
def norm(x):return re.sub(r'[^a-z0-9]+','',str(x).lower())

def save_record(dep,form,d,shift,values):
    rid=str(uuid.uuid4());now=datetime.now().isoformat(timespec='seconds');rows=[]
    for p in form.get('metadata',[])+form['parameters']:
        v=values.get(p['id'])
        if v is None or v=='':continue
        rows.append({'Record ID':rid,'Plant':'Maliya','Department':dep,'Form ID':form['id'],'Form Title':form['title'],'Inspection Date':str(d),'Shift':shift,'Parameter ID':p['id'],'Parameter':p['label'],'Value':v if p['type']=='number' else '','Text Value':v.strftime('%H:%M:%S') if p['type']=='time' else ('' if p['type']=='number' else str(v)),'Unit':p.get('unit',''),'Created At':now})
    write_csv(DATA_PATH,pd.concat([readings(),pd.DataFrame(rows)],ignore_index=True),'Append SPC inspection')

def widget(p,key):
    if p['type']=='number':return st.number_input(p['label'],value=None,key=key)
    if p['type']=='time':return st.time_input(p['label'],value=None,key=key)
    return st.text_input(p['label'],key=key)

def first_scalar(value):
    """Return one safe scalar even when pandas yields duplicate-column Series."""
    if isinstance(value, pd.Series):
        non_blank = value.dropna()
        return '' if non_blank.empty else non_blank.iloc[0]
    return value


def clean_excel_time(value):
    """Preserve Press time nomenclature while normalising common formats."""
    value = first_scalar(value)
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%H:%M:%S')
    raw = re.sub(r'\s+', '', str(value).strip()).upper()
    raw = raw.rstrip('.')
    # Operator files use variants such as 10.30AM., 10.06PM and 04:40 AM.
    raw = re.sub(r'(?<=\d)[.](?=\d)', ':', raw)
    match = re.fullmatch(r'(\d{1,2}):(\d{2})(?::(\d{2}))?(AM|PM)?', raw)
    if match:
        hour, minute, second, suffix = match.groups()
        hour, minute, second = int(hour), int(minute), int(second or 0)
        if suffix == 'PM' and hour < 12: hour += 12
        if suffix == 'AM' and hour == 12: hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59:
            return f'{hour:02d}:{minute:02d}:{second:02d}'
    parsed = pd.to_datetime(raw, errors='coerce')
    return str(value).strip() if pd.isna(parsed) else parsed.strftime('%H:%M:%S')


def parse_excel(up,form):
    # Read the operator workbook exactly as supplied. Blank spacer columns are
    # ignored, and duplicate-looking Press headers are mapped to distinct IDs.
    x=pd.read_excel(up,sheet_name='Quality Entry',engine='openpyxl').dropna(how='all')
    x=x.loc[:,~x.columns.astype(str).str.startswith('Unnamed:')]
    aliases={norm('Inspection Date'):'Inspection Date',norm('Shift'):'Shift'}
    for p in form.get('metadata',[])+form['parameters']:
        aliases[norm(p['label'])]=p['id']
    extras={
        'date':'Inspection Date','time':'inspection_time','supopename':'supervisor_operator_name',
        'pcrno':'press_number','finalsize':'tile_size','batchnumber':'batch_number',
        'bodycode':'body_code','silonumber':'silo_number','grlengthmm':'green_length_mm',
        'grweidthmm':'green_width_mm','greenwidthmm':'green_width_mm',
        'greendiagonal1mm':'green_diagonal_1_mm','greendiagonal2mm':'green_diagonal_2_mm',
        'bulkdensity13':'bulk_density_13_extra','bulkdensity14':'bulk_density_14',
        'remarkscommentsifany':'remarks'
    }
    for i in range(2,14):
        extras[norm(f'TH. {i}')]=f'thickness_{i}'
        extras[norm(f'B.D {i}')]=f'bulk_density_{i}'
    aliases.update(extras)

    # Build a new dataframe column by column instead of rename().  This avoids
    # duplicate canonical labels, the cause of the "truth value of a Series is
    # ambiguous" error when B.D 13 and Bulk Density 13 are both present.
    mapped={}
    for original in x.columns:
        target=aliases.get(norm(original))
        if not target:
            continue
        series=x[original]
        if isinstance(series,pd.DataFrame):
            series=series.bfill(axis=1).iloc[:,0]
        if target in mapped:
            mapped[target]=mapped[target].combine_first(series)
        else:
            mapped[target]=series
    x=pd.DataFrame(mapped,index=x.index)
    if 'Inspection Date' not in x.columns:
        raise ValueError('Inspection Date / Date is required.')

    field_map={p['id']:p for p in form.get('metadata',[])+form['parameters']}
    out=[];skipped=[]
    for row_no,(_,r) in enumerate(x.iterrows(),start=2):
        raw_date=first_scalar(r.get('Inspection Date',''))
        d=pd.to_datetime(raw_date,errors='coerce')
        if pd.isna(d):
            skipped.append(row_no);continue
        shift_value=first_scalar(r.get('Shift','Not provided'))
        shift='Not provided' if shift_value is None or pd.isna(shift_value) or not str(shift_value).strip() else str(shift_value).strip()
        if shift not in SHIFTS:shift='Not provided'
        vals={}
        for pid,pdef in field_map.items():
            if pid not in x.columns:continue
            value=first_scalar(r.get(pid,''))
            if value is None or (not isinstance(value,(list,tuple,dict)) and pd.isna(value)) or value=='':continue
            if pid=='inspection_time':
                value=clean_excel_time(value)
            elif pdef['type']=='number':
                numeric=pd.to_numeric(value,errors='coerce')
                if pd.isna(numeric):continue
                value=float(numeric)
            else:
                value=str(value).strip().replace('\\*','*')
            vals[pid]=value
        out.append((d.date(),shift,vals))
    if not out:
        raise ValueError('No valid inspection rows were found in the Excel file.')
    return out

def wide(form):
    x=readings();x=x[x['Form ID'].eq(form['id'])]
    if x.empty:return pd.DataFrame()
    b=x.groupby('Record ID').first()[['Inspection Date','Shift','Created At']]
    n=x.assign(N=pd.to_numeric(x['Value'],errors='coerce')).pivot_table(index='Record ID',columns='Parameter ID',values='N',aggfunc='first')
    t=x.pivot_table(index='Record ID',columns='Parameter ID',values='Text Value',aggfunc='first')
    return b.join(n,rsuffix='_n').join(t,rsuffix='_t').reset_index()
def imr(v):
    x=pd.Series(v,dtype=float).dropna().reset_index(drop=True)
    if len(x)<2:return None
    mr=x.diff().abs().dropna();m=mr.mean();cl=x.mean();return x,cl,cl+2.66*m,cl-2.66*m,mr,m,3.267*m,0
def xbarr(mat):
    a=np.array(mat,float);a=a[~np.isnan(a).all(1)]
    if len(a)<2:return None
    means=np.nanmean(a,1);ranges=np.nanmax(a,1)-np.nanmin(a,1);n=int(np.nanmedian(np.sum(~np.isnan(a),1)));k={8:(.373,.136,1.864),12:(.266,.284,1.716)};a2,d3,d4=k[8 if n<=8 else 12];xb=means.mean();rb=ranges.mean();return means,xb,xb+a2*rb,xb-a2*rb,ranges,rb,d4*rb,d3*rb
def fig(title,x,y,cl,u,l,unit):
    f=go.Figure(go.Scatter(x=x,y=y,mode='lines+markers',line=dict(color='#166534',width=2),marker=dict(size=7)))
    for v,n,c,d in [(u,'UCL','#b42318','dash'),(cl,'CL','#2563eb','dot'),(l,'LCL','#b42318','dash')]:f.add_hline(y=v,line_color=c,line_dash=d,annotation_text=f'{n}: {v:.2f}')
    f.update_layout(title=title,xaxis_title='Observation / Inspection Date',yaxis_title=unit,height=430,margin=dict(b=95));f.update_xaxes(tickangle=-45,automargin=True);return f

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

def entry():
    st.subheader('Manual Inspection Entry');dep=st.selectbox('Department',departments());ts=[f['title'] for d,f in forms() if d==dep];form=get_form(dep,st.selectbox('Form',ts))
    with st.form('entry'):
        a,b=st.columns(2);d=a.date_input('Inspection Date');shift=b.selectbox('Shift',SHIFTS);vals={};cs=st.columns(3)
        for i,p in enumerate(form.get('metadata',[])+form['parameters']):
            with cs[i%3]:vals[p['id']]=widget(p,p['id'])
        go=st.form_submit_button('Save Inspection',type='primary',use_container_width=True)
    if go:save_record(dep,form,d,shift,vals);st.success('Inspection saved.')
def upload():
    st.subheader('Excel Upload');dep=st.selectbox('Department',departments());ts=[f['title'] for d,f in forms() if d==dep];form=get_form(dep,st.selectbox('Form',ts));template=ROOT/'excel_templates'/f"{form['id']}.xlsx";st.download_button('Download Excel Template',template.read_bytes(),file_name=template.name);up=st.file_uploader('Upload completed Excel',type='xlsx')
    if up and st.button('Import'):
        rows=parse_excel(up,form)
        for d,sh,v in rows:save_record(dep,form,d,sh,v)
        st.success(f'{len(rows)} inspections imported.')
def analysis(day=False):
    st.subheader('Day-wise Analysis' if day else 'Observation-wise Control Charts')
    if day:st.info('Exactly one point per date. Subgrouped parameters use the average of subgroup averages for that date; daily I-MR is used.')
    dep=st.selectbox('Department',departments());ts=[f['title'] for d,f in forms() if d==dep];form=get_form(dep,st.selectbox('Form',ts));its=items(form);labels=[i[1] for i in its];it=its[labels.index(st.selectbox('Parameter / Subgroup',labels))];start=end=None
    if day:a,b=st.columns(2);start=a.date_input('From Date',date.today().replace(day=1));end=b.date_input('To Date',date.today())
    r=series(form,it,day,start,end)
    if not r:st.warning('No data.');return
    x,v,unit=r;calc=xbarr(v) if it[0]=='g' and not day else imr(v)
    if not calc:st.warning('At least two observations/dates are required.');return
    vals,cl,u,l,ranges,rcl,ru,rl=calc;st.plotly_chart(fig(f'{it[1]} - {"Day-wise" if day else "Observation-wise"}',x,vals,cl,u,l,unit),use_container_width=True)
    if not day:st.plotly_chart(fig(f'{it[1]} - Range',x[1:] if len(x)==len(ranges)+1 else x[:len(ranges)],ranges,rcl,ru,rl,unit),use_container_width=True)
def data_page():
    st.subheader('Data & Limits');x=readings();x=x[x.Department.isin(departments())];st.dataframe(x.tail(300),use_container_width=True);st.download_button('Download Readings',x.to_csv(index=False).encode(),file_name='quality_readings.csv')
    lim=pd.read_csv(LIMITS_PATH);edit=st.data_editor(lim,num_rows='dynamic',use_container_width=True)
    if st.button('Save Limits'):write_csv(LIMITS_PATH,edit,'Update limits');st.success('Saved.')

if not st.session_state.get('logged'):login();st.stop()
with st.sidebar:
    st.success(st.session_state.user['display_name']);st.caption('Plant: '+st.session_state.user['plant'])
    if st.button('Logout',use_container_width=True):st.session_state.clear();st.rerun()
st.markdown('<div class="hero"><h2>Manufacturing SPC & Daily Analysis</h2><div>Observation-wise charts, one-point-per-day analysis, Excel uploads and firing-zone monitoring</div></div>',unsafe_allow_html=True)
page=st.sidebar.radio('Page',['Manual Entry','Excel Upload','Observation-wise Analysis','Day-wise Analysis','Data & Limits'])
{'Manual Entry':entry,'Excel Upload':upload,'Observation-wise Analysis':lambda:analysis(False),'Day-wise Analysis':lambda:analysis(True),'Data & Limits':data_page}[page]()
