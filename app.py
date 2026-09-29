import base64
import io
import json
import re
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
CONFIG = json.loads(Path("config/forms.json").read_text(encoding="utf-8"))
PLANTS = CONFIG["plants"]
DEPARTMENTS = list(CONFIG["departments"])
SHIFTS = ["Shift A", "Shift B", "Shift C", "Shift R"]
SPEC_PATH = "data/spec_limits.csv"
SPEC_COLUMNS = ["Plant", "Department", "Form ID", "Parameter ID", "Parameter", "LSL", "USL", "Updated At"]

st.markdown("""
<style>
:root{--green:#166534;--ink:#10231a;--muted:#64748b;--line:#dcebe1}
.stApp{background:radial-gradient(circle at 8% 8%,#dcfce7 0,transparent 23%),linear-gradient(135deg,#f8fffa,#edf7f0)}
.block-container{max-width:1180px;padding-top:2rem;padding-bottom:3rem} #MainMenu,footer{visibility:hidden}.stDeployButton{display:none}
.login-hero{position:relative;overflow:hidden;padding:2.2rem 2.4rem;border-radius:26px;background:linear-gradient(125deg,#123f28,#166534 48%,#16a34a);color:#fff;box-shadow:0 22px 60px rgba(20,83,45,.21);margin:1rem 0 1.4rem}
.login-hero h1{font-size:2.35rem;margin:.85rem 0 .45rem;font-weight:800}.login-hero p{opacity:.88;margin:0}.hero-kicker{display:inline-flex;padding:.35rem .72rem;border:1px solid rgba(255,255,255,.28);border-radius:999px;background:rgba(255,255,255,.10);font-size:.78rem;font-weight:700}
.feature-row{display:grid;grid-template-columns:repeat(3,1fr);gap:.75rem;margin-top:1.35rem}.feature{padding:.8rem 1rem;border-radius:14px;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.13)} .feature b{display:block}
.login-title{text-align:center;margin:.25rem 0 1rem}.login-title h3{margin:0}.login-title p{margin:.25rem 0;color:var(--muted)}
div[data-testid="stForm"]{background:rgba(255,255,255,.94);border:1px solid var(--line);border-radius:22px;padding:1.25rem;box-shadow:0 16px 42px rgba(15,50,30,.09)}
div[data-baseweb="select"]>div,.stTextInput input{background:#f4fbf6!important;border:1px solid #d9eee0!important;border-radius:12px!important;min-height:48px}
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{min-height:46px;border-radius:12px;font-weight:700}.stFormSubmitButton>button{background:linear-gradient(90deg,#166534,#16a34a)!important;color:white!important;border:0!important}
.page-hero{padding:1.35rem 1.5rem;border-radius:19px;background:linear-gradient(125deg,#14532d,#16a34a);color:white;margin-bottom:1rem;box-shadow:0 12px 30px rgba(20,83,45,.16)}.page-hero h1{margin:0;font-size:1.8rem}.page-hero p{margin:.3rem 0 0;opacity:.88}
.download-card,.spec-card{padding:.9rem 1rem;border:1px solid #d9eee0;border-radius:14px;background:#f7fff9;margin:.7rem 0}.trust{text-align:center;margin-top:1rem;color:#6b7f73;font-size:.82rem}
@media(max-width:760px){.block-container{padding:1rem}.login-hero{padding:1.5rem}.feature-row{display:none}}
</style>
""", unsafe_allow_html=True)


def slug(value): return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
def field_visible(field, values):
    rule = field.get("show_if")
    return not rule or values.get(rule["field"]) == rule["equals"]

def render_field(field, key):
    label = field["label"] + (" *" if field.get("required") else "")
    if field["type"] == "choice": return st.selectbox(label, field["options"], key=key)
    if field["type"] == "number": return st.number_input(label, value=0.0, format=f"%.{field.get('decimals',3)}f", key=key)
    if field["type"] == "textarea": return st.text_area(label, key=key)
    return st.text_input(label, key=key)

def add_horizontal_line(fig, value, name, color, count, dash="dot"):
    fig.add_trace(go.Scatter(x=list(range(1, count + 1)), y=[value] * count, name=name, mode="lines", line=dict(color=color, dash=dash, width=2)))

def add_limit_lines(fig, center, ucl, lcl, count):
    add_horizontal_line(fig, center, "Center Line", "#15803d", count, "dash")
    add_horizontal_line(fig, ucl, "UCL", "#dc2626", count)
    add_horizontal_line(fig, lcl, "LCL", "#dc2626", count)

def add_spec_lines(fig, lsl, usl, count):
    if lsl is not None: add_horizontal_line(fig, lsl, "LSL", "#f59e0b", count, "dashdot")
    if usl is not None: add_horizontal_line(fig, usl, "USL", "#7c3aed", count, "dashdot")

def gh_headers():
    return {"Authorization": f"Bearer {st.secrets['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

def gh_url(path):
    return f"https://api.github.com/repos/{st.secrets['GITHUB_OWNER']}/{st.secrets['GITHUB_REPO']}/contents/{path}"

def read_specs():
    response = requests.get(gh_url(SPEC_PATH), headers=gh_headers(), params={"ref": st.secrets.get("GITHUB_BRANCH", "main")}, timeout=30)
    if response.status_code == 404: return pd.DataFrame(columns=SPEC_COLUMNS), None
    response.raise_for_status(); payload = response.json()
    raw = base64.b64decode(payload["content"])
    try: frame = pd.read_csv(io.BytesIO(raw))
    except pd.errors.EmptyDataError: frame = pd.DataFrame(columns=SPEC_COLUMNS)
    for column in SPEC_COLUMNS:
        if column not in frame: frame[column] = ""
    return frame[SPEC_COLUMNS], payload["sha"]

def write_specs(frame, sha, message):
    content = base64.b64encode(frame[SPEC_COLUMNS].to_csv(index=False).encode("utf-8")).decode("utf-8")
    body = {"message": message, "content": content, "branch": st.secrets.get("GITHUB_BRANCH", "main")}
    if sha: body["sha"] = sha
    response = requests.put(gh_url(SPEC_PATH), headers=gh_headers(), json=body, timeout=30)
    response.raise_for_status()

def save_spec(department, form, parameter, lsl, usl):
    specs, sha = read_specs()
    mask = specs["Plant"].astype(str).eq(st.session_state.plant) & specs["Department"].astype(str).eq(department) & specs["Form ID"].astype(str).eq(form["id"]) & specs["Parameter ID"].astype(str).eq(parameter["id"])
    specs = specs.loc[~mask].copy()
    row = {"Plant": st.session_state.plant, "Department": department, "Form ID": form["id"], "Parameter ID": parameter["id"], "Parameter": parameter["label"], "LSL": lsl, "USL": usl, "Updated At": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    specs = pd.concat([specs, pd.DataFrame([row])], ignore_index=True)
    write_specs(specs, sha, f"Update specification limits for {parameter['label']}")

def get_spec(department, form, parameter):
    try: specs, _ = read_specs()
    except Exception: return None, None
    found = specs[specs["Plant"].astype(str).eq(st.session_state.plant) & specs["Department"].astype(str).eq(department) & specs["Form ID"].astype(str).eq(form["id"]) & specs["Parameter ID"].astype(str).eq(parameter["id"])]
    if found.empty: return None, None
    row = found.iloc[-1]
    lsl = pd.to_numeric(row["LSL"], errors="coerce"); usl = pd.to_numeric(row["USL"], errors="coerce")
    return (None if pd.isna(lsl) else float(lsl)), (None if pd.isna(usl) else float(usl))

def normalized_rows(form, inspection_date, shift, values, record_id, created_at):
    rows = []
    for p in form["parameters"]:
        if not field_visible(p, values): continue
        value = values.get(p["id"], "")
        rows.append({"Record ID": record_id, "Plant": st.session_state.plant, "Department": st.session_state.department, "Form ID": form["id"], "Form Title": form["title"], "Inspection Date": str(inspection_date), "Shift": shift, "Parameter ID": p["id"], "Parameter": p["label"], "Value": value if p["type"] == "number" else "", "Text Value": "" if p["type"] == "number" else value, "Unit": p.get("unit", ""), "Created At": created_at})
    return rows

def template_bytes(form):
    columns = ["Inspection Date", "Shift"] + [p["label"] for p in form["parameters"]]
    row = {c: "" for c in columns}; row.update({"Inspection Date": date.today().isoformat(), "Shift": "Shift A"})
    for p in form["parameters"]:
        if p["type"] == "choice": row[p["label"]] = p["options"][0]
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([row], columns=columns).to_excel(writer, sheet_name="Quality Entry", index=False)
        pd.DataFrame([["Rule", "One row equals one complete inspection"], ["Valid Shifts", ", ".join(SHIFTS)]], columns=["Item", "Instruction"]).to_excel(writer, sheet_name="Instructions", index=False)
    return output.getvalue()

def parse_upload(upload, form):
    data = pd.read_csv(upload) if upload.name.lower().endswith(".csv") else pd.read_excel(upload, sheet_name="Quality Entry", engine="openpyxl")
    data = data.dropna(how="all"); required = ["Inspection Date", "Shift"] + [p["label"] for p in form["parameters"]]
    missing = [c for c in required if c not in data.columns]
    if missing: raise ValueError("Missing columns: " + ", ".join(missing))
    result, errors = [], []
    for idx, row in data.iterrows():
        n = idx + 2; d = pd.to_datetime(row["Inspection Date"], errors="coerce"); shift = "" if pd.isna(row["Shift"]) else str(row["Shift"]).strip(); values = {p["id"]: ("" if pd.isna(row[p["label"]]) else row[p["label"]]) for p in form["parameters"]}
        if pd.isna(d): errors.append(f"Row {n}: invalid date")
        if shift not in SHIFTS: errors.append(f"Row {n}: invalid shift")
        for p in form["parameters"]:
            if not field_visible(p, values): continue
            v = values[p["id"]]
            if p.get("required") and v == "": errors.append(f"Row {n}: {p['label']} is required")
            if p["type"] == "number" and v != "":
                x = pd.to_numeric(v, errors="coerce")
                if pd.isna(x): errors.append(f"Row {n}: {p['label']} must be numeric")
                else: values[p["id"]] = float(x)
            if p["type"] == "choice" and v not in p["options"]: errors.append(f"Row {n}: invalid {p['label']}")
        result.append((d, shift, values))
    if errors: raise ValueError("\n".join(errors[:25]))
    return result

def wide_export(data, form):
    if data.empty: return pd.DataFrame()
    base_cols = ["Record ID", "Plant", "Department", "Form Title", "Inspection Date", "Shift", "Created At"]
    base = data.groupby("Record ID", as_index=False).first()[base_cols]
    data = data.copy(); data["Export Value"] = data["Value"].where(data["Value"].notna() & data["Value"].astype(str).ne(""), data["Text Value"])
    pivot = data.pivot_table(index="Record ID", columns="Parameter", values="Export Value", aggfunc="first").reset_index()
    result = base.merge(pivot, on="Record ID", how="left")
    return result[base_cols + [p["label"] for p in form["parameters"] if p["label"] in result.columns]]

def excel_bytes(frame, sheet="Quality Data"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer: frame.to_excel(writer, sheet_name=sheet[:31], index=False)
    return output.getvalue()

def form_records(department, form):
    data, _ = read_data()
    return data[data["Plant"].astype(str).eq(st.session_state.plant) & data["Department"].astype(str).eq(department) & data["Form ID"].astype(str).eq(form["id"])].copy()

def chart_result(filtered, form, selection):
    groups = {}
    for p in form["parameters"]:
        if p.get("chart_group"): groups.setdefault(p["chart_group"], []).append(p)
    singles = [p for p in form["parameters"] if p.get("chart_type") == "imr"]
    if selection in groups:
        params = groups[selection]
        pivot = filtered[filtered["Parameter ID"].isin([p["id"] for p in params])].pivot_table(index="Record ID", columns="Parameter ID", values="Value", aggfunc="first").reindex(columns=[p["id"] for p in params])
        result = xbar_r(pivot)
        representative = {"id": f"group_{slug(selection)}", "label": selection, "chart_group": selection}
        return result, representative, True
    parameter = next(p for p in singles if p["label"] == selection)
    series = pd.to_numeric(filtered.loc[filtered["Parameter ID"].eq(parameter["id"]), "Value"], errors="coerce")
    return imr(series), parameter, False

def capability(result, grouped):
    values, center, _, _, ranges, range_center, _, _ = result
    sigma = (float(range_center) / 3.407) if grouped else (float(range_center) / 1.128)
    return float(pd.Series(values).mean()), sigma

def make_charts(result, selection, grouped, lsl=None, usl=None):
    values, center, ucl, lcl, ranges, rc, ru, rl = result
    fig1 = go.Figure(go.Scatter(x=list(range(1, len(values)+1)), y=values, mode="lines+markers", name=selection))
    add_limit_lines(fig1, center, ucl, lcl, len(values)); add_spec_lines(fig1, lsl, usl, len(values))
    fig1.update_layout(title=("X-bar Chart: " if grouped else "Individuals Chart: ") + selection, xaxis_title="Observation", yaxis_title="Value")
    fig2 = go.Figure(go.Scatter(x=list(range(1, len(ranges)+1)), y=ranges, mode="lines+markers", name="Range"))
    add_limit_lines(fig2, rc, ru, rl, len(ranges)); fig2.update_layout(title=("R Chart: " if grouped else "Moving Range Chart: ") + selection, xaxis_title="Observation", yaxis_title="Range")
    return fig1, fig2

def operator_entry_page():
    st.markdown(f"<div class='page-hero'><h1>🧪 Operator Quality Data Entry</h1><p>{st.session_state.plant} · {st.session_state.department}</p></div>", unsafe_allow_html=True)
    forms = CONFIG["departments"][st.session_state.department]["forms"]; form = st.selectbox("Quality Check", forms, format_func=lambda x: x["title"])
    manual, upload_tab, download = st.tabs(["✍️ Manual Entry", "📥 Excel Upload", "⬇ Download Data"])
    with manual:
        d = st.date_input("Inspection Date *", date.today(), key="md"+form["id"]); shift = st.selectbox("Shift *", SHIFTS, key="ms"+form["id"]); values = {}
        for p in form["parameters"]:
            if field_visible(p, values): values[p["id"]] = render_field(p, "m"+form["id"]+p["id"])
        if st.button("Save Manual Entry", type="primary", use_container_width=True):
            missing = [p["label"] for p in form["parameters"] if field_visible(p, values) and p.get("required") and (values.get(p["id"]) is None or isinstance(values.get(p["id"]), str) and not values.get(p["id"]).strip())]
            if missing: st.error("Required fields missing: " + ", ".join(missing))
            else:
                rid = "QC-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
                try: append_rows(normalized_rows(form, d, shift, values, rid, datetime.now().strftime("%Y-%m-%d %H:%M:%S")), "Add quality check "+rid); st.success("Saved: "+rid)
                except Exception as e: st.error(f"Save failed: {e}")
    with upload_tab:
        st.download_button("Download Blank Excel Template", template_bytes(form), f"{form['id']}_template.xlsx", use_container_width=True)
        file = st.file_uploader("Upload completed Excel or CSV", type=["xlsx","csv"], key="u"+form["id"])
        if file and st.button("Validate and Save Uploaded Rows", type="primary", use_container_width=True):
            try:
                parsed = parse_upload(file, form); rows = []
                for d, shift, values in parsed:
                    rid = "QC-" + datetime.now().strftime("%Y%m%d%H%M%S%f"); rows += normalized_rows(form, d.date(), shift, values, rid, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                append_rows(rows, f"Add {len(parsed)} uploaded quality checks"); st.success(f"{len(parsed)} records uploaded.")
            except Exception as e: st.error(f"Upload failed: {e}")
    with download:
        try: export = wide_export(form_records(st.session_state.department, form), form)
        except Exception as e: st.warning(str(e)); export = pd.DataFrame()
        if export.empty: st.info("No saved records available.")
        else:
            c1,c2=st.columns(2); c1.download_button("Download Entered Data as Excel", excel_bytes(export), f"{form['id']}_data.xlsx", use_container_width=True); c2.download_button("Download Entered Data as CSV", export.to_csv(index=False).encode("utf-8-sig"), f"{form['id']}_data.csv", use_container_width=True)

def control_chart_page():
    st.markdown(f"<div class='page-hero'><h1>📈 Parameter Control Charts</h1><p>{st.session_state.plant} plant</p></div>", unsafe_allow_html=True)
    c1,c2=st.columns(2); department=c1.selectbox("Department", DEPARTMENTS, key="chart_dep"); forms=CONFIG["departments"][department]["forms"]; form=c2.selectbox("Quality Check", forms, format_func=lambda x:x["title"], key="chart_form")
    try: filtered=form_records(department, form)
    except Exception as e: st.error(str(e)); return
    if filtered.empty: st.info("No data available."); return
    groups={}
    for p in form["parameters"]:
        if p.get("chart_group"): groups.setdefault(p["chart_group"],[]).append(p)
    singles=[p for p in form["parameters"] if p.get("chart_type")=="imr"]
    selection=st.selectbox("Parameter / Group", [p["label"] for p in singles]+list(groups), key="chart_param")
    result, parameter, grouped = chart_result(filtered, form, selection)
    if not result: st.info("At least two readings or two complete subgroups are required."); return
    lsl, usl = get_spec(department, form, parameter)
    fig1,fig2=make_charts(result,selection,grouped,lsl,usl); st.plotly_chart(fig1,use_container_width=True); st.plotly_chart(fig2,use_container_width=True)
    mean,sigma=capability(result,grouped)
    if lsl is not None and usl is not None and sigma>0:
        cp=(usl-lsl)/(6*sigma); cpk=min((usl-mean)/(3*sigma),(mean-lsl)/(3*sigma)); a,b,c,d=st.columns(4); a.metric("LSL",f"{lsl:.3f}"); b.metric("USL",f"{usl:.3f}"); c.metric("Cp",f"{cp:.3f}"); d.metric("Cpk",f"{cpk:.3f}")
    else: st.info("Add both USL and LSL in 'Specifications & Capability' to display Cp and Cpk.")
    wide=wide_export(filtered,form); d1,d2,d3,d4=st.columns(4); d1.download_button("SPC Data Excel",excel_bytes(wide),f"{form['id']}_spc.xlsx",use_container_width=True); d2.download_button("SPC Data CSV",wide.to_csv(index=False).encode("utf-8-sig"),f"{form['id']}_spc.csv",use_container_width=True); d3.download_button("Main Chart HTML",pio.to_html(fig1,full_html=True,include_plotlyjs="cdn").encode(),f"{slug(selection)}_main.html",use_container_width=True); d4.download_button("Range Chart HTML",pio.to_html(fig2,full_html=True,include_plotlyjs="cdn").encode(),f"{slug(selection)}_range.html",use_container_width=True)

def specification_page():
    st.markdown(f"<div class='page-hero'><h1>🎯 Specifications & Capability</h1><p>Add USL/LSL, view updated charts and calculate Cp/Cpk</p></div>", unsafe_allow_html=True)
    c1,c2=st.columns(2); department=c1.selectbox("Department",DEPARTMENTS,key="spec_dep"); forms=CONFIG["departments"][department]["forms"]; form=c2.selectbox("Quality Check",forms,format_func=lambda x:x["title"],key="spec_form")
    groups={}
    for p in form["parameters"]:
        if p.get("chart_group"): groups.setdefault(p["chart_group"],[]).append(p)
    singles=[p for p in form["parameters"] if p.get("chart_type")=="imr"]
    choices=[p["label"] for p in singles]+list(groups); selection=st.selectbox("Parameter / Group",choices,key="spec_param")
    parameter = {"id":f"group_{slug(selection)}","label":selection,"chart_group":selection} if selection in groups else next(p for p in singles if p["label"]==selection)
    old_lsl,old_usl=get_spec(department,form,parameter)
    st.markdown("<div class='spec-card'><b>Specification entry</b><br><small>Leave both fields blank if no specification is available. The control chart will continue without USL/LSL.</small></div>",unsafe_allow_html=True)
    a,b=st.columns(2); lsl_text=a.text_input("LSL",value="" if old_lsl is None else str(old_lsl),placeholder="Enter lower specification limit"); usl_text=b.text_input("USL",value="" if old_usl is None else str(old_usl),placeholder="Enter upper specification limit")
    if st.button("Save USL / LSL",type="primary",use_container_width=True):
        try:
            lsl=None if not lsl_text.strip() else float(lsl_text); usl=None if not usl_text.strip() else float(usl_text)
            if lsl is not None and usl is not None and lsl>=usl: raise ValueError("LSL must be lower than USL.")
            save_spec(department,form,parameter,lsl,usl); st.success("Specification limits saved. Graphs are updated automatically."); st.rerun()
        except Exception as e: st.error(str(e))
    try: filtered=form_records(department,form)
    except Exception as e: st.error(str(e)); return
    if filtered.empty: st.info("No process data available for this selection."); return
    result,parameter,grouped=chart_result(filtered,form,selection)
    if not result: st.info("At least two readings or two complete subgroups are required."); return
    lsl,usl=get_spec(department,form,parameter); fig1,fig2=make_charts(result,selection,grouped,lsl,usl); st.plotly_chart(fig1,use_container_width=True); st.plotly_chart(fig2,use_container_width=True)
    mean,sigma=capability(result,grouped)
    if lsl is None or usl is None: st.warning("Cp and Cpk are not available. Please add both USL and LSL above.")
    elif sigma<=0: st.warning("Cp and Cpk cannot be calculated because process variation is zero.")
    else:
        cp=(usl-lsl)/(6*sigma); cpk=min((usl-mean)/(3*sigma),(mean-lsl)/(3*sigma)); c1,c2,c3,c4,c5=st.columns(5); c1.metric("Mean",f"{mean:.3f}"); c2.metric("Sigma",f"{sigma:.3f}"); c3.metric("Cp",f"{cp:.3f}"); c4.metric("Cpk",f"{cpk:.3f}"); c5.metric("Specification",f"{lsl:.3f} to {usl:.3f}")

def plant_login():
    st.markdown("""<div class='login-hero'><span class='hero-kicker'>◆ Smart Manufacturing Quality</span><h1>Quality Parameter Control</h1><p>Secure digital quality checks, disciplined traceability and real-time statistical process control.</p><div class='feature-row'><div class='feature'><b>🧪 Digital Inspections</b>Structured entry</div><div class='feature'><b>📊 Live SPC</b>Control charts</div><div class='feature'><b>🎯 Capability</b>Cp and Cpk</div></div></div><div class='login-title'><h3>Welcome back</h3><p>Select the plant and enter the authorized password.</p></div>""",unsafe_allow_html=True)
    _,center,_=st.columns([1,1.35,1])
    with center:
        with st.form("plant_login"):
            plant=st.selectbox("Plant",PLANTS); password=st.text_input("Plant Password",type="password")
            if st.form_submit_button("Continue securely →",use_container_width=True):
                if password==st.secrets.get("plant_passwords",{}).get(slug(plant)): st.session_state.update(plant=plant,plant_ok=True); st.rerun()
                else: st.error("Incorrect plant password.")

def main():
    if not st.session_state.get("plant_ok"): plant_login(); st.stop()
    with st.sidebar:
        st.success("Plant: "+st.session_state.plant)
        if st.button("Logout",use_container_width=True): st.session_state.clear(); st.rerun()
    module=st.radio("Module",["Operator Data Entry","Control Chart Analysis","Specifications & Capability"],horizontal=True)
    if module=="Control Chart Analysis": control_chart_page(); return
    if module=="Specifications & Capability": specification_page(); return
    if not st.session_state.get("department_ok"):
        st.markdown(f"<div class='page-hero'><h1>🔐 Department Access</h1><p>{st.session_state.plant} plant</p></div>",unsafe_allow_html=True); _,center,_=st.columns([1,1.35,1])
        with center:
            with st.form("department_login"):
                department=st.selectbox("Department",DEPARTMENTS); password=st.text_input("Department Password",type="password")
                if st.form_submit_button("Open department →",use_container_width=True):
                    key=f"{slug(st.session_state.plant)}_{slug(department)}"; expected=st.secrets.get("department_passwords",{}).get(key,st.secrets.get("DEFAULT_DEPARTMENT_PASSWORD","Dept@123"))
                    if password==expected: st.session_state.update(department=department,department_ok=True); st.rerun()
                    else: st.error("Incorrect department password.")
        st.stop()
    operator_entry_page()

main()
