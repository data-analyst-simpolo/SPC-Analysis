import hashlib, io, json, os, re, uuid
from datetime import date, datetime
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import github_store

st.set_page_config(page_title='Manufacturing SPC Portal',page_icon='📈',layout='wide')
ROOT=Path(__file__).parent;CFG=json.loads((ROOT/'config/forms.json').read_text());USERS=json.loads((ROOT/'config/users.json').read_text())['users']
DATA=ROOT/'data/quality_readings.csv';LIMITS=ROOT/'data/spec_limits.csv';PLANTS=['Maliya','Unit 1','Unit 2','Unit 3'];SHIFTS=['A','B','C','General','Not provided']
COLS=['Record ID','Plant','Department','Form ID','Form Title','Inspection Date','Shift','Parameter ID','Parameter','Sample No','Value','Text Value','Unit','Created At']
st.markdown('''<style>.stApp{background:#f5faf6}.block-container{max-width:1450px}.hero,.loginhead{background:linear-gradient(120deg,#102d20,#16803d);color:white;border-radius:20px;padding:1.3rem 1.5rem;margin-bottom:1rem}.card{background:white;border:1px solid #d8e5dc;border-radius:16px;padding:1rem}.kpi{background:#eef8f0;border:1px solid #cce4d1;border-radius:14px;padding:.8rem;text-align:center}.stButton>button,.stDownloadButton>button{border-radius:10px}</style>''',unsafe_allow_html=True)
for k in ('GITHUB_TOKEN','GITHUB_OWNER','GITHUB_REPO','GITHUB_BRANCH'):
    if k in st.secrets:os.environ[k]=str(st.secrets[k])

def allowed():
    d=st.session_state.get('user',{}).get('departments',[]);return list(CFG['departments']) if '*' in d else d
def login():
    st.markdown("<div class='loginhead'><b>MANUFACTURING EXCELLENCE</b><h2>SPC & Daily Analysis Portal</h2><div>Secure plant and department access</div></div>",unsafe_allow_html=True);_,c,_=st.columns([1.2,1,1.2])
    with c:
        with st.form('login'):
            plant=st.selectbox('Plant',PLANTS);dept=st.selectbox('Department',['Plant Administration']+list(CFG['departments']));uid=st.text_input('User ID');pwd=st.text_input('Password',type='password');go=st.form_submit_button('Secure Login',type='primary',use_container_width=True)
        if go:
            u=USERS.get(uid.strip());ok=bool(u) and hashlib.sha256(pwd.encode()).hexdigest()==u['password_sha256'] and plant in u['plants'] and ((dept=='Plant Administration' and u['role']=='admin') or '*' in u['departments'] or dept in u['departments'])
            if ok:st.session_state.logged=True;st.session_state.user=u;st.session_state.plant=plant;st.rerun()
            else:st.error('Invalid login details.')
def read_csv(path,cols):
    remote=github_store.read_text(str(path.relative_to(ROOT)).replace('\\','/'));df=pd.read_csv(io.StringIO(remote)) if remote is not None else pd.read_csv(path)
    for c in cols:
        if c not in df:df[c]=''
    return df[cols]
def save_csv(path,df,msg):
    text=df.to_csv(index=False);path.write_text(text);github_store.write_text(str(path.relative_to(ROOT)).replace('\\','/'),text,msg)
def readings():return read_csv(DATA,COLS)
def limits():return read_csv(LIMITS,['Plant','Department','Form ID','Parameter ID','Parameter','LSL','USL','Target'])
def forms():return [(d,f) for d,v in CFG['departments'].items() for f in v['forms']]
def get_form(d,t):return next(f for dep,f in forms() if dep==d and f['title']==t)
def choose(key):
    d=st.selectbox('Department',allowed(),key=key+'d');titles=[f['title'] for dep,f in forms() if dep==d];return d,get_form(d,st.selectbox('Form',titles,key=key+'f'))
def norm(x):return re.sub('[^a-z0-9]+','',str(x).lower())
def scalar(x):
    if isinstance(x,pd.Series):x=x.dropna();return '' if x.empty else x.iloc[0]
    return x
def time_text(v):
    if hasattr(v,'strftime'):return v.strftime('%H:%M:%S')
    s=re.sub(r'\s+','',str(v)).upper().rstrip('.');s=re.sub(r'(?<=\d)\.(?=\d)',':',s);m=re.fullmatch(r'(\d{1,2}):(\d{2})(AM|PM)?',s)
    if m:
        h,mi,a=m.groups();h=int(h);h=h+12 if a=='PM' and h<12 else 0 if a=='AM' and h==12 else h;return f'{h:02d}:{int(mi):02d}:00'
    return str(v).strip()
def press_rows(upload):
    x=pd.read_excel(upload,sheet_name='Quality Entry',engine='openpyxl').dropna(how='all');x=x.loc[:,~x.columns.astype(str).str.startswith('Unnamed:')];m={}
    aliases={'date':'date','time':'inspection_time','supopename':'supervisor_operator_name','pcrno':'press_number','finalsize':'tile_size','batchnumber':'batch_number','bodycode':'body_code','silonumber':'silo_number','grlengthmm':'green_length_mm','grweidthmm':'green_width_mm','greendiagonal1mm':'green_diagonal_1_mm','greendiagonal2mm':'green_diagonal_2_mm','remarkscommentsifany':'remarks'}
    for i in range(2,14):aliases[norm(f'TH. {i}')]=f'thickness_{i-1}';aliases[norm(f'B.D {i}')]=f'bulk_density_{i-1}'
    aliases['bulkdensity13']='bulk_density_extra_13';aliases['bulkdensity14']='bulk_density_extra_14'
    for c in x:
        target=aliases.get(norm(c))
        if target:m[target]=x[c] if target not in m else m[target].combine_first(x[c])
    x=pd.DataFrame(m);out=[]
    for _,r in x.iterrows():
        d=pd.to_datetime(scalar(r.get('date','')),errors='coerce')
        if pd.isna(d):continue
        meta={k:scalar(r.get(k,'')) for k in ['inspection_time','supervisor_operator_name','press_number','tile_size','batch_number','body_code','silo_number','remarks']};meta['inspection_time']=time_text(meta['inspection_time'])
        th=[pd.to_numeric(scalar(r.get(f'thickness_{i}','')),errors='coerce') for i in range(1,13)];bd=[pd.to_numeric(scalar(r.get(f'bulk_density_{i}','')),errors='coerce') for i in range(1,13)]
        vals={'meta':meta,'single':{k:pd.to_numeric(scalar(r.get(k,'')),errors='coerce') for k in ['green_length_mm','green_width_mm','green_diagonal_1_mm','green_diagonal_2_mm']},'Thickness':th,'Bulk Density':bd};out.append((d.date(),'Not provided',vals))
    return out
def generic_rows(upload,form):
    x=pd.read_excel(upload,sheet_name='Quality Entry',engine='openpyxl').dropna(how='all');aliases={norm('Inspection Date'):'date',norm('Shift'):'shift'}
    for p in form.get('metadata',[])+form['parameters']:aliases[norm(p['label'])]=p['id']
    x=x.rename(columns={c:aliases.get(norm(c),c) for c in x});out=[]
    for _,r in x.iterrows():
        d=pd.to_datetime(scalar(r.get('date','')),errors='coerce')
        if pd.isna(d):continue
        vals={'meta':{},'single':{}}
        for p in form.get('metadata',[]):
            v=scalar(r.get(p['id'],''));vals['meta'][p['id']]=time_text(v) if p['type']=='time' else v
        for p in form['parameters']:
            v=pd.to_numeric(scalar(r.get(p['id'],'')),errors='coerce');vals['single'][p['id']]=v
        out.append((d.date(),str(r.get('shift','Not provided')),vals))
    return out
def append(dep,form,d,shift,payload):
    rid=str(uuid.uuid4());now=datetime.now().isoformat(timespec='seconds');rows=[]
    for p in form.get('metadata',[]):
        v=payload.get('meta',{}).get(p['id'],'')
        if v!='' and not pd.isna(v):rows.append([rid,st.session_state.plant,dep,form['id'],form['title'],d,shift,p['id'],p['label'],'','',v,p.get('unit',''),now])
    for p in form['parameters']:
        if p['type']=='subgroup':
            values=payload.get(p['label'],[])
            for i,v in enumerate(values,1):
                if not pd.isna(v):rows.append([rid,st.session_state.plant,dep,form['id'],form['title'],d,shift,p['id'],p['label'],i,float(v),'',p['unit'],now])
        else:
            v=payload.get('single',{}).get(p['id'],np.nan)
            if not pd.isna(v):rows.append([rid,st.session_state.plant,dep,form['id'],form['title'],d,shift,p['id'],p['label'],'',float(v),'',p.get('unit',''),now])
    save_csv(DATA,pd.concat([readings(),pd.DataFrame(rows,columns=COLS)],ignore_index=True),'Append inspection')
def manual():
    st.subheader('Manual Inspection Entry');dep,form=choose('m')
    with st.form('entry'):
        a,b=st.columns(2);d=a.date_input('Inspection Date');shift=b.selectbox('Shift',SHIFTS);payload={'meta':{},'single':{}}
        for p in form.get('metadata',[]):payload['meta'][p['id']]=st.time_input(p['label'],value=None) if p['type']=='time' else st.text_input(p['label'])
        for p in form['parameters']:
            if p['type']=='subgroup':
                st.markdown(f"#### {p['label']} - 12 samples form one observation");cs=st.columns(6);payload[p['label']]=[cs[(i-1)%6].number_input(f'Sample {i}',value=None,key=p['id']+str(i)) for i in range(1,13)]
            else:payload['single'][p['id']]=st.number_input(p['label'],value=None)
        go=st.form_submit_button('Save Inspection',type='primary',use_container_width=True)
    if go:append(dep,form,d,shift,payload);st.success('Inspection saved.')
def upload():
    st.subheader('Excel Upload');dep,form=choose('u');template=ROOT/'excel_templates'/f"{form['id']}.xlsx";st.download_button('Download exact Excel template',template.read_bytes(),file_name=template.name);up=st.file_uploader('Upload Excel',type='xlsx')
    if up and st.button('Import Excel',type='primary'):
        try:
            rows=press_rows(up) if form['id']=='press_green_tile_thickness_bd' else generic_rows(up,form)
            for d,s,p in rows:append(dep,form,d,s,p)
            st.success(f'{len(rows)} observations imported.')
        except Exception as e:st.error(str(e))
def parameter_data(form,p):
    x=readings();x=x[(x.Plant.eq(st.session_state.plant))&(x['Form ID'].eq(form['id']))&(x['Parameter ID'].eq(p['id']))].copy();x['Date']=pd.to_datetime(x['Inspection Date']).dt.date;x['Value']=pd.to_numeric(x['Value'],errors='coerce');return x.dropna(subset=['Value']).sort_values(['Date','Created At','Record ID','Sample No'])
def xbarr(a):
    a=np.asarray(a,float);means=a.mean(1);ranges=a.max(1)-a.min(1);xb=means.mean();rb=ranges.mean();a2,d3,d4=.266,.284,1.716;return means,xb,xb+a2*rb,xb-a2*rb,ranges,rb,d4*rb,d3*rb,rb/3.258
def imr(v):
    x=pd.Series(v,dtype=float);mr=x.diff().abs().dropna();m=mr.mean();cl=x.mean();return x,cl,cl+2.66*m,cl-2.66*m,mr,m,3.267*m,0,m/1.128
def plot(title,labels,v,cl,u,l,unit):
    f=go.Figure(go.Scatter(x=labels,y=v,mode='lines+markers',line=dict(color='#16803d',width=2.5)));f.add_hline(y=u,line_dash='dash',line_color='#c43d32',annotation_text=f'UCL {u:.3f}');f.add_hline(y=cl,line_dash='dot',line_color='#2563eb',annotation_text=f'CL {cl:.3f}');f.add_hline(y=l,line_dash='dash',line_color='#c43d32',annotation_text=f'LCL {l:.3f}');f.update_layout(title=title,xaxis_title='Observation / Inspection Date',yaxis_title=unit,height=430,margin=dict(b=100));f.update_xaxes(tickangle=-45);return f
def analysis(day=False):
    st.subheader('Day-wise Analysis' if day else 'Observation-wise SPC & Capability');dep,form=choose('a'+str(day));p=next(x for x in form['parameters'] if x['label']==st.selectbox('Parameter', [x['label'] for x in form['parameters']]))
    x=parameter_data(form,p)
    if x.empty:st.warning('No data.');return
    if p['type']=='subgroup':
        piv=x.pivot_table(index=['Record ID','Date'],columns='Sample No',values='Value',aggfunc='first');piv=piv.dropna(thresh=2);means=piv.mean(1)
        if day:
            daily=means.groupby(level='Date').mean();calc=imr(daily.values);labels=[str(d) for d in daily.index];method='Daily I-MR of average subgroup averages'
        else:
            full=piv.dropna();
            if len(full)<2:st.warning('At least two complete 12-sample observations are required.');return
            calc=xbarr(full.values);labels=[f'Observation {i}<br>{idx[1].strftime("%d-%b-%Y")}' for i,idx in enumerate(full.index,1)];method='X-bar R (n=12)'
    else:
        if day:x=x.groupby('Date',as_index=False).Value.mean();labels=x.Date.astype(str).tolist()
        else:labels=[f'Observation {i}<br>{d.strftime("%d-%b-%Y")}' for i,d in enumerate(x.Date,1)]
        calc=imr(x.Value.values);method='I-MR'
    if calc is None or len(calc[0])<2:st.warning('At least two observations/dates are required.');return
    vals,cl,u,l,ranges,rcl,ru,rl,sigma=calc;st.caption(method)
    saved=limits();saved=saved[(saved.Plant.eq(st.session_state.plant))&(saved['Form ID'].eq(form['id']))&(saved['Parameter ID'].eq(p['id']))]
    default_lsl=None if saved.empty or pd.isna(pd.to_numeric(saved.iloc[-1]['LSL'],errors='coerce')) else float(saved.iloc[-1]['LSL'])
    default_usl=None if saved.empty or pd.isna(pd.to_numeric(saved.iloc[-1]['USL'],errors='coerce')) else float(saved.iloc[-1]['USL'])
    c1,c2=st.columns(2);lsl=c1.number_input('LSL',value=default_lsl);usl=c2.number_input('USL',value=default_usl)
    if lsl is not None and usl is not None and sigma>0:
        cp=(usl-lsl)/(6*sigma);cpk=min((usl-cl)/(3*sigma),(cl-lsl)/(3*sigma));a,b,c=st.columns(3);a.metric('Cp',f'{cp:.3f}');b.metric('Cpk',f'{cpk:.3f}');c.metric('Process Mean',f'{cl:.3f}')
        lim=limits();row={'Plant':st.session_state.plant,'Department':dep,'Form ID':form['id'],'Parameter ID':p['id'],'Parameter':p['label'],'LSL':lsl,'USL':usl,'Target':(lsl+usl)/2};lim=lim[~((lim.Plant.eq(row['Plant']))&(lim['Form ID'].eq(form['id']))&(lim['Parameter ID'].eq(p['id'])))];save_csv(LIMITS,pd.concat([lim,pd.DataFrame([row])],ignore_index=True),'Update specification limits')
    st.plotly_chart(plot(p['label'],labels,vals,cl,u,l,p['unit']),use_container_width=True)
    if not day:st.plotly_chart(plot(p['label']+' Range',labels[1:] if len(labels)==len(ranges)+1 else labels[:len(ranges)],ranges,rcl,ru,rl,p['unit']),use_container_width=True)
def data_page():
    x=readings();x=x[(x.Plant.eq(st.session_state.plant))&x.Department.isin(allowed())];st.dataframe(x.tail(500),use_container_width=True);st.download_button('Download data',x.to_csv(index=False).encode(),file_name='quality_readings.csv')

if not st.session_state.get('logged'):login();st.stop()
with st.sidebar:
    st.success(st.session_state.user['display_name']);st.caption('Plant: '+st.session_state.plant)
    if st.button('Logout'):st.session_state.clear();st.rerun()
st.markdown('<div class="hero"><h2>Manufacturing SPC & Daily Analysis</h2><div>Subgroup control charts, process capability, daily averages and Excel upload</div></div>',unsafe_allow_html=True)
page=st.sidebar.radio('Page',['Manual Entry','Excel Upload','Observation-wise Analysis','Day-wise Analysis','Data'])
{'Manual Entry':manual,'Excel Upload':upload,'Observation-wise Analysis':lambda:analysis(False),'Day-wise Analysis':lambda:analysis(True),'Data':data_page}[page]()
