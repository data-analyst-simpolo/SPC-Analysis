import base64, io, json, re
from datetime import date, datetime
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import requests
import streamlit as st
from github_store import append_rows, read_data
from spc import imr

st.set_page_config(page_title="Quality Parameter Control", page_icon="🏭", layout="wide", initial_sidebar_state="collapsed")
CFG=json.loads(Path("config/forms.json").read_text(encoding="utf-8"))
for dept in CFG.get("departments",{}).values():
    for form in dept.get("forms",[]):
        for p in form.get("parameters",[]): p["required"]=False
PLANTS=CFG["plants"]; DEPTS=list(CFG["departments"]); SHIFTS=["Shift A","Shift B","Shift C","Shift R"]
SPEC_PATH="data/spec_limits.csv"; SPEC_COLS=["Plant","Department","Form ID","Parameter ID","Parameter","LSL","USL","Updated At"]
# d2 and d3 constants for subgroup sizes 2-14
D2={2:1.128,3:1.693,4:2.059,5:2.326,6:2.534,7:2.704,8:2.847,9:2.970,10:3.078,11:3.173,12:3.258,13:3.336,14:3.407}
D3={2:.853,3:.888,4:.880,5:.864,6:.848,7:.833,8:.820,9:.808,10:.797,11:.787,12:.778,13:.770,14:.763}

st.markdown("""<style>
.stApp{background:linear-gradient(135deg,#f7fff9,#edf7f0)}.block-container{max-width:1180px;padding-top:1.7rem}#MainMenu,footer{visibility:hidden}
.hero{padding:1.5rem 1.8rem;border-radius:22px;background:linear-gradient(125deg,#123f28,#15803d,#22a447);color:white;margin-bottom:1rem;box-shadow:0 15px 38px rgba(20,83,45,.18)}.hero h1{margin:0}.hero p{margin:.35rem 0 0;opacity:.9}
div[data-testid="stForm"]{background:white;border:1px solid #d9e8de;border-radius:20px;padding:1.25rem;box-shadow:0 12px 30px rgba(20,83,45,.08)}
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{border-radius:11px;min-height:44px;font-weight:700}.stFormSubmitButton>button{background:#15803d!important;color:white!important;border:0!important}
.card{padding:.9rem 1rem;background:white;border:1px solid #d9e8de;border-radius:14px;margin:.7rem 0}
</style>""",unsafe_allow_html=True)

def slug(v): return re.sub(r"[^a-z0-9]+","_",str(v).lower()).strip("_")
def clean(v): return str(v or "").strip()
def visible(p,vals):
    r=p.get("show_if"); return not r or vals.get(r["field"])==r["equals"]
def field(p,key):
    label=p["label"]+" (Optional)"
    if p["type"]=="choice": return st.selectbox(label,[""]+p["options"],format_func=lambda x:"Select an option (optional)" if x=="" else x,key=key)
    if p["type"]=="number":
        raw=st.text_input(label,placeholder="Leave blank if not measured",key=key)
        if not raw.strip(): return ""
        try:return float(raw)
        except:return raw
    if p["type"]=="textarea": return st.text_area(label,key=key)
    return st.text_input(label,key=key)

def rows_for(form,dt,shift,vals,rid):
    now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"); rows=[]
    for p in form["parameters"]:
        if not visible(p,vals): continue
        v=vals.get(p["id"],"")
        if v=="": continue
        rows.append({"Record ID":rid,"Plant":st.session_state.plant,"Department":st.session_state.department,"Form ID":form["id"],"Form Title":form["title"],"Inspection Date":str(dt),"Shift":shift,"Parameter ID":p["id"],"Parameter":p["label"],"Value":v if p["type"]=="number" else "","Text Value":"" if p["type"]=="number" else v,"Unit":p.get("unit",""),"Created At":now})
    return rows

def records(dep,form):
    df,_=read_data(); return df[df["Plant"].astype(str).eq(st.session_state.plant)&df["Department"].astype(str).eq(dep)&df["Form ID"].astype(str).eq(form["id"])].copy()
def wide(df,form):
    if df.empty:return pd.DataFrame()
    base=["Record ID","Plant","Department","Form Title","Inspection Date","Shift","Created At"]; b=df.groupby("Record ID",as_index=False).first()[base]; x=df.copy(); x["Export"]=x["Value"].where(x["Value"].notna()&x["Value"].astype(str).ne(""),x["Text Value"]); p=x.pivot_table(index="Record ID",columns="Parameter",values="Export",aggfunc="first").reset_index(); out=b.merge(p,on="Record ID",how="left"); return out[base+[q["label"] for q in form["parameters"] if q["label"] in out.columns]]
def xlsx(df,sheet="Data"):
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as w: df.to_excel(w,sheet_name=sheet[:31],index=False)
    return out.getvalue()
def template(form):
    cols=["Inspection Date","Shift"]+[p["label"] for p in form["parameters"]]; row={c:"" for c in cols}; row.update({"Inspection Date":date.today().isoformat(),"Shift":"Shift A"}); return xlsx(pd.DataFrame([row],columns=cols),"Quality Entry")
def parse_upload(file,form):
    df=pd.read_csv(file) if file.name.lower().endswith(".csv") else pd.read_excel(file,sheet_name="Quality Entry",engine="openpyxl"); df=df.dropna(how="all"); needed=["Inspection Date","Shift"]+[p["label"] for p in form["parameters"]]; missing=[c for c in needed if c not in df]
    if missing: raise ValueError("Missing columns: "+", ".join(missing))
    output=[]; errors=[]
    for i,row in df.iterrows():
        dt=pd.to_datetime(row["Inspection Date"],errors="coerce"); shift="" if pd.isna(row["Shift"]) else str(row["Shift"]).strip(); vals={p["id"]:("" if pd.isna(row[p["label"]]) else row[p["label"]]) for p in form["parameters"]}
        if pd.isna(dt): errors.append(f"Row {i+2}: invalid date")
        if shift not in SHIFTS: errors.append(f"Row {i+2}: invalid shift")
        for p in form["parameters"]:
            v=vals[p["id"]]
            if p["type"]=="number" and v!="":
                n=pd.to_numeric(v,errors="coerce")
                if pd.isna(n): errors.append(f"Row {i+2}: {p['label']} must be numeric")
                else: vals[p["id"]]=float(n)
            if p["type"]=="choice" and v!="" and v not in p["options"]: errors.append(f"Row {i+2}: invalid {p['label']}")
        output.append((dt,shift,vals))
    if errors: raise ValueError("\n".join(errors[:25]))
    return output

# GitHub-backed specification limits
def ghh(): return {"Authorization":f"Bearer {st.secrets['GITHUB_TOKEN']}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
def ghu(): return f"https://api.github.com/repos/{st.secrets['GITHUB_OWNER']}/{st.secrets['GITHUB_REPO']}/contents/{SPEC_PATH}"
def read_specs():
    r=requests.get(ghu(),headers=ghh(),params={"ref":st.secrets.get("GITHUB_BRANCH","main")},timeout=30)
    if r.status_code==404:return pd.DataFrame(columns=SPEC_COLS),None
    r.raise_for_status(); p=r.json()
    try:df=pd.read_csv(io.BytesIO(base64.b64decode(p["content"])))
    except pd.errors.EmptyDataError:df=pd.DataFrame(columns=SPEC_COLS)
    for c in SPEC_COLS:
        if c not in df:df[c]=""
    return df[SPEC_COLS],p["sha"]
def save_spec(dep,form,p,lsl,usl):
    df,sha=read_specs(); m=df["Plant"].astype(str).eq(st.session_state.plant)&df["Department"].astype(str).eq(dep)&df["Form ID"].astype(str).eq(form["id"])&df["Parameter ID"].astype(str).eq(p["id"]); df=df.loc[~m]; row={"Plant":st.session_state.plant,"Department":dep,"Form ID":form["id"],"Parameter ID":p["id"],"Parameter":p["label"],"LSL":lsl,"USL":usl,"Updated At":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}; df=pd.concat([df,pd.DataFrame([row])],ignore_index=True); body={"message":f"Update limits for {p['label']}","content":base64.b64encode(df.to_csv(index=False).encode()).decode(),"branch":st.secrets.get("GITHUB_BRANCH","main")};
    if sha:body["sha"]=sha
    r=requests.put(ghu(),headers=ghh(),json=body,timeout=30);r.raise_for_status()
def get_spec(dep,form,p):
    try:df,_=read_specs()
    except:return None,None
    x=df[df["Plant"].astype(str).eq(st.session_state.plant)&df["Department"].astype(str).eq(dep)&df["Form ID"].astype(str).eq(form["id"])&df["Parameter ID"].astype(str).eq(p["id"])]
    if x.empty:return None,None
    l=pd.to_numeric(x.iloc[-1]["LSL"],errors="coerce");u=pd.to_numeric(x.iloc[-1]["USL"],errors="coerce");return (None if pd.isna(l) else float(l)),(None if pd.isna(u) else float(u))

def chart_options(form):
    groups={}
    for p in form["parameters"]:
        if p.get("chart_group"):groups.setdefault(p["chart_group"],[]).append(p)
    singles=[p for p in form["parameters"] if p.get("chart_type")=="imr"]
    return groups,singles,[p["label"] for p in singles]+list(groups)

SIZE_RULES = [
    ("600 X 1200", 12),
    ("1200 X 1800", 12),
    ("1200 X 2400", 8),
]

def record_text_map(df, parameter_id):
    part=df[df["Parameter ID"].astype(str).eq(parameter_id)][["Record ID","Text Value"]].copy()
    return dict(zip(part["Record ID"].astype(str),part["Text Value"].fillna("").astype(str)))

def fixed_size_group_result(df,params,size_label,required_n):
    """Create a fixed-subgroup X-bar/R result for one tile size.

    600 X 1200 and 1200 X 1800 use readings 1-12.
    1200 X 2400 uses readings 1-8.
    Limits remain constant because subgroup size is fixed within each chart.
    """
    size_map=record_text_map(df,"tile_size")
    record_ids=[rid for rid,value in size_map.items() if clean(value).upper()==size_label.upper()]
    if not record_ids:return None
    selected_params=params[:required_n]
    pv=df[df["Record ID"].astype(str).isin(record_ids)&df["Parameter ID"].isin([p["id"] for p in selected_params])].pivot_table(index="Record ID",columns="Parameter ID",values="Value",aggfunc="first").reindex(columns=[p["id"] for p in selected_params])
    pv=pv.apply(pd.to_numeric,errors="coerce").dropna(how="any")
    if len(pv)<2:return None
    meta=df[df["Record ID"].astype(str).isin(pv.index.astype(str))].groupby("Record ID",as_index=False).first().set_index("Record ID")
    order=sorted(pv.index,key=lambda rid:(str(meta.loc[rid,"Inspection Date"]) if rid in meta.index else "",str(meta.loc[rid,"Created At"]) if rid in meta.index else "",str(rid)))
    pv=pv.loc[order]
    means=pv.mean(axis=1); ranges=pv.max(axis=1)-pv.min(axis=1); grand=float(means.mean()); rbar=float(ranges.mean()); sigma=rbar/D2[required_n]
    ucl=grand+3*sigma/(required_n**0.5); lcl=grand-3*sigma/(required_n**0.5)
    rcenter=rbar; rucl=(D2[required_n]+3*D3[required_n])*sigma; rlcl=max(0,(D2[required_n]-3*D3[required_n])*sigma)
    press_map=record_text_map(df,"press_no"); batch_map=record_text_map(df,"batch_number")
    labels=[]; hover=[]
    for rid in order:
        raw_date=str(meta.loc[rid,"Inspection Date"]) if rid in meta.index else ""
        dt=pd.to_datetime(raw_date,errors="coerce")
        label=dt.strftime("%d-%b-%Y") if not pd.isna(dt) else raw_date
        labels.append(label)
        hover.append(f"Date: {label}<br>Press: {press_map.get(str(rid),'')}<br>Batch: {batch_map.get(str(rid),'')}<br>Readings used: {required_n}")
    return {"values":means,"center":grand,"ucl":ucl,"lcl":lcl,"ranges":ranges,"rcenter":rcenter,"rucl":rucl,"rlcl":rlcl,"sizes":pd.Series([required_n]*len(means)),"sigma":sigma,"labels":labels,"hover":hover,"size_label":size_label,"required_n":required_n}

def single_result(df,p):
    z=imr(pd.to_numeric(df.loc[df["Parameter ID"].eq(p["id"]),"Value"],errors="coerce"));
    if not z:return None
    vals,c,u,l,r,rc,ru,rl=z
    return {"values":vals,"center":c,"ucl":u,"lcl":l,"ranges":r,"rcenter":rc,"rucl":ru,"rlcl":rl,"sizes":pd.Series([1]*len(vals)),"sigma":float(rc)/1.128}
def chart_result(df,form,sel):
    groups,singles,_=chart_options(form)
    if sel in groups:return variable_group_result(df,groups[sel]),{"id":"group_"+slug(sel),"label":sel},True
    p=next(p for p in singles if p["label"]==sel);return single_result(df,p),p,False
def seq(v,n):
    if isinstance(v,pd.Series):return list(v.astype(float))
    if hasattr(v,"__len__") and not isinstance(v,(str,bytes)):return list(v)
    return [float(v)]*n
def addline(fig,y,name,color,n,dash="dot"):fig.add_trace(go.Scatter(x=list(range(1,n+1)),y=seq(y,n),name=name,mode="lines",line=dict(color=color,dash=dash)))
def figures(r,sel,grouped,lsl,usl,title_suffix=""):
    vals=list(r["values"]); n=len(vals); labels=r.get("labels",[str(i) for i in range(1,n+1)]); hover=r.get("hover",[f"Subgroup size: {x}" for x in list(r["sizes"])])
    x=list(range(1,n+1))
    f1=go.Figure(go.Scatter(x=x,y=vals,mode="lines+markers",name=sel,text=hover,hovertemplate="%{text}<br>Average: %{y:.4f}<extra></extra>"))
    for y,name,col,d in [(r["center"],"Center","#15803d","dash"),(r["ucl"],"UCL","#dc2626","dot"),(r["lcl"],"LCL","#dc2626","dot")]:addline(f1,y,name,col,n,d)
    if lsl is not None:addline(f1,lsl,"LSL","#f59e0b",n,"dashdot")
    if usl is not None:addline(f1,usl,"USL","#7c3aed",n,"dashdot")
    f1.update_layout(title=("X-bar Chart: " if grouped else "Individuals Chart: ")+sel+title_suffix,xaxis_title="Inspection Date",yaxis_title="Average",xaxis=dict(tickmode="array",tickvals=x,ticktext=labels,tickangle=-35))
    rn=len(r["ranges"]);rx=list(range(1,rn+1));f2=go.Figure(go.Scatter(x=rx,y=list(r["ranges"]),mode="lines+markers",name="Range",text=hover,hovertemplate="%{text}<br>Range: %{y:.4f}<extra></extra>"))
    for y,name,col,d in [(r["rcenter"],"Center","#15803d","dash"),(r["rucl"],"UCL","#dc2626","dot"),(r["rlcl"],"LCL","#dc2626","dot")]:addline(f2,y,name,col,rn,d)
    f2.update_layout(title=("R Chart: " if grouped else "Moving Range Chart: ")+sel+title_suffix,xaxis_title="Inspection Date",yaxis_title="Range",xaxis=dict(tickmode="array",tickvals=rx,ticktext=labels,tickangle=-35));return f1,f2

def department_login():
    st.markdown(f"<div class='hero'><h1>🔐 Department Access</h1><p>{st.session_state.plant} plant</p></div>",unsafe_allow_html=True);_,c,_=st.columns([1,1.6,1])
    with c:
        with st.form("department_login"):
            dep=st.selectbox("Department",DEPTS);pw=st.text_input("Department Password",type="password");ok=st.form_submit_button("Open Department →",use_container_width=True)
        if ok:
            key=f"{slug(st.session_state.plant)}_{slug(dep)}";specific=st.secrets.get("department_passwords",{}).get(key);fallback=st.secrets.get("DEFAULT_DEPARTMENT_PASSWORD")
            if specific is None and fallback is None:st.error(f"Password not configured for: {key}")
            elif clean(pw) in {clean(specific),clean(fallback)}-{""}:st.session_state.update(department=dep,department_ok=True);st.rerun()
            else:st.error("Incorrect department password.")
def operator_page():
    st.markdown(f"<div class='hero'><h1>🧪 Operator Quality Data Entry</h1><p>{st.session_state.plant} · {st.session_state.department}</p></div>",unsafe_allow_html=True);forms=CFG["departments"][st.session_state.department]["forms"];form=st.selectbox("Quality Check",forms,format_func=lambda x:x["title"]);m,u,d=st.tabs(["Manual Entry","Excel Upload","Download Data"])
    with m:
        dt=st.date_input("Inspection Date",date.today());shift=st.selectbox("Shift",SHIFTS);vals={}
        for p in form["parameters"]:
            if visible(p,vals):vals[p["id"]]=field(p,"m"+form["id"]+p["id"])
        if st.button("Save Entry",type="primary",use_container_width=True):
            bad=[]
            for p in form["parameters"]:
                v=vals.get(p["id"],"")
                if p["type"]=="number" and v!="":
                    try:vals[p["id"]]=float(v)
                    except:bad.append(p["label"])
            if bad:st.error("Enter numbers or leave blank: "+", ".join(bad))
            else:
                rid="QC-"+datetime.now().strftime("%Y%m%d%H%M%S%f");rows=rows_for(form,dt,shift,vals,rid)
                if not rows:st.warning("Enter at least one parameter before saving.")
                else:
                    try:append_rows(rows,"Add quality check "+rid);st.success("Saved: "+rid)
                    except Exception as e:st.error(str(e))
    with u:
        st.download_button("Download Blank Excel Template",template(form),f"{form['id']}_template.xlsx",use_container_width=True);file=st.file_uploader("Upload completed Excel or CSV",type=["xlsx","csv"])
        if file and st.button("Validate and Save Uploaded Rows",type="primary",use_container_width=True):
            try:
                parsed=parse_upload(file,form);all_rows=[]
                for dt,shift,vals in parsed:all_rows+=rows_for(form,dt.date(),shift,vals,"QC-"+datetime.now().strftime("%Y%m%d%H%M%S%f"))
                if not all_rows:st.warning("No parameter values found.")
                else:append_rows(all_rows,f"Add {len(parsed)} uploaded checks");st.success(f"{len(parsed)} rows processed.")
            except Exception as e:st.error(str(e))
    with d:
        out=wide(records(st.session_state.department,form),form)
        if out.empty:st.info("No saved records.")
        else:
            a,b=st.columns(2);a.download_button("Download Data as Excel",xlsx(out),f"{form['id']}_data.xlsx",use_container_width=True);b.download_button("Download Data as CSV",out.to_csv(index=False).encode("utf-8-sig"),f"{form['id']}_data.csv",use_container_width=True)
def chart_page(spec=False):
    st.markdown("<div class='hero'><h1>🎯 Specifications & Capability</h1><p>Size-wise fixed-subgroup charts with day-wise observations</p></div>" if spec else "<div class='hero'><h1>📈 Control Chart Analysis</h1><p>Separate day-wise charts for each tile size</p></div>",unsafe_allow_html=True)
    a,b=st.columns(2);dep=a.selectbox("Department",DEPTS,key="sd" if spec else "cd");forms=CFG["departments"][dep]["forms"];form=b.selectbox("Quality Check",forms,format_func=lambda x:x["title"],key="sf" if spec else "cf");df=records(dep,form);groups,singles,opts=chart_options(form);sel=st.selectbox("Parameter / Group",opts,key="sp" if spec else "cp");param={"id":"group_"+slug(sel),"label":sel} if sel in groups else next(p for p in singles if p["label"]==sel)
    if spec:
        ol,ou=get_spec(dep,form,param);x,y=st.columns(2);lt=x.text_input("LSL",value="" if ol is None else str(ol));ut=y.text_input("USL",value="" if ou is None else str(ou))
        if st.button("Save USL / LSL",type="primary",use_container_width=True):
            try:
                l=None if not lt.strip() else float(lt);u=None if not ut.strip() else float(ut)
                if l is not None and u is not None and l>=u:raise ValueError("LSL must be lower than USL.")
                save_spec(dep,form,param,l,u);st.success("Limits saved.");st.rerun()
            except Exception as e:st.error(str(e))
        specs,_=read_specs();selected=specs[specs["Plant"].astype(str).eq(st.session_state.plant)&specs["Department"].astype(str).eq(dep)&specs["Form ID"].astype(str).eq(form["id"])]
        if not selected.empty:
            x,y=st.columns(2);x.download_button("Download Limits as Excel",xlsx(selected,"Specification Limits"),f"{form['id']}_limits.xlsx",use_container_width=True);y.download_button("Download Limits as CSV",selected.to_csv(index=False).encode(),f"{form['id']}_limits.csv",use_container_width=True)
    if df.empty:st.info("No data available.");return
    lsl,usl=get_spec(dep,form,param)
    if sel in groups and form["id"]=="press_green_tile_thickness_bd":
        rendered=0
        for size_label,required_n in SIZE_RULES:
            result=fixed_size_group_result(df,groups[sel],size_label,required_n)
            st.subheader(f"{size_label} | {required_n} readings per inspection")
            if not result:
                st.info(f"At least two inspections of size {size_label}, each with readings 1-{required_n} complete, are required.")
                continue
            f1,f2=figures(result,sel,True,lsl,usl,f" | Size {size_label}");st.plotly_chart(f1,use_container_width=True);st.plotly_chart(f2,use_container_width=True);rendered+=1
            mean=float(pd.Series(result["values"]).mean());sigma=result["sigma"]
            if lsl is not None and usl is not None and sigma>0:
                cp=(usl-lsl)/(6*sigma);cpk=min((usl-mean)/(3*sigma),(mean-lsl)/(3*sigma));c1,c2,c3,c4=st.columns(4);c1.metric("Mean",f"{mean:.3f}");c2.metric("Sigma",f"{sigma:.3f}");c3.metric("Cp",f"{cp:.3f}");c4.metric("Cpk",f"{cpk:.3f}")
            else:st.info("Add both USL and LSL to display Cp and Cpk.")
        if rendered==0:st.warning("No size has two valid fixed-size inspection subgroups yet.")
        return
    result,param,grouped=chart_result(df,form,sel)
    if not result:st.info("At least two readings are required.");return
    f1,f2=figures(result,sel,grouped,lsl,usl);st.plotly_chart(f1,use_container_width=True);st.plotly_chart(f2,use_container_width=True)

def plant_login():
    st.markdown("<div class='hero'><h1>Quality Parameter Control</h1><p>Digital inspections, SPC and capability analysis</p></div>",unsafe_allow_html=True);_,c,_=st.columns([1,1.5,1])
    with c:
        with st.form("plant_login"):
            plant=st.selectbox("Plant",PLANTS);pw=st.text_input("Plant Password",type="password");ok=st.form_submit_button("Continue →",use_container_width=True)
        if ok:
            if clean(pw)==clean(st.secrets.get("plant_passwords",{}).get(slug(plant))):st.session_state.update(plant=plant,plant_ok=True);st.rerun()
            else:st.error("Incorrect plant password.")
def main():
    if not st.session_state.get("plant_ok"):plant_login();st.stop()
    if not st.session_state.get("department_ok"):department_login();st.stop()
    with st.sidebar:
        st.success(f"{st.session_state.plant} · {st.session_state.department}")
        if st.button("Change Department"):st.session_state.pop("department_ok",None);st.session_state.pop("department",None);st.rerun()
        if st.button("Logout"):st.session_state.clear();st.rerun()
    module=st.radio("Module",["Operator Data Entry","Control Chart Analysis","Specifications & Capability"],horizontal=True,label_visibility="collapsed")
    if module=="Operator Data Entry":operator_page()
    elif module=="Control Chart Analysis":chart_page(False)
    else:chart_page(True)
main()
