import base64, io, json, re
from datetime import date, datetime
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import requests
import streamlit as st
from github_store import append_rows, read_data
from spc import imr, xbar_r

st.set_page_config(page_title="Quality Parameter Control", page_icon="🏭", layout="wide", initial_sidebar_state="collapsed")
CONFIG=json.loads(Path("config/forms.json").read_text(encoding="utf-8"))
for dept in CONFIG.get("departments",{}).values():
    for form in dept.get("forms",[]):
        for parameter in form.get("parameters",[]): parameter["required"]=False
PLANTS=CONFIG["plants"]; DEPARTMENTS=list(CONFIG["departments"]); SHIFTS=["Shift A","Shift B","Shift C","Shift R"]
SPEC_PATH="data/spec_limits.csv"; SPEC_COLUMNS=["Plant","Department","Form ID","Parameter ID","Parameter","LSL","USL","Updated At"]

st.markdown("""<style>
.stApp{background:linear-gradient(135deg,#f8fffa,#edf7f0)}.block-container{max-width:1180px;padding-top:2rem}#MainMenu,footer{visibility:hidden}.login-hero,.page-hero{padding:1.5rem;border-radius:20px;background:linear-gradient(125deg,#14532d,#16a34a);color:white;margin-bottom:1rem;box-shadow:0 12px 30px rgba(20,83,45,.16)}.login-hero{padding:2.2rem}.login-hero h1,.page-hero h1{margin:0}.feature-row{display:grid;grid-template-columns:repeat(3,1fr);gap:.75rem;margin-top:1rem}.feature,.card{padding:.85rem 1rem;border-radius:14px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.16)}.card{background:#f7fff9;border-color:#d9eee0;color:#173b26;margin:.7rem 0}div[data-testid="stForm"]{background:white;border:1px solid #dcebe1;border-radius:20px;padding:1.2rem;box-shadow:0 12px 32px rgba(15,50,30,.08)}.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{min-height:44px;border-radius:11px;font-weight:700}@media(max-width:760px){.feature-row{display:none}}
</style>""",unsafe_allow_html=True)

def slug(v): return re.sub(r"[^a-z0-9]+","_",str(v).lower()).strip("_")
def visible(f,vals):
    rule=f.get("show_if"); return not rule or vals.get(rule["field"])==rule["equals"]
def widget(f,key):
    label=f["label"]+" (Optional)"
    if f["type"]=="choice": return st.selectbox(label,[""]+f["options"],key=key,format_func=lambda x:"Select an option (optional)" if x=="" else x)
    if f["type"]=="number":
        raw=st.text_input(label,key=key,placeholder="Leave blank if not measured")
        if not raw.strip(): return ""
        try: return float(raw)
        except ValueError: return raw
    if f["type"]=="textarea": return st.text_area(label,key=key)
    return st.text_input(label,key=key)
def hline(fig,value,name,color,n,dash="dot"): fig.add_trace(go.Scatter(x=list(range(1,n+1)),y=[value]*n,name=name,mode="lines",line=dict(color=color,dash=dash,width=2)))
def add_control(fig,c,u,l,n): hline(fig,c,"Center Line","#15803d",n,"dash"); hline(fig,u,"UCL","#dc2626",n); hline(fig,l,"LCL","#dc2626",n)
def add_specs(fig,lsl,usl,n):
    if lsl is not None: hline(fig,lsl,"LSL","#f59e0b",n,"dashdot")
    if usl is not None: hline(fig,usl,"USL","#7c3aed",n,"dashdot")

def gh_headers(): return {"Authorization":f"Bearer {st.secrets['GITHUB_TOKEN']}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
def gh_url(path): return f"https://api.github.com/repos/{st.secrets['GITHUB_OWNER']}/{st.secrets['GITHUB_REPO']}/contents/{path}"
def read_specs():
    r=requests.get(gh_url(SPEC_PATH),headers=gh_headers(),params={"ref":st.secrets.get("GITHUB_BRANCH","main")},timeout=30)
    if r.status_code==404: return pd.DataFrame(columns=SPEC_COLUMNS),None
    r.raise_for_status(); p=r.json()
    try: df=pd.read_csv(io.BytesIO(base64.b64decode(p["content"])))
    except pd.errors.EmptyDataError: df=pd.DataFrame(columns=SPEC_COLUMNS)
    for c in SPEC_COLUMNS:
        if c not in df: df[c]=""
    return df[SPEC_COLUMNS],p["sha"]
def write_specs(df,sha,msg):
    body={"message":msg,"content":base64.b64encode(df[SPEC_COLUMNS].to_csv(index=False).encode()).decode(),"branch":st.secrets.get("GITHUB_BRANCH","main")}
    if sha: body["sha"]=sha
    r=requests.put(gh_url(SPEC_PATH),headers=gh_headers(),json=body,timeout=30); r.raise_for_status()
def save_spec(dep,form,param,lsl,usl):
    df,sha=read_specs(); mask=df["Plant"].astype(str).eq(st.session_state.plant)&df["Department"].astype(str).eq(dep)&df["Form ID"].astype(str).eq(form["id"])&df["Parameter ID"].astype(str).eq(param["id"]); df=df.loc[~mask]
    row={"Plant":st.session_state.plant,"Department":dep,"Form ID":form["id"],"Parameter ID":param["id"],"Parameter":param["label"],"LSL":lsl,"USL":usl,"Updated At":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}; write_specs(pd.concat([df,pd.DataFrame([row])],ignore_index=True),sha,f"Update limits for {param['label']}")
def get_spec(dep,form,param):
    try: df,_=read_specs()
    except Exception: return None,None
    x=df[df["Plant"].astype(str).eq(st.session_state.plant)&df["Department"].astype(str).eq(dep)&df["Form ID"].astype(str).eq(form["id"])&df["Parameter ID"].astype(str).eq(param["id"])]
    if x.empty: return None,None
    l=pd.to_numeric(x.iloc[-1]["LSL"],errors="coerce"); u=pd.to_numeric(x.iloc[-1]["USL"],errors="coerce"); return (None if pd.isna(l) else float(l)),(None if pd.isna(u) else float(u))

def rows_for(form,d,shift,vals,rid):
    rows=[]; now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for p in form["parameters"]:
        if not visible(p,vals): continue
        v=vals.get(p["id"],"")
        if v=="": continue
        rows.append({"Record ID":rid,"Plant":st.session_state.plant,"Department":st.session_state.department,"Form ID":form["id"],"Form Title":form["title"],"Inspection Date":str(d),"Shift":shift,"Parameter ID":p["id"],"Parameter":p["label"],"Value":v if p["type"]=="number" else "","Text Value":"" if p["type"]=="number" else v,"Unit":p.get("unit",""),"Created At":now})
    return rows
def template(form):
    cols=["Inspection Date","Shift"]+[p["label"] for p in form["parameters"]]; row={c:"" for c in cols}; row.update({"Inspection Date":date.today().isoformat(),"Shift":"Shift A"}); out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as w: pd.DataFrame([row],columns=cols).to_excel(w,sheet_name="Quality Entry",index=False)
    return out.getvalue()
def parse_upload(file,form):
    df=pd.read_csv(file) if file.name.lower().endswith(".csv") else pd.read_excel(file,sheet_name="Quality Entry",engine="openpyxl"); df=df.dropna(how="all"); required=["Inspection Date","Shift"]+[p["label"] for p in form["parameters"]]; missing=[c for c in required if c not in df]
    if missing: raise ValueError("Missing columns: "+", ".join(missing))
    output=[]; errors=[]
    for i,row in df.iterrows():
        d=pd.to_datetime(row["Inspection Date"],errors="coerce"); shift="" if pd.isna(row["Shift"]) else str(row["Shift"]).strip(); vals={p["id"]:("" if pd.isna(row[p["label"]]) else row[p["label"]]) for p in form["parameters"]}
        if pd.isna(d): errors.append(f"Row {i+2}: invalid date")
        if shift not in SHIFTS: errors.append(f"Row {i+2}: invalid shift")
        for p in form["parameters"]:
            v=vals[p["id"]]
            if p["type"]=="number" and v!="":
                x=pd.to_numeric(v,errors="coerce")
                if pd.isna(x): errors.append(f"Row {i+2}: {p['label']} must be numeric")
                else: vals[p["id"]]=float(x)
            if p["type"]=="choice" and v!="" and v not in p["options"]: errors.append(f"Row {i+2}: invalid {p['label']}")
        output.append((d,shift,vals))
    if errors: raise ValueError("\n".join(errors[:25]))
    return output
def records(dep,form):
    df,_=read_data(); return df[df["Plant"].astype(str).eq(st.session_state.plant)&df["Department"].astype(str).eq(dep)&df["Form ID"].astype(str).eq(form["id"])].copy()
def wide(df,form):
    if df.empty:return pd.DataFrame()
    base_cols=["Record ID","Plant","Department","Form Title","Inspection Date","Shift","Created At"]; base=df.groupby("Record ID",as_index=False).first()[base_cols]; df=df.copy(); df["Export Value"]=df["Value"].where(df["Value"].notna()&df["Value"].astype(str).ne(""),df["Text Value"]); pivot=df.pivot_table(index="Record ID",columns="Parameter",values="Export Value",aggfunc="first").reset_index(); out=base.merge(pivot,on="Record ID",how="left"); return out[base_cols+[p["label"] for p in form["parameters"] if p["label"] in out.columns]]
def xlsx(df,sheet="Data"):
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as w: df.to_excel(w,sheet_name=sheet[:31],index=False)
    return out.getvalue()
def options(form):
    groups={}
    for p in form["parameters"]:
        if p.get("chart_group"): groups.setdefault(p["chart_group"],[]).append(p)
    singles=[p for p in form["parameters"] if p.get("chart_type")=="imr"]
    return groups,singles,[p["label"] for p in singles]+list(groups)
def chart_result(df,form,sel):
    groups,singles,_=options(form)
    if sel in groups:
        ps=groups[sel]; pivot=df[df["Parameter ID"].isin([p["id"] for p in ps])].pivot_table(index="Record ID",columns="Parameter ID",values="Value",aggfunc="first").reindex(columns=[p["id"] for p in ps]); return xbar_r(pivot),{"id":f"group_{slug(sel)}","label":sel},True
    p=next(p for p in singles if p["label"]==sel); return imr(pd.to_numeric(df.loc[df["Parameter ID"].eq(p["id"]),"Value"],errors="coerce")),p,False
def make_charts(result,sel,grouped,lsl=None,usl=None):
    values,c,u,l,ranges,rc,ru,rl=result; f1=go.Figure(go.Scatter(x=list(range(1,len(values)+1)),y=values,mode="lines+markers",name=sel)); add_control(f1,c,u,l,len(values)); add_specs(f1,lsl,usl,len(values)); f1.update_layout(title=("X-bar Chart: " if grouped else "Individuals Chart: ")+sel); f2=go.Figure(go.Scatter(x=list(range(1,len(ranges)+1)),y=ranges,mode="lines+markers",name="Range")); add_control(f2,rc,ru,rl,len(ranges)); f2.update_layout(title=("R Chart: " if grouped else "Moving Range Chart: ")+sel); return f1,f2
def capability(result,grouped):
    values,_,_,_,_,rbar,_,_=result; return float(pd.Series(values).mean()),float(rbar)/(3.407 if grouped else 1.128)

def operator_page():
    st.markdown(f"<div class='page-hero'><h1>🧪 Operator Quality Data Entry</h1><p>{st.session_state.plant} · {st.session_state.department}</p></div>",unsafe_allow_html=True); forms=CONFIG["departments"][st.session_state.department]["forms"]; form=st.selectbox("Quality Check",forms,format_func=lambda x:x["title"]); m,u,d=st.tabs(["✍️ Manual Entry","📥 Excel Upload","⬇ Download Data"])
    with m:
        dt=st.date_input("Inspection Date *",date.today()); shift=st.selectbox("Shift *",SHIFTS); vals={}
        for p in form["parameters"]:
            if visible(p,vals): vals[p["id"]]=widget(p,"m"+form["id"]+p["id"])
        if st.button("Save Manual Entry",type="primary",use_container_width=True):
            invalid=[]
            for p in form["parameters"]:
                v=vals.get(p["id"],"")
                if p["type"]=="number" and v!="":
                    try: vals[p["id"]]=float(v)
                    except: invalid.append(p["label"])
            if invalid: st.error("Enter numbers or leave blank: "+", ".join(invalid))
            else:
                rid="QC-"+datetime.now().strftime("%Y%m%d%H%M%S%f"); rows=rows_for(form,dt,shift,vals,rid)
                if not rows: st.warning("Enter at least one parameter before saving.")
                else:
                    try: append_rows(rows,"Add quality check "+rid); st.success("Saved: "+rid)
                    except Exception as e: st.error(f"Save failed: {e}")
    with u:
        st.download_button("Download Blank Excel Template",template(form),f"{form['id']}_template.xlsx",use_container_width=True); file=st.file_uploader("Upload completed Excel or CSV",type=["xlsx","csv"])
        if file and st.button("Validate and Save Uploaded Rows",type="primary",use_container_width=True):
            try:
                parsed=parse_upload(file,form); all_rows=[]
                for dt,shift,vals in parsed:
                    all_rows+=rows_for(form,dt.date(),shift,vals,"QC-"+datetime.now().strftime("%Y%m%d%H%M%S%f"))
                if not all_rows: st.warning("No parameter values found in the uploaded file.")
                else: append_rows(all_rows,f"Add {len(parsed)} uploaded checks"); st.success(f"{len(parsed)} rows processed.")
            except Exception as e: st.error(f"Upload failed: {e}")
    with d:
        out=wide(records(st.session_state.department,form),form)
        if out.empty: st.info("No saved records available.")
        else:
            a,b=st.columns(2); a.download_button("Download Entered Data as Excel",xlsx(out),f"{form['id']}_data.xlsx",use_container_width=True); b.download_button("Download Entered Data as CSV",out.to_csv(index=False).encode("utf-8-sig"),f"{form['id']}_data.csv",use_container_width=True)

def chart_page():
    st.markdown("<div class='page-hero'><h1>📈 Parameter Control Charts</h1></div>",unsafe_allow_html=True); a,b=st.columns(2); dep=a.selectbox("Department",DEPARTMENTS,key="cd"); forms=CONFIG["departments"][dep]["forms"]; form=b.selectbox("Quality Check",forms,format_func=lambda x:x["title"],key="cf"); df=records(dep,form)
    if df.empty: st.info("No data available."); return
    _,_,opts=options(form); sel=st.selectbox("Parameter / Group",opts,key="cp"); result,param,grouped=chart_result(df,form,sel)
    if not result: st.info("At least two readings or two complete subgroups are required."); return
    lsl,usl=get_spec(dep,form,param); f1,f2=make_charts(result,sel,grouped,lsl,usl); st.plotly_chart(f1,use_container_width=True); st.plotly_chart(f2,use_container_width=True); mean,sigma=capability(result,grouped)
    if lsl is not None and usl is not None and sigma>0:
        cp=(usl-lsl)/(6*sigma); cpk=min((usl-mean)/(3*sigma),(mean-lsl)/(3*sigma)); a,b,c,d=st.columns(4); a.metric("LSL",f"{lsl:.3f}"); b.metric("USL",f"{usl:.3f}"); c.metric("Cp",f"{cp:.3f}"); d.metric("Cpk",f"{cpk:.3f}")
    else: st.info("Add both USL and LSL to display Cp and Cpk.")
    out=wide(df,form); a,b,c,d=st.columns(4); a.download_button("SPC Data Excel",xlsx(out),f"{form['id']}_spc.xlsx",use_container_width=True); b.download_button("SPC Data CSV",out.to_csv(index=False).encode(),f"{form['id']}_spc.csv",use_container_width=True); c.download_button("Main Chart HTML",pio.to_html(f1,full_html=True,include_plotlyjs="cdn").encode(),f"{slug(sel)}_main.html",use_container_width=True); d.download_button("Range Chart HTML",pio.to_html(f2,full_html=True,include_plotlyjs="cdn").encode(),f"{slug(sel)}_range.html",use_container_width=True)

def spec_page():
    st.markdown("<div class='page-hero'><h1>🎯 Specifications & Capability</h1></div>",unsafe_allow_html=True); a,b=st.columns(2); dep=a.selectbox("Department",DEPARTMENTS,key="sd"); forms=CONFIG["departments"][dep]["forms"]; form=b.selectbox("Quality Check",forms,format_func=lambda x:x["title"],key="sf"); groups,singles,opts=options(form); sel=st.selectbox("Parameter / Group",opts,key="sp"); param={"id":f"group_{slug(sel)}","label":sel} if sel in groups else next(p for p in singles if p["label"]==sel); old_l,old_u=get_spec(dep,form,param); a,b=st.columns(2); lt=a.text_input("LSL",value="" if old_l is None else str(old_l)); ut=b.text_input("USL",value="" if old_u is None else str(old_u))
    if st.button("Save USL / LSL",type="primary",use_container_width=True):
        try:
            l=None if not lt.strip() else float(lt); u=None if not ut.strip() else float(ut)
            if l is not None and u is not None and l>=u: raise ValueError("LSL must be lower than USL.")
            save_spec(dep,form,param,l,u); st.success("Specification limits saved."); st.rerun()
        except Exception as e: st.error(str(e))
    specs,_=read_specs(); selected=specs[specs["Plant"].astype(str).eq(st.session_state.plant)&specs["Department"].astype(str).eq(dep)&specs["Form ID"].astype(str).eq(form["id"])]
    if not selected.empty:
        a,b=st.columns(2); a.download_button("Download Specification Limits as Excel",xlsx(selected,"Specification Limits"),f"{form['id']}_spec_limits.xlsx",use_container_width=True); b.download_button("Download Specification Limits as CSV",selected.to_csv(index=False).encode(),f"{form['id']}_spec_limits.csv",use_container_width=True)
    df=records(dep,form)
    if df.empty: st.info("No process data available."); return
    result,param,grouped=chart_result(df,form,sel)
    if not result: st.info("At least two readings or two complete subgroups are required."); return
    lsl,usl=get_spec(dep,form,param); f1,f2=make_charts(result,sel,grouped,lsl,usl); st.plotly_chart(f1,use_container_width=True); st.plotly_chart(f2,use_container_width=True); mean,sigma=capability(result,grouped)
    if lsl is None or usl is None: st.warning("Add both USL and LSL to calculate Cp and Cpk.")
    elif sigma>0:
        cp=(usl-lsl)/(6*sigma); cpk=min((usl-mean)/(3*sigma),(mean-lsl)/(3*sigma)); a,b,c,d=st.columns(4); a.metric("Mean",f"{mean:.3f}"); b.metric("Sigma",f"{sigma:.3f}"); c.metric("Cp",f"{cp:.3f}"); d.metric("Cpk",f"{cpk:.3f}")

def login():
    st.markdown("""<div class='login-hero'><h1>Quality Parameter Control</h1><p>Digital inspections, SPC charts and process capability.</p><div class='feature-row'><div class='feature'><b>🧪 Digital Entry</b></div><div class='feature'><b>📊 Live SPC</b></div><div class='feature'><b>🎯 Cp & Cpk</b></div></div></div>""",unsafe_allow_html=True); _,c,_=st.columns([1,1.3,1])
    with c:
        with st.form("login"):
            plant=st.selectbox("Plant",PLANTS); pw=st.text_input("Plant Password",type="password")
            if st.form_submit_button("Continue",use_container_width=True):
                if pw==st.secrets.get("plant_passwords",{}).get(slug(plant)): st.session_state.update(plant=plant,plant_ok=True); st.rerun()
                else: st.error("Incorrect plant password.")
def main():
    if not st.session_state.get("plant_ok"): login(); st.stop()
    module=st.radio("Module",["Operator Data Entry","Control Chart Analysis","Specifications & Capability"],horizontal=True)
    if module=="Control Chart Analysis": chart_page(); return
    if module=="Specifications & Capability": spec_page(); return
    if not st.session_state.get("department_ok"):
        with st.form("dept"):
            dep=st.selectbox("Department",DEPARTMENTS); pw=st.text_input("Department Password",type="password")
            if st.form_submit_button("Open Department"):
                key=f"{slug(st.session_state.plant)}_{slug(dep)}"; expected=st.secrets.get("department_passwords",{}).get(key,st.secrets.get("DEFAULT_DEPARTMENT_PASSWORD","Dept@123"))
                if pw==expected: st.session_state.update(department=dep,department_ok=True); st.rerun()
                else: st.error("Incorrect department password.")
        st.stop()
    operator_page()
main()
