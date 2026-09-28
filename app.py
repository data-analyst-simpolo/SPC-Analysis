import io, json, re
from datetime import date, datetime
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from github_store import append_rows, read_data
from spc import imr, xbar_r

st.set_page_config(page_title="Quality Parameter Control", page_icon="🏭", layout="wide", initial_sidebar_state="collapsed")
CONFIG=json.loads(Path("config/forms.json").read_text(encoding="utf-8")); PLANTS=CONFIG["plants"]; DEPARTMENTS=list(CONFIG["departments"]); SHIFTS=["Shift A","Shift B","Shift C","Shift R"]

st.markdown("""
<style>
:root{--green:#166534;--green2:#15803d;--mint:#ecfdf3;--ink:#10231a;--muted:#64748b;--line:#dcebe1}
.stApp{background:radial-gradient(circle at 8% 8%,#dcfce7 0,transparent 23%),linear-gradient(135deg,#f8fffa 0%,#f4f8f5 55%,#edf7f0 100%)}
.block-container{max-width:1180px;padding-top:2.1rem;padding-bottom:3rem}
#MainMenu,footer{visibility:hidden}.stDeployButton{display:none}
.login-hero{position:relative;overflow:hidden;padding:2.2rem 2.4rem;border-radius:26px;background:linear-gradient(125deg,#123f28 0%,#166534 48%,#16a34a 100%);color:#fff;box-shadow:0 22px 60px rgba(20,83,45,.21);margin:1rem 0 1.4rem}
.login-hero:after{content:"";position:absolute;width:310px;height:310px;border-radius:50%;right:-90px;top:-155px;background:rgba(255,255,255,.10)}
.hero-kicker{display:inline-flex;align-items:center;gap:.45rem;padding:.35rem .72rem;border:1px solid rgba(255,255,255,.28);border-radius:999px;background:rgba(255,255,255,.10);font-size:.78rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase}
.login-hero h1{font-size:2.35rem;line-height:1.12;margin:.85rem 0 .45rem;font-weight:800;letter-spacing:-.035em}.login-hero p{font-size:1rem;opacity:.88;margin:0;max-width:720px}
.feature-row{display:grid;grid-template-columns:repeat(3,1fr);gap:.75rem;margin-top:1.35rem}.feature{padding:.8rem 1rem;border-radius:14px;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.13);font-size:.88rem}.feature b{display:block;font-size:.96rem;margin-bottom:.12rem}
.login-title{text-align:center;margin:.25rem 0 1rem}.login-title h3{margin:0;color:var(--ink);font-size:1.32rem}.login-title p{margin:.25rem 0;color:var(--muted);font-size:.92rem}
div[data-testid="stForm"]{background:rgba(255,255,255,.92);border:1px solid var(--line);border-radius:22px;padding:1.25rem 1.35rem 1.1rem;box-shadow:0 16px 42px rgba(15,50,30,.09)}
div[data-baseweb="select"]>div,.stTextInput input{background:#f4fbf6!important;border:1px solid #d9eee0!important;border-radius:12px!important;min-height:48px}.stTextInput input:focus{border-color:#22c55e!important;box-shadow:0 0 0 3px rgba(34,197,94,.12)!important}
.stButton>button,.stFormSubmitButton>button{min-height:48px;border-radius:12px;font-weight:750;letter-spacing:.01em}.stFormSubmitButton>button{background:linear-gradient(90deg,#166534,#16a34a)!important;color:white!important;border:0!important;box-shadow:0 8px 20px rgba(22,101,52,.20)}.stFormSubmitButton>button:hover{transform:translateY(-1px);box-shadow:0 11px 24px rgba(22,101,52,.26)}
.trust{text-align:center;margin-top:1rem;color:#6b7f73;font-size:.82rem}.page-hero{padding:1.35rem 1.5rem;border-radius:19px;background:linear-gradient(125deg,#14532d,#16a34a);color:white;margin-bottom:1rem;box-shadow:0 12px 30px rgba(20,83,45,.16)}.page-hero h1{margin:0;font-size:1.8rem}.page-hero p{margin:.3rem 0 0;opacity:.88}
@media(max-width:760px){.block-container{padding:1rem}.login-hero{padding:1.5rem}.login-hero h1{font-size:1.75rem}.feature-row{grid-template-columns:1fr}.feature{display:none}}
</style>
""",unsafe_allow_html=True)

def slug(v): return re.sub(r"[^a-z0-9]+","_",str(v).lower()).strip("_")
def visible(f,vals):
 r=f.get("show_if"); return not r or vals.get(r["field"])==r["equals"]
def widget(f,key):
 label=f["label"]+(" *" if f.get("required") else ""); typ=f["type"]
 if typ=="choice": return st.selectbox(label,f["options"],key=key)
 if typ=="number": return st.number_input(label,value=0.0,format=f"%.{f.get('decimals',3)}f",key=key)
 if typ=="textarea": return st.text_area(label,key=key)
 return st.text_input(label,key=key)
def normalized(form,d,shift,vals,rid,created):
 return [{"Record ID":rid,"Plant":st.session_state.plant,"Department":st.session_state.department,"Form ID":form["id"],"Form Title":form["title"],"Inspection Date":str(d),"Shift":shift,"Parameter ID":p["id"],"Parameter":p["label"],"Value":vals.get(p["id"],"") if p["type"]=="number" else "","Text Value":"" if p["type"]=="number" else vals.get(p["id"],""),"Unit":p.get("unit",""),"Created At":created} for p in form["parameters"] if visible(p,vals)]
def template(form):
 cols=["Inspection Date","Shift"]+[p["label"] for p in form["parameters"]]; row={c:"" for c in cols}; row.update({"Inspection Date":date.today().isoformat(),"Shift":"Shift A"})
 for p in form["parameters"]:
  if p["type"]=="choice": row[p["label"]]=p["options"][0]
 out=io.BytesIO()
 with pd.ExcelWriter(out,engine="openpyxl") as w:
  pd.DataFrame([row],columns=cols).to_excel(w,sheet_name="Quality Entry",index=False)
  pd.DataFrame([["Rule","One row equals one complete inspection"],["Shift",", ".join(SHIFTS)],["Conditional","Ball Mill Number is required for Batch Ball Mill; Other Tile Size is required when size is Other"]],columns=["Item","Instruction"]).to_excel(w,sheet_name="Instructions",index=False)
 return out.getvalue()
def parse_upload(upload,form):
 df=pd.read_csv(upload) if upload.name.lower().endswith(".csv") else pd.read_excel(upload,sheet_name="Quality Entry",engine="openpyxl"); df=df.dropna(how="all")
 cols=["Inspection Date","Shift"]+[p["label"] for p in form["parameters"]]; missing=[c for c in cols if c not in df]
 if missing: raise ValueError("Missing columns: "+", ".join(missing))
 result=[]; errors=[]
 for idx,row in df.iterrows():
  r=idx+2; d=pd.to_datetime(row["Inspection Date"],errors="coerce"); shift="" if pd.isna(row["Shift"]) else str(row["Shift"]).strip(); vals={p["id"]:("" if pd.isna(row[p["label"]]) else row[p["label"]]) for p in form["parameters"]}
  if pd.isna(d): errors.append(f"Row {r}: invalid Inspection Date")
  if shift not in SHIFTS: errors.append(f"Row {r}: invalid Shift")
  for p in form["parameters"]:
   if not visible(p,vals): continue
   v=vals[p["id"]]
   if p.get("required") and v=="": errors.append(f"Row {r}: {p['label']} is required")
   if p["type"]=="number" and v!="":
    x=pd.to_numeric(v,errors="coerce")
    if pd.isna(x): errors.append(f"Row {r}: {p['label']} must be numeric")
    else: vals[p["id"]]=float(x)
   if p["type"]=="choice" and v not in p["options"]: errors.append(f"Row {r}: invalid {p['label']}")
  result.append((d,shift,vals))
 if errors: raise ValueError("\n".join(errors[:25]))
 return result

def entry_page():
 st.markdown(f"<div class='page-hero'><h1>🧪 Operator Quality Data Entry</h1><p>{st.session_state.plant} · {st.session_state.department}</p></div>",unsafe_allow_html=True)
 forms=CONFIG["departments"][st.session_state.department]["forms"]; form=st.selectbox("Quality Check",forms,format_func=lambda x:x["title"]); st.caption(form.get("description","")); m,x=st.tabs(["✍️ Manual Entry","📥 Excel Upload"])
 with m:
  d=st.date_input("Inspection Date *",date.today(),key="md"+form["id"]); shift=st.selectbox("Shift *",SHIFTS,key="ms"+form["id"]); vals={}
  for p in form["parameters"]:
   if visible(p,vals): vals[p["id"]]=widget(p,"m"+form["id"]+p["id"])
  if st.button("Save Manual Entry",type="primary",use_container_width=True):
   miss=[p["label"] for p in form["parameters"] if visible(p,vals) and p.get("required") and (vals.get(p["id"]) is None or isinstance(vals.get(p["id"]),str) and not vals.get(p["id"]).strip())]
   if miss: st.error("Required fields missing: "+", ".join(miss))
   else:
    rid="QC-"+datetime.now().strftime("%Y%m%d%H%M%S%f")
    try: append_rows(normalized(form,d,shift,vals,rid,datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"Add manual quality check "+rid); st.success("Saved: "+rid)
    except Exception as e: st.error(f"Save failed: {e}")
 with x:
  st.info("Download the template, enter one full inspection per row, and upload the completed file.")
  st.download_button("Download Excel Template",template(form),f"{form['id']}_template.xlsx",use_container_width=True)
  up=st.file_uploader("Upload completed Excel or CSV",type=["xlsx","csv"],key="u"+form["id"])
  if up and st.button("Validate and Save Uploaded Rows",type="primary",use_container_width=True):
   try:
    parsed=parse_upload(up,form); rows=[]
    for d,shift,vals in parsed:
     rid="QC-"+datetime.now().strftime("%Y%m%d%H%M%S%f"); rows+=normalized(form,d.date(),shift,vals,rid,datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    append_rows(rows,f"Add {len(parsed)} uploaded quality checks"); st.success(f"{len(parsed)} rows uploaded successfully.")
   except Exception as e: st.error(f"Upload failed: {e}")

def chart_page():
 st.markdown(f"<div class='page-hero'><h1>📈 Parameter Control Charts</h1><p>{st.session_state.plant} plant</p></div>",unsafe_allow_html=True)
 try: data,_=read_data()
 except Exception as e: st.error(str(e)); return
 data=data[data["Plant"].astype(str).eq(st.session_state.plant)]; c1,c2=st.columns(2); dep=c1.selectbox("Department",DEPARTMENTS); forms=CONFIG["departments"][dep]["forms"]; form=c2.selectbox("Quality Check",forms,format_func=lambda x:x["title"]); fd=data[(data["Department"].eq(dep))&(data["Form ID"].eq(form["id"]))].copy()
 if fd.empty: st.info("No data available for the selected quality check."); return
 groups={}
 for p in form["parameters"]:
  if p.get("chart_group"): groups.setdefault(p["chart_group"],[]).append(p)
 singles=[p for p in form["parameters"] if p.get("chart_type")=="imr"]; choice=st.selectbox("Parameter / Group",[p["label"] for p in singles]+list(groups))
 if choice in groups:
  ps=groups[choice]; pv=fd[fd["Parameter ID"].isin([p["id"] for p in ps])].pivot_table(index="Record ID",columns="Parameter ID",values="Value",aggfunc="first").reindex(columns=[p["id"] for p in ps]); z=xbar_r(pv)
  if not z: st.info("At least two complete 14-reading subgroups are required."); return
 else:
  p=next(p for p in singles if p["label"]==choice); z=imr(pd.to_numeric(fd.loc[fd["Parameter ID"].eq(p["id"]),"Value"],errors="coerce"))
  if not z: st.info("At least two readings are required."); return
 a,c,u,l,b,bc,bu,bl=z
 for values,cc,uu,ll,title in [(a,c,u,l,("X-bar Chart: " if choice in groups else "Individuals Chart: ")+choice),(b,bc,bu,bl,("R Chart: " if choice in groups else "Moving Range Chart: ")+choice)]:
  fig=go.Figure(go.Scatter(x=list(range(1,len(values)+1)),y=values,mode="lines+markers",name=choice)); add_limit_lines(fig,cc,uu,ll,len(values)); fig.update_layout(title=title); st.plotly_chart(fig,use_container_width=True)

def plant_login():
 st.markdown("""<div class='login-hero'><span class='hero-kicker'>◆ Smart Manufacturing Quality</span><h1>Quality Parameter Control</h1><p>Secure digital quality checks, disciplined traceability and real-time statistical process control for plant operations.</p><div class='feature-row'><div class='feature'><b>🧪 Digital Inspections</b>Structured operator entry</div><div class='feature'><b>📊 Live SPC</b>I-MR and X-bar/R charts</div><div class='feature'><b>🔐 Controlled Access</b>Plant and department login</div></div></div><div class='login-title'><h3>Welcome back</h3><p>Select the plant and enter the authorized password to continue.</p></div>""",unsafe_allow_html=True)
 left,center,right=st.columns([1,1.35,1])
 with center:
  with st.form("plant_login"):
   plant=st.selectbox("Plant",PLANTS); password=st.text_input("Plant Password",type="password",placeholder="Enter plant password")
   if st.form_submit_button("Continue securely  →",use_container_width=True):
    if password==st.secrets.get("plant_passwords",{}).get(slug(plant)): st.session_state.update(plant=plant,plant_ok=True); st.rerun()
    else: st.error("Incorrect plant password.")
  st.markdown("<div class='trust'>🔒 Authorized plant users only &nbsp;•&nbsp; Data secured through controlled repository access</div>",unsafe_allow_html=True)

def main():
 if not st.session_state.get("plant_ok"): plant_login(); st.stop()
 with st.sidebar:
  st.success("Plant: "+st.session_state.plant)
  if st.button("Logout",use_container_width=True): st.session_state.clear(); st.rerun()
 module=st.radio("Module",["Operator Data Entry","Control Chart Analysis"],horizontal=True)
 if module=="Control Chart Analysis": chart_page(); return
 if not st.session_state.get("department_ok"):
  st.markdown(f"<div class='page-hero'><h1>🔐 Department Access</h1><p>{st.session_state.plant} plant</p></div>",unsafe_allow_html=True)
  a,b,c=st.columns([1,1.35,1])
  with b:
   with st.form("department_login"):
    dep=st.selectbox("Department",DEPARTMENTS); password=st.text_input("Department Password",type="password",placeholder="Enter department password")
    if st.form_submit_button("Open department  →",use_container_width=True):
     key=f"{slug(st.session_state.plant)}_{slug(dep)}"; expected=st.secrets.get("department_passwords",{}).get(key,st.secrets.get("DEFAULT_DEPARTMENT_PASSWORD","Dept@123"))
     if password==expected: st.session_state.update(department=dep,department_ok=True); st.rerun()
     else: st.error("Incorrect department password.")
  st.stop()
 entry_page()
main()
