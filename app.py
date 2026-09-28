import io
import json
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from github_store import append_rows, read_data
from spc import imr, xbar_r

st.set_page_config(
    page_title="Quality Parameter Control",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CONFIG = json.loads(Path("config/forms.json").read_text(encoding="utf-8"))
PLANTS = CONFIG["plants"]
DEPARTMENTS = list(CONFIG["departments"])
SHIFTS = ["Shift A", "Shift B", "Shift C", "Shift R"]

st.markdown(
    """
<style>
:root{--green:#166534;--green2:#15803d;--ink:#10231a;--muted:#64748b;--line:#dcebe1}
.stApp{background:radial-gradient(circle at 8% 8%,#dcfce7 0,transparent 23%),linear-gradient(135deg,#f8fffa 0%,#f4f8f5 55%,#edf7f0 100%)}
.block-container{max-width:1180px;padding-top:2rem;padding-bottom:3rem}
#MainMenu,footer{visibility:hidden}.stDeployButton{display:none}
.login-hero{position:relative;overflow:hidden;padding:2.2rem 2.4rem;border-radius:26px;background:linear-gradient(125deg,#123f28 0%,#166534 48%,#16a34a 100%);color:#fff;box-shadow:0 22px 60px rgba(20,83,45,.21);margin:1rem 0 1.4rem}
.login-hero:after{content:"";position:absolute;width:310px;height:310px;border-radius:50%;right:-90px;top:-155px;background:rgba(255,255,255,.10)}
.hero-kicker{display:inline-flex;padding:.35rem .72rem;border:1px solid rgba(255,255,255,.28);border-radius:999px;background:rgba(255,255,255,.10);font-size:.78rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase}
.login-hero h1{font-size:2.35rem;line-height:1.12;margin:.85rem 0 .45rem;font-weight:800;letter-spacing:-.035em}.login-hero p{font-size:1rem;opacity:.88;margin:0;max-width:720px}
.feature-row{display:grid;grid-template-columns:repeat(3,1fr);gap:.75rem;margin-top:1.35rem}.feature{padding:.8rem 1rem;border-radius:14px;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.13);font-size:.88rem}.feature b{display:block;font-size:.96rem;margin-bottom:.12rem}
.login-title{text-align:center;margin:.25rem 0 1rem}.login-title h3{margin:0;color:var(--ink);font-size:1.32rem}.login-title p{margin:.25rem 0;color:var(--muted);font-size:.92rem}
div[data-testid="stForm"]{background:rgba(255,255,255,.94);border:1px solid var(--line);border-radius:22px;padding:1.25rem 1.35rem 1.1rem;box-shadow:0 16px 42px rgba(15,50,30,.09)}
div[data-baseweb="select"]>div,.stTextInput input{background:#f4fbf6!important;border:1px solid #d9eee0!important;border-radius:12px!important;min-height:48px}
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{min-height:46px;border-radius:12px;font-weight:700}.stFormSubmitButton>button{background:linear-gradient(90deg,#166534,#16a34a)!important;color:white!important;border:0!important}
.page-hero{padding:1.35rem 1.5rem;border-radius:19px;background:linear-gradient(125deg,#14532d,#16a34a);color:white;margin-bottom:1rem;box-shadow:0 12px 30px rgba(20,83,45,.16)}.page-hero h1{margin:0;font-size:1.8rem}.page-hero p{margin:.3rem 0 0;opacity:.88}
.download-card{padding:.85rem 1rem;border:1px solid #d9eee0;border-radius:14px;background:#f7fff9;margin:.6rem 0}
.trust{text-align:center;margin-top:1rem;color:#6b7f73;font-size:.82rem}
@media(max-width:760px){.block-container{padding:1rem}.login-hero{padding:1.5rem}.login-hero h1{font-size:1.75rem}.feature-row{display:none}}
</style>
""",
    unsafe_allow_html=True,
)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def field_visible(field, values):
    rule = field.get("show_if")
    return not rule or values.get(rule["field"]) == rule["equals"]


def render_field(field, key):
    label = field["label"] + (" *" if field.get("required") else "")
    if field["type"] == "choice":
        return st.selectbox(label, field["options"], key=key)
    if field["type"] == "number":
        return st.number_input(label, value=0.0, format=f"%.{field.get('decimals', 3)}f", key=key)
    if field["type"] == "textarea":
        return st.text_area(label, key=key)
    return st.text_input(label, key=key)


def add_limit_lines(figure, center, ucl, lcl, count):
    x_values = list(range(1, count + 1))
    for value, name, color, dash in [
        (center, "Center Line", "#15803d", "dash"),
        (ucl, "UCL", "#dc2626", "dot"),
        (lcl, "LCL", "#dc2626", "dot"),
    ]:
        figure.add_trace(go.Scatter(x=x_values, y=[value] * count, name=name, mode="lines", line=dict(color=color, dash=dash)))


def normalized_rows(form, inspection_date, shift, values, record_id, created_at):
    rows = []
    for parameter in form["parameters"]:
        if not field_visible(parameter, values):
            continue
        value = values.get(parameter["id"], "")
        rows.append({
            "Record ID": record_id,
            "Plant": st.session_state.plant,
            "Department": st.session_state.department,
            "Form ID": form["id"],
            "Form Title": form["title"],
            "Inspection Date": str(inspection_date),
            "Shift": shift,
            "Parameter ID": parameter["id"],
            "Parameter": parameter["label"],
            "Value": value if parameter["type"] == "number" else "",
            "Text Value": "" if parameter["type"] == "number" else value,
            "Unit": parameter.get("unit", ""),
            "Created At": created_at,
        })
    return rows


def template_bytes(form):
    columns = ["Inspection Date", "Shift"] + [p["label"] for p in form["parameters"]]
    example = {column: "" for column in columns}
    example.update({"Inspection Date": date.today().isoformat(), "Shift": "Shift A"})
    for parameter in form["parameters"]:
        if parameter["type"] == "choice":
            example[parameter["label"]] = parameter["options"][0]
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([example], columns=columns).to_excel(writer, sheet_name="Quality Entry", index=False)
        pd.DataFrame([
            ["Form", form["title"]],
            ["Upload Rule", "One Excel row equals one complete quality inspection."],
            ["Valid Shifts", ", ".join(SHIFTS)],
            ["Important", "Do not change column names or the Quality Entry sheet name."],
        ], columns=["Item", "Instruction"]).to_excel(writer, sheet_name="Instructions", index=False)
    return output.getvalue()


def parse_upload(upload, form):
    data = pd.read_csv(upload) if upload.name.lower().endswith(".csv") else pd.read_excel(upload, sheet_name="Quality Entry", engine="openpyxl")
    data = data.dropna(how="all")
    if data.empty:
        raise ValueError("The uploaded file contains no records.")
    required_columns = ["Inspection Date", "Shift"] + [p["label"] for p in form["parameters"]]
    missing = [column for column in required_columns if column not in data.columns]
    if missing:
        raise ValueError("Missing columns: " + ", ".join(missing))
    output, errors = [], []
    for index, row in data.iterrows():
        excel_row = index + 2
        inspection_date = pd.to_datetime(row["Inspection Date"], errors="coerce")
        shift = "" if pd.isna(row["Shift"]) else str(row["Shift"]).strip()
        values = {p["id"]: ("" if pd.isna(row[p["label"]]) else row[p["label"]]) for p in form["parameters"]}
        if pd.isna(inspection_date): errors.append(f"Row {excel_row}: invalid Inspection Date.")
        if shift not in SHIFTS: errors.append(f"Row {excel_row}: invalid Shift.")
        for parameter in form["parameters"]:
            if not field_visible(parameter, values): continue
            value = values[parameter["id"]]
            if parameter.get("required") and value == "": errors.append(f"Row {excel_row}: {parameter['label']} is required.")
            if parameter["type"] == "number" and value != "":
                numeric = pd.to_numeric(value, errors="coerce")
                if pd.isna(numeric): errors.append(f"Row {excel_row}: {parameter['label']} must be numeric.")
                else: values[parameter["id"]] = float(numeric)
            if parameter["type"] == "choice" and value not in parameter["options"]: errors.append(f"Row {excel_row}: invalid {parameter['label']}.")
        output.append((inspection_date, shift, values))
    if errors: raise ValueError("\n".join(errors[:25]))
    return output


def form_data(form, department=None):
    data, _ = read_data()
    department = department or st.session_state.department
    return data[
        data["Plant"].astype(str).eq(st.session_state.plant)
        & data["Department"].astype(str).eq(department)
        & data["Form ID"].astype(str).eq(form["id"])
    ].copy()


def wide_export(data, form):
    if data.empty:
        return pd.DataFrame()
    base_columns = ["Record ID", "Plant", "Department", "Form Title", "Inspection Date", "Shift", "Created At"]
    base = data.groupby("Record ID", as_index=False).first()[base_columns]
    data = data.copy()
    data["Export Value"] = data["Value"].where(data["Value"].notna() & data["Value"].astype(str).ne(""), data["Text Value"])
    pivot = data.pivot_table(index="Record ID", columns="Parameter", values="Export Value", aggfunc="first").reset_index()
    result = base.merge(pivot, on="Record ID", how="left")
    ordered = base_columns + [p["label"] for p in form["parameters"] if p["label"] in result.columns]
    return result[ordered]


def excel_bytes(dataframe, sheet_name="Quality Data"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return output.getvalue()


def data_entry_downloads(form):
    st.markdown("<div class='download-card'><b>⬇ Download entered data</b><br><small>Download all saved records for the selected plant, department and quality check.</small></div>", unsafe_allow_html=True)
    try:
        current = form_data(form)
        export = wide_export(current, form)
    except Exception as error:
        st.warning(f"Download unavailable: {error}")
        return
    if export.empty:
        st.caption("No saved records are available for download yet.")
        return
    col1, col2 = st.columns(2)
    col1.download_button(
        "Download Entered Data as Excel",
        excel_bytes(export),
        file_name=f"{slug(st.session_state.plant)}_{form['id']}_data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    col2.download_button(
        "Download Entered Data as CSV",
        export.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{slug(st.session_state.plant)}_{form['id']}_data.csv",
        mime="text/csv",
        use_container_width=True,
    )


def operator_entry_page():
    st.markdown(f"<div class='page-hero'><h1>🧪 Operator Quality Data Entry</h1><p>{st.session_state.plant} · {st.session_state.department}</p></div>", unsafe_allow_html=True)
    forms = CONFIG["departments"][st.session_state.department]["forms"]
    form = st.selectbox("Quality Check", forms, format_func=lambda item: item["title"])
    st.caption(form.get("description", ""))
    manual_tab, excel_tab, download_tab = st.tabs(["✍️ Manual Entry", "📥 Excel Upload", "⬇ Download Data"])

    with manual_tab:
        inspection_date = st.date_input("Inspection Date *", date.today(), key=f"manual_date_{form['id']}")
        shift = st.selectbox("Shift *", SHIFTS, key=f"manual_shift_{form['id']}")
        values = {}
        for parameter in form["parameters"]:
            if field_visible(parameter, values):
                values[parameter["id"]] = render_field(parameter, f"manual_{form['id']}_{parameter['id']}")
        if st.button("Save Manual Entry", type="primary", use_container_width=True):
            missing = [p["label"] for p in form["parameters"] if field_visible(p, values) and p.get("required") and (values.get(p["id"]) is None or isinstance(values.get(p["id"]), str) and not values.get(p["id"]).strip())]
            if missing:
                st.error("Required fields missing: " + ", ".join(missing))
            else:
                record_id = "QC-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
                try:
                    append_rows(normalized_rows(form, inspection_date, shift, values, record_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")), f"Add manual quality check {record_id}")
                    st.success(f"Saved successfully. Record ID: {record_id}")
                except Exception as error:
                    st.error(f"Save failed: {error}")

    with excel_tab:
        st.info("Download the template, enter one complete inspection per row, and upload the completed file.")
        st.download_button("Download Blank Excel Template", template_bytes(form), file_name=f"{form['id']}_template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        upload = st.file_uploader("Upload completed Excel or CSV", type=["xlsx", "csv"], key=f"upload_{form['id']}")
        if upload and st.button("Validate and Save Uploaded Rows", type="primary", use_container_width=True, key=f"save_upload_{form['id']}"):
            try:
                parsed = parse_upload(upload, form)
                all_rows = []
                for inspection_date, shift, values in parsed:
                    record_id = "QC-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
                    all_rows.extend(normalized_rows(form, inspection_date.date(), shift, values, record_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                append_rows(all_rows, f"Add {len(parsed)} uploaded quality checks")
                st.success(f"{len(parsed)} quality checks uploaded successfully.")
            except Exception as error:
                st.error(f"Upload failed: {error}")

    with download_tab:
        data_entry_downloads(form)


def control_chart_page():
    st.markdown(f"<div class='page-hero'><h1>📈 Parameter Control Charts</h1><p>{st.session_state.plant} plant</p></div>", unsafe_allow_html=True)
    try:
        data, _ = read_data()
    except Exception as error:
        st.error(f"Unable to read data: {error}")
        return
    data = data[data["Plant"].astype(str).eq(st.session_state.plant)]
    col1, col2 = st.columns(2)
    department = col1.selectbox("Department", DEPARTMENTS)
    forms = CONFIG["departments"][department]["forms"]
    form = col2.selectbox("Quality Check", forms, format_func=lambda item: item["title"])
    filtered = data[data["Department"].eq(department) & data["Form ID"].eq(form["id"])].copy()
    if filtered.empty:
        st.info("No data available for the selected quality check.")
        return

    groups = {}
    for parameter in form["parameters"]:
        if parameter.get("chart_group"):
            groups.setdefault(parameter["chart_group"], []).append(parameter)
    singles = [p for p in form["parameters"] if p.get("chart_type") == "imr"]
    selection = st.selectbox("Parameter / Group", [p["label"] for p in singles] + list(groups))

    if selection in groups:
        params = groups[selection]
        pivot = filtered[filtered["Parameter ID"].isin([p["id"] for p in params])].pivot_table(index="Record ID", columns="Parameter ID", values="Value", aggfunc="first").reindex(columns=[p["id"] for p in params])
        result = xbar_r(pivot)
        if not result:
            st.info("At least two complete 14-reading subgroups are required.")
            return
        first_title, second_title = f"X-bar Chart: {selection}", f"R Chart: {selection}"
    else:
        parameter = next(p for p in singles if p["label"] == selection)
        series = pd.to_numeric(filtered.loc[filtered["Parameter ID"].eq(parameter["id"]), "Value"], errors="coerce")
        result = imr(series)
        if not result:
            st.info("At least two readings are required.")
            return
        first_title, second_title = f"Individuals Chart: {selection}", f"Moving Range Chart: {selection}"

    values, center, ucl, lcl, ranges, range_center, range_ucl, range_lcl = result
    first = go.Figure(go.Scatter(x=list(range(1, len(values) + 1)), y=values, mode="lines+markers", name=selection))
    add_limit_lines(first, center, ucl, lcl, len(values))
    first.update_layout(title=first_title, xaxis_title="Observation", yaxis_title="Value")
    st.plotly_chart(first, use_container_width=True)

    second = go.Figure(go.Scatter(x=list(range(1, len(ranges) + 1)), y=ranges, mode="lines+markers", name="Range"))
    add_limit_lines(second, range_center, range_ucl, range_lcl, len(ranges))
    second.update_layout(title=second_title, xaxis_title="Observation", yaxis_title="Range")
    st.plotly_chart(second, use_container_width=True)

    st.markdown("<div class='download-card'><b>⬇ Download SPC results</b><br><small>Download filtered source data and interactive chart files.</small></div>", unsafe_allow_html=True)
    wide = wide_export(filtered, form)
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button("SPC Data Excel", excel_bytes(wide), file_name=f"{form['id']}_{slug(selection)}_spc_data.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    d2.download_button("SPC Data CSV", wide.to_csv(index=False).encode("utf-8-sig"), file_name=f"{form['id']}_{slug(selection)}_spc_data.csv", mime="text/csv", use_container_width=True)
    d3.download_button("Main Chart HTML", pio.to_html(first, full_html=True, include_plotlyjs="cdn").encode("utf-8"), file_name=f"{form['id']}_{slug(selection)}_main_chart.html", mime="text/html", use_container_width=True)
    d4.download_button("Range Chart HTML", pio.to_html(second, full_html=True, include_plotlyjs="cdn").encode("utf-8"), file_name=f"{form['id']}_{slug(selection)}_range_chart.html", mime="text/html", use_container_width=True)


def plant_login():
    st.markdown("""
<div class='login-hero'><span class='hero-kicker'>◆ Smart Manufacturing Quality</span><h1>Quality Parameter Control</h1><p>Secure digital quality checks, disciplined traceability and real-time statistical process control for plant operations.</p><div class='feature-row'><div class='feature'><b>🧪 Digital Inspections</b>Structured operator entry</div><div class='feature'><b>📊 Live SPC</b>I-MR and X-bar/R charts</div><div class='feature'><b>🔐 Controlled Access</b>Plant and department login</div></div></div><div class='login-title'><h3>Welcome back</h3><p>Select the plant and enter the authorized password to continue.</p></div>
""", unsafe_allow_html=True)
    _, center, _ = st.columns([1, 1.35, 1])
    with center:
        with st.form("plant_login"):
            plant = st.selectbox("Plant", PLANTS)
            password = st.text_input("Plant Password", type="password", placeholder="Enter plant password")
            if st.form_submit_button("Continue securely  →", use_container_width=True):
                if password == st.secrets.get("plant_passwords", {}).get(slug(plant)):
                    st.session_state.update(plant=plant, plant_ok=True)
                    st.rerun()
                else:
                    st.error("Incorrect plant password.")
        st.markdown("<div class='trust'>🔒 Authorized plant users only</div>", unsafe_allow_html=True)


def main():
    if not st.session_state.get("plant_ok"):
        plant_login()
        st.stop()
    with st.sidebar:
        st.success(f"Plant: {st.session_state.plant}")
        if st.button("Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    module = st.radio("Module", ["Operator Data Entry", "Control Chart Analysis"], horizontal=True)
    if module == "Control Chart Analysis":
        control_chart_page()
        return
    if not st.session_state.get("department_ok"):
        st.markdown(f"<div class='page-hero'><h1>🔐 Department Access</h1><p>{st.session_state.plant} plant</p></div>", unsafe_allow_html=True)
        _, center, _ = st.columns([1, 1.35, 1])
        with center:
            with st.form("department_login"):
                department = st.selectbox("Department", DEPARTMENTS)
                password = st.text_input("Department Password", type="password", placeholder="Enter department password")
                if st.form_submit_button("Open department  →", use_container_width=True):
                    key = f"{slug(st.session_state.plant)}_{slug(department)}"
                    expected = st.secrets.get("department_passwords", {}).get(key, st.secrets.get("DEFAULT_DEPARTMENT_PASSWORD", "Dept@123"))
                    if password == expected:
                        st.session_state.update(department=department, department_ok=True)
                        st.rerun()
                    else:
                        st.error("Incorrect department password.")
        st.stop()
    operator_entry_page()


main()
