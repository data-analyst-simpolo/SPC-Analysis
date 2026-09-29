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

# Thickness 1-14 and Bulk Density 1-14 are optional in the Press Green Tile form.
# This runtime override keeps the app correct even if an older forms.json still marks them required.
for form in CONFIG.get("departments", {}).get("Press", {}).get("forms", []):
    if form.get("id") == "press_green_tile_thickness_bd":
        for parameter in form.get("parameters", []):
            parameter_id = str(parameter.get("id", ""))
            if parameter_id.startswith("thickness_") or parameter_id.startswith("bulk_density_"):
                parameter["required"] = False

PLANTS=CONFIG["plants"]; DEPARTMENTS=list(CONFIG["departments"]); SHIFTS=["Shift A","Shift B","Shift C","Shift R"]
SPEC_PATH="data/spec_limits.csv"; SPEC_COLUMNS=["Plant","Department","Form ID","Parameter ID","Parameter","LSL","USL","Updated At"]

st.markdown("""<style>
:root{--green:#166534;--ink:#10231a;--muted:#64748b;--line:#dcebe1}.stApp{background:radial-gradient(circle at 8% 8%,#dcfce7 0,transparent 23%),linear-gradient(135deg,#f8fffa,#edf7f0)}.block-container{max-width:1180px;padding-top:2rem;padding-bottom:3rem}#MainMenu,footer{visibility:hidden}.stDeployButton{display:none}.login-hero{padding:2.2rem 2.4rem;border-radius:26px;background:linear-gradient(125deg,#123f28,#166534 48%,#16a34a);color:#fff;box-shadow:0 22px 60px rgba(20,83,45,.21);margin:1rem 0 1.4rem}.login-hero h1{font-size:2.35rem;margin:.85rem 0 .45rem;font-weight:800}.login-hero p{opacity:.88;margin:0}.hero-kicker{display:inline-flex;padding:.35rem .72rem;border:1px solid rgba(255,255,255,.28);border-radius:999px;background:rgba(255,255,255,.10);font-size:.78rem;font-weight:700}.feature-row{display:grid;grid-template-columns:repeat(3,1fr);gap:.75rem;margin-top:1.35rem}.feature{padding:.8rem 1rem;border-radius:14px;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.13)}.feature b{display:block}.login-title{text-align:center;margin:.25rem 0 1rem}.login-title h3{margin:0}.login-title p{margin:.25rem 0;color:var(--muted)}div[data-testid="stForm"]{background:rgba(255,255,255,.94);border:1px solid var(--line);border-radius:22px;padding:1.25rem;box-shadow:0 16px 42px rgba(15,50,30,.09)}div[data-baseweb="select"]>div,.stTextInput input{background:#f4fbf6!important;border:1px solid #d9eee0!important;border-radius:12px!important;min-height:48px}.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{min-height:46px;border-radius:12px;font-weight:700}.stFormSubmitButton>button{background:linear-gradient(90deg,#166534,#16a34a)!important;color:white!important;border:0!important}.page-hero{padding:1.35rem 1.5rem;border-radius:19px;background:linear-gradient(125deg,#14532d,#16a34a);color:white;margin-bottom:1rem;box-shadow:0 12px 30px rgba(20,83,45,.16)}.page-hero h1{margin:0;font-size:1.8rem}.page-hero p{margin:.3rem 0 0;opacity:.88}.card{padding:.9rem 1rem;border:1px solid #d9eee0;border-radius:14px;background:#f7fff9;margin:.7rem 0}@media(max-width:760px){.block-container{padding:1rem}.login-hero{padding:1.5rem}.feature-row{display:none}}
</style>""",unsafe_allow_html=True)

def slug(v): return re.sub(r"[^a-z0-9]+","_",str(v).lower()).strip("_")
def visible(f,v):
 r=f.get("show_if"); return not r or v.get(r["field"])==r["equals"]
def widget(f,key):
 label=f["label"]+(" *" if f.get("required") else "")
 if f["type"]=="choice": return st.selectbox(label,f["options"],key=key)
 if f["type"]=="number":
  # Optional numeric fields must be allowed to remain genuinely blank.
  if not f.get("required"):
   raw=st.text_input(label,key=key,placeholder="Optional - leave blank if not measured")
   if not raw.strip(): return ""
   try: return float(raw)
   except ValueError:
    st.warning(f"{f['label']} must be numeric or left blank.")
    return raw
  return st.number_input(label,value=0.0,format=f"%.{f.get('decimals',3)}f",key=key)
 if f["type"]=="textarea": return st.text_area(label,key=key)
 return st.text_input(label,key=key)
def hline(fig,value,name,color,count,dash="dot"):
 fig.add_trace(go.Scatter(x=list(range(1,count+1)),y=[value]*count,name=name,mode="lines",line=dict(color=color,dash=dash,width=2)))
def control_lines(fig,c,u,l,n):
 hline(fig,c,"Center Line","#15803d",n,"dash"); hline(fig,u,"UCL","#dc2626",n); hline(fig,l,"LCL","#dc2626",n)
def spec_lines(fig,lsl,usl,n):
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
def write_specs(df,sha,message):
 content=base64.b64encode(df[SPEC_COLUMNS].to_csv(index=False).encode()).decode(); body={"message":message,"content":content,"branch":st.secrets.get("GITHUB_BRANCH","main")}
 if sha: body["sha"]=sha
 r=requests.put(gh_url(SPEC_PATH),headers=gh_headers(),json=body,timeout=30); r.raise_for_status()
def save_spec(dep,form,param,lsl,usl):
 df,sha=read_specs(); mask=df["Plant"].astype(str).eq(st.session_state.plant)&df["Department"].astype(str).eq(dep)&df["Form ID"].astype(str).eq(form["id"])&df["Parameter ID"].astype(str).eq(param["id"]); df=df.loc[~mask]
 row={"Plant":st.session_state.plant,"Department":dep,"Form ID":form["id"],"Parameter ID":param["id"],"Parameter":param["label"],"LSL":lsl,"USL":usl,"Updated At":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}; write_specs(pd.concat([df,pd.DataFrame([row])],ignore_index=True),sha,f"Update specification limits for {param['label']}")
def get_spec(dep,form,param):
 try: df,_=read_specs()
 except Exception: return None,None
 x=df[df["Plant"].astype(str).eq(st.session_state.plant)&df["Department"].astype(str).eq(dep)&df["Form ID"].astype(str).eq(form["id"])&df["Parameter ID"].astype(str).eq(param["id"])]
 if x.empty: return None,None
 row=x.iloc[-1]; l=pd.to_numeric(row["LSL"],errors="coerce"); u=pd.to_numeric(row["USL"],errors="coerce"); return (None if pd.isna(l) else float(l)),(None if pd.isna(u) else float(u))

def normalized(form,d,shift,vals,rid,created):
 return [{"Record ID":rid,"Plant":st.session_state.plant,"Department":st.session_state.department,"Form ID":form["id"],"Form Title":form["title"],"Inspection Date":str(d),"Shift":shift,"Parameter ID":p["id"],"Parameter":p["label"],"Value":vals.get(p["id"],"") if p["type"]=="number" else "","Text Value":"" if p["type"]=="number" else vals.get(p["id"],""),"Unit":p.get("unit",""),"Created At":created} for p in form["parameters"] if visible(p,vals)]
def template(form):
 cols=["Inspection Date","Shift"]+[p["label"] for p in form["parameters"]]; row={c:"" for c in cols}; row.update({"Inspection Date":date.today().isoformat(),"Shift":"Shift A"})
 for p in form["parameters"]:
  if p["type"]=="choice": row[p["label"]]=p["options"][0]
 out=io.BytesIO()
 with pd.ExcelWriter(out,engine="openpyxl") as w:
  pd.DataFrame([row],columns=cols).to_excel(w,sheet_name="Quality Entry",index=False); pd.DataFrame([["Rule","One row equals one complete inspection"],["Valid Shifts",", ".join(SHIFTS)]],columns=["Item","Instruction"]).to_excel(w,sheet_name="Instructions",index=False)
 return out.getvalue()
def parse_upload(file,form):
 df=pd.read_csv(file) if file.name.lower().endswith(".csv") else pd.read_excel(file,sheet_name="Quality Entry",engine="openpyxl"); df=df.dropna(how="all"); required=["Inspection Date","Shift"]+[p["label"] for p in form["parameters"]]; missing=[c for c in required if c not in df]
 if missing: raise ValueError("Missing columns: "+", ".join(missing))
 result=[]; errors=[]
 for i,row in df.iterrows():
  n=i+2; d=pd.to_datetime(row["Inspection Date"],errors="coerce"); shift="" if pd.isna(row["Shift"]) else str(row["Shift"]).strip(); vals={p["id"]:("" if pd.isna(row[p["label"]]) else row[p["label"]]) for p in form["parameters"]}
  if pd.isna(d): errors.append(f"Row {n}: invalid date")
  if shift not in SHIFTS: errors.append(f"Row {n}: invalid shift")
  for p in form["parameters"]:
   if not visible(p,vals): continue
   v=vals[p["id"]]
   if p.get("required") and v=="": errors.append(f"Row {n}: {p['label']} is required")
   if p["type"]=="number" and v!="":
    x=pd.to_numeric(v,errors="coerce")
    if pd.isna(x): errors.append(f"Row {n}: {p['label']} must be numeric")
    else: vals[p["id"]]=float(x)
   if p["type"]=="choice" and v not in p["options"]: errors.append(f"Row {n}: invalid {p['label']}")
  result.append((d,shift,vals))
 if errors: raise ValueError("\n".join(errors[:25]))
 return result
def records(dep,form):
 df,_=read_data(); return df[df["Plant"].astype(str).eq(st.session_state.plant)&df["Department"].astype(str).eq(dep)&df["Form ID"].astype(str).eq(form["id"])].copy()
def wide(df,form):
 if df.empty: return pd.DataFrame()
 base_cols=["Record ID","Plant","Department","Form Title","Inspection Date","Shift","Created At"]; base=df.groupby("Record ID",as_index=False).first()[base_cols]; df=df.copy(); df["Export Value"]=df["Value"].where(df["Value"].notna()&df["Value"].astype(str).ne(""),df["Text Value"]); pivot=df.pivot_table(index="Record ID",columns="Parameter",values="Export Value",aggfunc="first").reset_index(); out=base.merge(pivot,on="Record ID",how="left"); return out[base_cols+[p["label"] for p in form["parameters"] if p["label"] in out.columns]]
def xlsx(df,sheet="Data"):
 out=io.BytesIO()
 with pd.ExcelWriter(out,engine="openpyxl") as w: df.to_excel(w,sheet_name=sheet[:31],index=False)
 return out.getvalue()

def choices(form):
 groups={}
 for p in form["parameters"]:
  if p.get("chart_group"): groups.setdefault(p["chart_group"],[]).append(p)
 singles=[p for p in form["parameters"] if p.get("chart_type")=="imr"]
 return groups,singles,[p["label"] for p in singles]+list(groups)
def chart_result(df,form,selection):
 groups,singles,_=choices(form)
 if selection in groups:
  ps=groups[selection]; pivot=df[df["Parameter ID"].isin([p["id"] for p in ps])].pivot_table(index="Record ID",columns="Parameter ID",values="Value",aggfunc="first").reindex(columns=[p["id"] for p in ps]); return xbar_r(pivot),{"id":f"group_{slug(selection)}","label":selection},True
 p=next(p for p in singles if p["label"]==selection); s=pd.to_numeric(df.loc[df["Parameter ID"].eq(p["id"]),"Value"],errors="coerce"); return imr(s),p,False
def charts(result,selection,grouped,lsl=None,usl=None):
 values,c,u,l,ranges,rc,ru,rl=result; f1=go.Figure(go.Scatter(x=list(range(1,len(values)+1)),y=values,mode="lines+markers",name=selection)); control_lines(f1,c,u,l,len(values)); spec_lines(f1,lsl,usl,len(values)); f1.update_layout(title=("X-bar Chart: " if grouped else "Individuals Chart: ")+selection,xaxis_title="Observation",yaxis_title="Value"); f2=go.Figure(go.Scatter(x=list(range(1,len(ranges)+1)),y=ranges,mode="lines+markers",name="Range")); control_lines(f2,rc,ru,rl,len(ranges)); f2.update_layout(title=("R Chart: " if grouped else "Moving Range Chart: ")+selection,xaxis_title="Observation",yaxis_title="Range"); return f1,f2
def capability(result,grouped):
 values,_,_,_,_,rbar,_,_=result; sigma=float(rbar)/(3.407 if grouped else 1.128); return float(pd.Series(values).mean()),sigma

def operator_page():
 st.markdown(f"<div class='page-hero'><h1>🧪 Operator Quality Data Entry</h1><p>{st.session_state.plant} · {st.session_state.department}</p></div>",unsafe_allow_html=True); forms=CONFIG["departments"][st.session_state.department]["forms"]; form=st.selectbox("Quality Check",forms,format_func=lambda x:x["title"]); m,u,d=st.tabs(["✍️ Manual Entry","📥 Excel Upload","⬇ Download Data"])
 with m:
  dt=st.date_input("Inspection Date *",date.today(),key="md"+form["id"]); shift=st.selectbox("Shift *",SHIFTS,key="ms"+form["id"]); vals={}
  for p in form["parameters"]:
   if visible(p,vals): vals[p["id"]]=widget(p,"m"+form["id"]+p["id"])
  if st.button("Save Manual Entry",type="primary",use_container_width=True):
   miss=[p["label"] for p in form["parameters"] if visible(p,vals) and p.get("required") and (vals.get(p["id"]) is None or isinstance(vals.get(p["id"]),str) and not vals.get(p["id"]).strip())]
   invalid_optional=[]
   for p in form["parameters"]:
    value=vals.get(p["id"],"")
    if p["type"]=="number" and not p.get("required") and value!="":
     try: vals[p["id"]]=float(value)
     except (TypeError,ValueError): invalid_optional.append(p["label"])
   if miss: st.error("Required fields missing: "+", ".join(miss))
   elif invalid_optional: st.error("Enter a numeric value or leave blank: "+", ".join(invalid_optional))
   else:
    rid="QC-"+datetime.now().strftime("%Y%m%d%H%M%S%f")
    try: append_rows(normalized(form,dt,shift,vals,rid,datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"Add quality check "+rid); st.success("Saved: "+rid)
    except Exception as e: st.error(f"Save failed: {e}")
 with u:
  st.download_button("Download Blank Excel Template",template(form),f"{form['id']}_template.xlsx",use_container_width=True); file=st.file_uploader("Upload completed Excel or CSV",type=["xlsx","csv"],key="up"+form["id"])
  if file and st.button("Validate and Save Uploaded Rows",type="primary",use_container_width=True):
   try:
    parsed=parse_upload(file,form); rows=[]
    for dt,shift,vals in parsed:
     rid="QC-"+datetime.now().strftime("%Y%m%d%H%M%S%f"); rows+=normalized(form,dt.date(),shift,vals,rid,datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    append_rows(rows,f"Add {len(parsed)} uploaded quality checks"); st.success(f"{len(parsed)} records uploaded.")
   except Exception as e: st.error(f"Upload failed: {e}")
 with d:
  try: out=wide(records(st.session_state.department,form),form)
  except Exception as e: st.warning(str(e)); out=pd.DataFrame()
  if out.empty: st.info("No saved records available.")
  else:
   a,b=st.columns(2); a.download_button("Download Entered Data as Excel",xlsx(out),f"{form['id']}_data.xlsx",use_container_width=True); b.download_button("Download Entered Data as CSV",out.to_csv(index=False).encode("utf-8-sig"),f"{form['id']}_data.csv",use_container_width=True)

def control_page():
 st.markdown(f"<div class='page-hero'><h1>📈 Parameter Control Charts</h1><p>{st.session_state.plant} plant</p></div>",unsafe_allow_html=True); a,b=st.columns(2); dep=a.selectbox("Department",DEPARTMENTS,key="cdep"); forms=CONFIG["departments"][dep]["forms"]; form=b.selectbox("Quality Check",forms,format_func=lambda x:x["title"],key="cform")
 try: df=records(dep,form)
 except Exception as e: st.error(str(e)); return
 if df.empty: st.info("No data available."); return
 _,_,opts=choices(form); sel=st.selectbox("Parameter / Group",opts,key="cparam"); result,param,grouped=chart_result(df,form,sel)
 if not result: st.info("At least two readings or two complete subgroups are required."); return
 lsl,usl=get_spec(dep,form,param); f1,f2=charts(result,sel,grouped,lsl,usl); st.plotly_chart(f1,use_container_width=True); st.plotly_chart(f2,use_container_width=True); mean,sigma=capability(result,grouped)
 if lsl is not None and usl is not None and sigma>0:
  cp=(usl-lsl)/(6*sigma); cpk=min((usl-mean)/(3*sigma),(mean-lsl)/(3*sigma)); c1,c2,c3,c4=st.columns(4); c1.metric("LSL",f"{lsl:.3f}"); c2.metric("USL",f"{usl:.3f}"); c3.metric("Cp",f"{cp:.3f}"); c4.metric("Cpk",f"{cpk:.3f}")
 else: st.info("Add both USL and LSL in Specifications & Capability to display Cp and Cpk.")
 out=wide(df,form); d1,d2,d3,d4=st.columns(4); d1.download_button("SPC Data Excel",xlsx(out),f"{form['id']}_spc.xlsx",use_container_width=True); d2.download_button("SPC Data CSV",out.to_csv(index=False).encode("utf-8-sig"),f"{form['id']}_spc.csv",use_container_width=True); d3.download_button("Main Chart HTML",pio.to_html(f1,full_html=True,include_plotlyjs="cdn").encode(),f"{slug(sel)}_main.html",use_container_width=True); d4.download_button("Range Chart HTML",pio.to_html(f2,full_html=True,include_plotlyjs="cdn").encode(),f"{slug(sel)}_range.html",use_container_width=True)

def spec_downloads(df,dep,form):
 selected=df[df["Plant"].astype(str).eq(st.session_state.plant)&df["Department"].astype(str).eq(dep)&df["Form ID"].astype(str).eq(form["id"])].copy(); st.markdown("<div class='card'><b>⬇ Download saved specification limits</b></div>",unsafe_allow_html=True)
 if selected.empty: st.info("No USL/LSL values have been saved for this selection."); return
 selected=selected[SPEC_COLUMNS].sort_values(["Parameter","Updated At"],[True,False]); a,b=st.columns(2); a.download_button("Download Specification Limits as Excel",xlsx(selected,"Specification Limits"),f"{slug(st.session_state.plant)}_{slug(dep)}_{form['id']}_spec_limits.xlsx",use_container_width=True); b.download_button("Download Specification Limits as CSV",selected.to_csv(index=False).encode("utf-8-sig"),f"{slug(st.session_state.plant)}_{slug(dep)}_{form['id']}_spec_limits.csv",use_container_width=True)
def spec_page():
 st.markdown("<div class='page-hero'><h1>🎯 Specifications & Capability</h1><p>Add USL/LSL, view updated charts and calculate Cp/Cpk</p></div>",unsafe_allow_html=True); a,b=st.columns(2); dep=a.selectbox("Department",DEPARTMENTS,key="sdep"); forms=CONFIG["departments"][dep]["forms"]; form=b.selectbox("Quality Check",forms,format_func=lambda x:x["title"],key="sform"); groups,singles,opts=choices(form); sel=st.selectbox("Parameter / Group",opts,key="sparam"); param={"id":f"group_{slug(sel)}","label":sel} if sel in groups else next(p for p in singles if p["label"]==sel); old_lsl,old_usl=get_spec(dep,form,param); st.markdown("<div class='card'><b>Specification entry</b><br><small>Leave both blank if no specification is available.</small></div>",unsafe_allow_html=True); c1,c2=st.columns(2); lt=c1.text_input("LSL",value="" if old_lsl is None else str(old_lsl)); ut=c2.text_input("USL",value="" if old_usl is None else str(old_usl))
 if st.button("Save USL / LSL",type="primary",use_container_width=True):
  try:
   l=None if not lt.strip() else float(lt); u=None if not ut.strip() else float(ut)
   if l is not None and u is not None and l>=u: raise ValueError("LSL must be lower than USL.")
   save_spec(dep,form,param,l,u); st.success("Specification limits saved."); st.rerun()
  except Exception as e: st.error(str(e))
 try: specs,_=read_specs(); spec_downloads(specs,dep,form)
 except Exception as e: st.warning(f"Specification download unavailable: {e}")
 try: df=records(dep,form)
 except Exception as e: st.error(str(e)); return
 if df.empty: st.info("No process data available."); return
 result,param,grouped=chart_result(df,form,sel)
 if not result: st.info("At least two readings or two complete subgroups are required."); return
 lsl,usl=get_spec(dep,form,param); f1,f2=charts(result,sel,grouped,lsl,usl); st.plotly_chart(f1,use_container_width=True); st.plotly_chart(f2,use_container_width=True); mean,sigma=capability(result,grouped)
 if lsl is None or usl is None: st.warning("Cp and Cpk are not available. Please add both USL and LSL above.")
 elif sigma<=0: st.warning("Cp and Cpk cannot be calculated because process variation is zero.")
 else:
  cp=(usl-lsl)/(6*sigma); cpk=min((usl-mean)/(3*sigma),(mean-lsl)/(3*sigma)); m1,m2,m3,m4,m5=st.columns(5); m1.metric("Mean",f"{mean:.3f}"); m2.metric("Sigma",f"{sigma:.3f}"); m3.metric("Cp",f"{cp:.3f}"); m4.metric("Cpk",f"{cpk:.3f}"); m5.metric("Specification",f"{lsl:.3f} to {usl:.3f}")

def login():
 st.markdown("""<div class='login-hero'><span class='hero-kicker'>◆ Smart Manufacturing Quality</span><h1>Quality Parameter Control</h1><p>Secure digital quality checks, disciplined traceability and real-time statistical process control.</p><div class='feature-row'><div class='feature'><b>🧪 Digital Inspections</b>Structured entry</div><div class='feature'><b>📊 Live SPC</b>Control charts</div><div class='feature'><b>🎯 Capability</b>Cp and Cpk</div></div></div><div class='login-title'><h3>Welcome back</h3><p>Select the plant and enter the authorized password.</p></div>""",unsafe_allow_html=True); _,c,_=st.columns([1,1.35,1])
 with c:
  with st.form("login"):
   plant=st.selectbox("Plant",PLANTS); pw=st.text_input("Plant Password",type="password")
   if st.form_submit_button("Continue securely →",use_container_width=True):
    if pw==st.secrets.get("plant_passwords",{}).get(slug(plant)): st.session_state.update(plant=plant,plant_ok=True); st.rerun()
    else: st.error("Incorrect plant password.")
def main():
 if not st.session_state.get("plant_ok"): login(); st.stop()
 with st.sidebar:
  st.success("Plant: "+st.session_state.plant)
  if st.button("Logout",use_container_width=True): st.session_state.clear(); st.rerun()
 module=st.radio("Module",["Operator Data Entry","Control Chart Analysis","Specifications & Capability"],horizontal=True)
 if module=="Control Chart Analysis": control_page(); return
 if module=="Specifications & Capability": spec_page(); return
 if not st.session_state.get("department_ok"):
  st.markdown(f"<div class='page-hero'><h1>🔐 Department Access</h1><p>{st.session_state.plant} plant</p></div>",unsafe_allow_html=True); _,c,_=st.columns([1,1.35,1])
  with c:
   with st.form("dept"):
    dep=st.selectbox("Department",DEPARTMENTS); pw=st.text_input("Department Password",type="password")
    if st.form_submit_button("Open department →",use_container_width=True):
     key=f"{slug(st.session_state.plant)}_{slug(dep)}"; expected=st.secrets.get("department_passwords",{}).get(key,st.secrets.get("DEFAULT_DEPARTMENT_PASSWORD","Dept@123"))
     if pw==expected: st.session_state.update(department=dep,department_ok=True); st.rerun()
     else: st.error("Incorrect department password.")
  st.stop()
 operator_page()
main()
