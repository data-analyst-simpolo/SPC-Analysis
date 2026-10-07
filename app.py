import io, json, os, re, uuid
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
DATA_PATH=ROOT/'data/quality_readings.csv'; LIMITS_PATH=ROOT/'data/spec_limits.csv'
DATA_COLUMNS=['Record ID','Plant','Department','Form ID','Form Title','Inspection Date','Shift','Parameter ID','Parameter','Value','Text Value','Unit','Created At']
SHIFTS=['A','B','C','General','Not provided']

st.markdown('''<style>.stApp{background:#f6faf7}.block-container{max-width:1450px;padding-top:1rem}.hero{background:linear-gradient(115deg,#102c20,#16803d);color:white;padding:1.2rem 1.5rem;border-radius:18px;margin-bottom:1rem}.soft{background:white;border:1px solid #d7e5db;border-radius:14px;padding:1rem}.small{color:#63756b;font-size:.85rem}</style>''',unsafe_allow_html=True)

def sync_env():
    for k in ('GITHUB_TOKEN','GITHUB_OWNER','GITHUB_REPO','GITHUB_BRANCH'):
        if k in st.secrets: os.environ[k]=str(st.secrets[k])
sync_env()

def read_csv(path,columns):
    remote=github_store.read_text(str(path.relative_to(ROOT)).replace('\\','/'))
    if remote is not None:
        df=pd.read_csv(io.StringIO(remote))
    elif path.exists() and path.stat().st_size:
        df=pd.read_csv(path)
    else: df=pd.DataFrame(columns=columns)
    for c in columns:
        if c not in df.columns:df[c]=''
    return df[columns]

def write_csv(path,df,message):
    text=df.to_csv(index=False)
    path.parent.mkdir(exist_ok=True);path.write_text(text,encoding='utf-8')
    if github_store.configured():github_store.write_text(str(path.relative_to(ROOT)).replace('\\','/'),text,message)

def readings(): return read_csv(DATA_PATH,DATA_COLUMNS)
def limits(): return read_csv(LIMITS_PATH,['Department','Form ID','Parameter ID','LSL','USL','Target'])
def forms_flat():
    out=[]
    for dep,dc in CONFIG['departments'].items():
        for f in dc['forms']:out.append((dep,f))
    return out

def get_form(dep,title):return next(f for d,f in forms_flat() if d==dep and f['title']==title)
def normalize(s):return re.sub(r'[^a-z0-9]+','',str(s).lower())

def append_record(dep,form,inspection_date,shift,values):
    rid=str(uuid.uuid4());created=datetime.now().isoformat(timespec='seconds');rows=[]
    fields=form.get('metadata',[])+form.get('parameters',[])
    for p in fields:
        value=values.get(p['id'],'')
        if value is None or value=='':continue
        numeric=value if p['type']=='number' else ''
        text=value.strftime('%H:%M:%S') if p['type']=='time' and hasattr(value,'strftime') else ('' if p['type']=='number' else str(value))
        rows.append({'Record ID':rid,'Plant':'Maliya','Department':dep,'Form ID':form['id'],'Form Title':form['title'],'Inspection Date':str(inspection_date),'Shift':shift,'Parameter ID':p['id'],'Parameter':p['label'],'Value':numeric,'Text Value':text,'Unit':p.get('unit',''),'Created At':created})
    old=readings();new=pd.concat([old,pd.DataFrame(rows)],ignore_index=True)
    write_csv(DATA_PATH,new,'Append SPC inspection')
    return rid

def field_widget(p,key):
    if p['type']=='number':return st.number_input(p['label'],value=None,key=key)
    if p['type']=='time':return st.time_input(p['label'],value=None,key=key)
    return st.text_input(p['label'],key=key)

def parse_excel(upload,dep,form):
    df=pd.read_excel(upload,sheet_name='Quality Entry',engine='openpyxl').dropna(how='all')
    aliases={normalize('Inspection Date'):'Inspection Date',normalize('Shift'):'Shift'}
    for p in form.get('metadata',[])+form.get('parameters',[]):aliases[normalize(p['label'])]=p['id']
    # operational Press nomenclature aliases
    extras={'date':'Inspection Date','time':'inspection_time','supopename':'supervisor_operator_name','pcrno':'press_number','finalsize':'tile_size','batchnumber':'batch_number','bodycode':'body_code','silonumber':'silo_number','grlengthmm':'green_length_mm','grweidthmm':'green_width_mm','greendiagonal1mm':'green_diagonal_1_mm','greendiagonal2mm':'green_diagonal_2_mm'}
    for i in range(2,14):extras[normalize(f'TH. {i}')]=f'thickness_{i}';extras[normalize(f'B.D {i}')]=f'bulk_density_{i}'
    aliases.update(extras)
    df=df.rename(columns={c:aliases.get(normalize(c),c) for c in df.columns})
    if 'Inspection Date' not in df.columns:raise ValueError('Inspection Date / Date column is required.')
    result=[]
    for _,r in df.iterrows():
        d=pd.to_datetime(r['Inspection Date'],errors='coerce')
        if pd.isna(d):continue
        shift=str(r.get('Shift','Not provided')).strip() if not pd.isna(r.get('Shift','Not provided')) else 'Not provided'
        values={}
        for p in form.get('metadata',[])+form.get('parameters',[]):
            if p['id'] in df.columns and not pd.isna(r.get(p['id'])):values[p['id']]=r[p['id']]
        result.append((d.date(),shift if shift in SHIFTS else 'Not provided',values))
    return result

def record_wide(df,form):
    part=df[df['Form ID'].astype(str).eq(form['id'])].copy()
    if part.empty:return pd.DataFrame()
    base=part.groupby('Record ID',as_index=False).first()[['Record ID','Inspection Date','Shift','Created At']]
    numeric=part.assign(Numeric=pd.to_numeric(part['Value'],errors='coerce')).pivot_table(index='Record ID',columns='Parameter ID',values='Numeric',aggfunc='first')
    text=part.pivot_table(index='Record ID',columns='Parameter ID',values='Text Value',aggfunc='first')
    return base.set_index('Record ID').join(numeric,rsuffix='_num').join(text,rsuffix='_text').reset_index()

def imr(values):
    x=pd.Series(values,dtype=float).dropna().reset_index(drop=True)
    if len(x)<2:return None
    mr=x.diff().abs().dropna();mrbar=mr.mean();cl=x.mean();ucl=cl+2.66*mrbar;lcl=cl-2.66*mrbar
    return x,cl,ucl,lcl,mr,mrbar,3.267*mrbar,0.0

def xbar_r(matrix):
    m=np.array(matrix,dtype=float);m=m[~np.isnan(m).all(axis=1)]
    if len(m)<2:return None
    means=np.nanmean(m,axis=1);ranges=np.nanmax(m,axis=1)-np.nanmin(m,axis=1);n=int(np.nanmedian(np.sum(~np.isnan(m),axis=1)))
    constants={2:(1.880,0,3.267),3:(1.023,0,2.574),4:(.729,0,2.282),5:(.577,0,2.114),6:(.483,0,2.004),7:(.419,.076,1.924),8:(.373,.136,1.864),9:(.337,.184,1.816),10:(.308,.223,1.777),11:(.285,.256,1.744),12:(.266,.284,1.716)}
    a2,d3,d4=constants.get(n,constants[12]);xb=means.mean();rb=ranges.mean()
    return means,xb,xb+a2*rb,xb-a2*rb,ranges,rb,d4*rb,d3*rb

def chart(fig_title,x,y,cl,ucl,lcl,ytitle,hover=None):
    fig=go.Figure();fig.add_trace(go.Scatter(x=x,y=y,mode='lines+markers',name='Value',line=dict(color='#166534',width=2),marker=dict(size=7),text=hover,hovertemplate='%{text}<br>Value: %{y:.3f}<extra></extra>' if hover else None))
    for val,name,color,dash in [(ucl,'UCL','#b42318','dash'),(cl,'CL','#2563eb','dot'),(lcl,'LCL','#b42318','dash')]:fig.add_hline(y=val,line_color=color,line_dash=dash,annotation_text=f'{name}: {val:.3f}')
    fig.update_layout(title=fig_title,xaxis_title='Observation / Inspection Date',yaxis_title=ytitle,height=430,hovermode='x unified',margin=dict(t=70,b=85))
    fig.update_xaxes(tickangle=-45,automargin=True)
    return fig

def selection_items(form):
    items=[];groups=[]
    for p in form['parameters']:
        g=p.get('chart_group')
        if g and g not in groups:groups.append(g)
        if not g:items.append(('parameter',p['label'],p))
    for g in groups:items.append(('group',g,{'chart_group':g,'label':g,'unit':next(p.get('unit','') for p in form['parameters'] if p.get('chart_group')==g)}))
    return items

def series_for(form,item,daywise=False,start=None,end=None):
    df=readings();wide=record_wide(df,form)
    if wide.empty:return None
    wide['Date']=pd.to_datetime(wide['Inspection Date'],errors='coerce').dt.date
    wide['Created']=pd.to_datetime(wide['Created At'],errors='coerce');wide=wide.sort_values(['Date','Created','Record ID'])
    if start:wide=wide[wide['Date']>=start]
    if end:wide=wide[wide['Date']<=end]
    kind,_,obj=item
    if kind=='parameter':
        pid=obj['id'];wide['Metric']=pd.to_numeric(wide.get(pid),errors='coerce');wide=wide.dropna(subset=['Metric'])
        if daywise:
            daily=wide.groupby('Date',as_index=False)['Metric'].mean();return daily['Date'].astype(str).tolist(),daily['Metric'].tolist(),None,obj.get('unit',''),'Daily average'
        labels=[f'Observation {i}<br>{d.strftime("%d-%b-%Y")}' for i,d in enumerate(wide['Date'],1)]
        hover=[f'Observation: {i}<br>Date: {d.strftime("%d-%b-%Y")}<br>Time: {t if pd.notna(t) else ""}' for i,(d,t) in enumerate(zip(wide['Date'],wide.get('inspection_time',pd.Series(['']*len(wide)))),1)]
        return labels,wide['Metric'].tolist(),hover,obj.get('unit',''),'I-MR'
    ids=[p['id'] for p in form['parameters'] if p.get('chart_group')==obj['chart_group']]
    matrix=wide.reindex(columns=ids).apply(pd.to_numeric,errors='coerce')
    valid=matrix.notna().sum(axis=1)>=2;wide=wide[valid].copy();matrix=matrix[valid]
    if daywise:
        wide['Subgroup Average']=matrix.mean(axis=1).values
        daily=wide.groupby('Date',as_index=False)['Subgroup Average'].mean()
        return daily['Date'].astype(str).tolist(),daily['Subgroup Average'].tolist(),None,obj.get('unit',''),'Daily average of subgroup averages'
    labels=[f'Observation {i}<br>{d.strftime("%d-%b-%Y")}' for i,d in enumerate(wide['Date'],1)]
    return labels,matrix.to_numpy(),None,obj.get('unit',''),'Xbar-R'

def analysis_page(daywise=False):
    st.subheader('Day-wise Analysis' if daywise else 'Observation-wise Control Charts')
    if daywise:st.info('One point is plotted per selected date. For subgrouped fields, the point is the average of each inspection subgroup average. A daily I-MR chart is used because there is one aggregated value per day.')
    deps=list(CONFIG['departments']);dep=st.selectbox('Department',deps,key='ad_dep'+str(daywise));titles=[f['title'] for d,f in forms_flat() if d==dep];title=st.selectbox('Form',titles,key='ad_form'+str(daywise));form=get_form(dep,title)
    items=selection_items(form);names=[x[1] for x in items];choice=st.selectbox('Parameter / Subgroup',names,key='ad_item'+str(daywise));item=items[names.index(choice)]
    start=end=None
    if daywise:
        c1,c2=st.columns(2);start=c1.date_input('From Date',value=date.today().replace(day=1),key='from');end=c2.date_input('To Date',value=date.today(),key='to')
    result=series_for(form,item,daywise,start,end)
    if not result:st.warning('No usable readings are available.');return
    labels,values,hover,unit,method=result
    if item[0]=='group' and not daywise:
        calc=xbar_r(values)
    else:calc=imr(values)
    if not calc:st.warning('At least two observations/dates are required.');return
    vals,cl,ucl,lcl,ranges,rcl,rucl,rlcl=calc
    st.caption(f'Chart method: {method}')
    st.plotly_chart(chart(f'{choice} - {"Day-wise" if daywise else "Observation-wise"}',labels,vals,cl,ucl,lcl,unit,hover),use_container_width=True)
    if not daywise:
        rlabels=labels[1:] if len(labels)==len(ranges)+1 else labels[:len(ranges)]
        st.plotly_chart(chart(f'{choice} - Moving Range / Subgroup Range',rlabels,ranges,rcl,rucl,rlcl,unit),use_container_width=True)

def entry_page():
    st.subheader('Manual Inspection Entry')
    dep=st.selectbox('Department',list(CONFIG['departments']),key='e_dep');titles=[f['title'] for d,f in forms_flat() if d==dep];form=get_form(dep,st.selectbox('Form',titles,key='e_form'))
    with st.form('entry'):
        c1,c2=st.columns(2);d=c1.date_input('Inspection Date');shift=c2.selectbox('Shift',SHIFTS)
        values={};fields=form.get('metadata',[])+form.get('parameters',[]);cols=st.columns(3)
        for i,p in enumerate(fields):
            with cols[i%3]:values[p['id']]=field_widget(p,f"{form['id']}_{p['id']}")
        submit=st.form_submit_button('Save Inspection',type='primary',use_container_width=True)
    if submit:
        rid=append_record(dep,form,d,shift,values);st.success(f'Inspection saved. Record ID: {rid}')

def upload_page():
    st.subheader('Excel Upload')
    dep=st.selectbox('Department',list(CONFIG['departments']),key='u_dep');titles=[f['title'] for d,f in forms_flat() if d==dep];form=get_form(dep,st.selectbox('Form',titles,key='u_form'))
    template=ROOT/'excel_templates'/f"{form['id']}.xlsx"
    st.download_button('Download Excel Template',template.read_bytes(),file_name=template.name)
    upload=st.file_uploader('Upload completed Excel',type=['xlsx'])
    if upload and st.button('Import Excel',type='primary'):
        try:
            parsed=parse_excel(upload,dep,form)
            for d,shift,values in parsed:append_record(dep,form,d,shift,values)
            st.success(f'{len(parsed)} inspections imported.')
        except Exception as e:st.error(str(e))

def data_page():
    st.subheader('Data & Specification Limits')
    df=readings();st.metric('Stored parameter rows',len(df));st.dataframe(df.tail(200),use_container_width=True,hide_index=True)
    st.download_button('Download All Readings CSV',df.to_csv(index=False).encode(),file_name='quality_readings.csv')
    st.divider();st.write('Specification limits')
    lim=limits();edit=st.data_editor(lim,num_rows='dynamic',use_container_width=True)
    if st.button('Save Specification Limits'):
        write_csv(LIMITS_PATH,edit,'Update SPC specification limits');st.success('Specification limits saved.')

st.markdown('<div class="hero"><h2>Manufacturing SPC & Daily Analysis</h2><div>Observation-wise control charts, day-wise averages, Excel upload and firing-zone temperature monitoring</div></div>',unsafe_allow_html=True)
page=st.sidebar.radio('Page',['Manual Entry','Excel Upload','Observation-wise Analysis','Day-wise Analysis','Data & Limits'])
if page=='Manual Entry':entry_page()
elif page=='Excel Upload':upload_page()
elif page=='Observation-wise Analysis':analysis_page(False)
elif page=='Day-wise Analysis':analysis_page(True)
else:data_page()
