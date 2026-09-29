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
from spc import imr

st.set_page_config(
    page_title="Quality Parameter Control",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CONFIG = json.loads(Path("config/forms.json").read_text(encoding="utf-8"))
for department_config in CONFIG.get("departments", {}).values():
    for form_config in department_config.get("forms", []):
        for parameter in form_config.get("parameters", []):
            parameter["required"] = False

PLANTS = CONFIG["plants"]
DEPARTMENTS = list(CONFIG["departments"])
SHIFTS = ["Shift A", "Shift B", "Shift C", "Shift R"]
SPEC_PATH = "data/spec_limits.csv"
SPEC_COLUMNS = [
    "Plant", "Department", "Form ID", "Parameter ID", "Parameter",
    "LSL", "USL", "Updated At",
]
SIZE_RULES = [
    ("600 X 1200", 12),
    ("1200 X 1800", 12),
    ("1200 X 2400", 8),
]
D2 = {
    2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534,
    7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078, 11: 3.173,
    12: 3.258, 13: 3.336, 14: 3.407,
}
D3 = {
    2: 0.853, 3: 0.888, 4: 0.880, 5: 0.864, 6: 0.848,
    7: 0.833, 8: 0.820, 9: 0.808, 10: 0.797, 11: 0.787,
    12: 0.778, 13: 0.770, 14: 0.763,
}

st.markdown(
    """
<style>
.stApp{background:linear-gradient(135deg,#f7fff9,#edf7f0)}
.block-container{max-width:1200px;padding-top:1.7rem;padding-bottom:3rem}
#MainMenu,footer{visibility:hidden}
.hero{padding:1.55rem 1.8rem;border-radius:22px;background:linear-gradient(125deg,#123f28,#15803d,#22a447);color:white;margin-bottom:1rem;box-shadow:0 15px 38px rgba(20,83,45,.18)}
.hero h1{margin:0}.hero p{margin:.35rem 0 0;opacity:.9}
div[data-testid="stForm"]{background:white;border:1px solid #d9e8de;border-radius:20px;padding:1.25rem;box-shadow:0 12px 30px rgba(20,83,45,.08)}
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{border-radius:11px;min-height:44px;font-weight:700}
.stFormSubmitButton>button{background:#15803d!important;color:white!important;border:0!important}
.card{padding:.9rem 1rem;background:white;border:1px solid #d9e8de;border-radius:14px;margin:.7rem 0}
[data-testid="stRadio"]>div{gap:1rem;flex-wrap:wrap}
</style>
""",
    unsafe_allow_html=True,
)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def clean(value):
    return str(value or "").strip()


def field_visible(parameter, values):
    rule = parameter.get("show_if")
    return not rule or values.get(rule["field"]) == rule["equals"]


def render_field(parameter, key):
    label = parameter["label"] + " (Optional)"
    field_type = parameter["type"]
    if field_type == "choice":
        return st.selectbox(
            label,
            [""] + parameter["options"],
            format_func=lambda value: "Select an option (optional)" if value == "" else value,
            key=key,
        )
    if field_type == "number":
        raw = st.text_input(label, placeholder="Leave blank if not measured", key=key)
        if not raw.strip():
            return ""
        try:
            return float(raw)
        except ValueError:
            return raw
    if field_type == "textarea":
        return st.text_area(label, key=key)
    return st.text_input(label, key=key)


def normalized_rows(form, inspection_date, shift, values, record_id):
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for parameter in form["parameters"]:
        if not field_visible(parameter, values):
            continue
        value = values.get(parameter["id"], "")
        if value == "":
            continue
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


def read_form_records(department, form):
    data, _ = read_data()
    return data[
        data["Plant"].astype(str).eq(st.session_state.plant)
        & data["Department"].astype(str).eq(department)
        & data["Form ID"].astype(str).eq(form["id"])
    ].copy()


def wide_export(data, form):
    if data.empty:
        return pd.DataFrame()
    base_columns = [
        "Record ID", "Plant", "Department", "Form Title",
        "Inspection Date", "Shift", "Created At",
    ]
    base = data.groupby("Record ID", as_index=False).first()[base_columns]
    data = data.copy()
    data["Export Value"] = data["Value"].where(
        data["Value"].notna() & data["Value"].astype(str).ne(""),
        data["Text Value"],
    )
    pivot = data.pivot_table(
        index="Record ID", columns="Parameter", values="Export Value", aggfunc="first"
    ).reset_index()
    output = base.merge(pivot, on="Record ID", how="left")
    ordered = base_columns + [
        p["label"] for p in form["parameters"] if p["label"] in output.columns
    ]
    return output[ordered]


def excel_bytes(dataframe, sheet_name="Data"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return output.getvalue()


def template_bytes(form):
    columns = ["Inspection Date", "Shift"] + [p["label"] for p in form["parameters"]]
    example = {column: "" for column in columns}
    example.update({"Inspection Date": date.today().isoformat(), "Shift": "Shift A"})
    return excel_bytes(pd.DataFrame([example], columns=columns), "Quality Entry")


def parse_upload(upload, form):
    if upload.name.lower().endswith(".csv"):
        data = pd.read_csv(upload)
    else:
        data = pd.read_excel(upload, sheet_name="Quality Entry", engine="openpyxl")
    data = data.dropna(how="all")
    required_columns = ["Inspection Date", "Shift"] + [p["label"] for p in form["parameters"]]
    missing = [column for column in required_columns if column not in data.columns]
    if missing:
        raise ValueError("Missing columns: " + ", ".join(missing))
    parsed = []
    errors = []
    for index, row in data.iterrows():
        excel_row = index + 2
        inspection_date = pd.to_datetime(row["Inspection Date"], errors="coerce")
        shift = "" if pd.isna(row["Shift"]) else str(row["Shift"]).strip()
        values = {
            p["id"]: "" if pd.isna(row[p["label"]]) else row[p["label"]]
            for p in form["parameters"]
        }
        if pd.isna(inspection_date):
            errors.append(f"Row {excel_row}: invalid Inspection Date")
        if shift not in SHIFTS:
            errors.append(f"Row {excel_row}: invalid Shift")
        for parameter in form["parameters"]:
            value = values[parameter["id"]]
            if parameter["type"] == "number" and value != "":
                numeric = pd.to_numeric(value, errors="coerce")
                if pd.isna(numeric):
                    errors.append(f"Row {excel_row}: {parameter['label']} must be numeric")
                else:
                    values[parameter["id"]] = float(numeric)
            if (
                parameter["type"] == "choice"
                and value != ""
                and value not in parameter["options"]
            ):
                errors.append(f"Row {excel_row}: invalid {parameter['label']}")
        parsed.append((inspection_date, shift, values))
    if errors:
        raise ValueError("\n".join(errors[:25]))
    return parsed


# GitHub-backed specification limits

def github_headers():
    return {
        "Authorization": f"Bearer {st.secrets['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def specification_url():
    return (
        f"https://api.github.com/repos/{st.secrets['GITHUB_OWNER']}/"
        f"{st.secrets['GITHUB_REPO']}/contents/{SPEC_PATH}"
    )


def read_specs():
    response = requests.get(
        specification_url(),
        headers=github_headers(),
        params={"ref": st.secrets.get("GITHUB_BRANCH", "main")},
        timeout=30,
    )
    if response.status_code == 404:
        return pd.DataFrame(columns=SPEC_COLUMNS), None
    response.raise_for_status()
    payload = response.json()
    try:
        specs = pd.read_csv(io.BytesIO(base64.b64decode(payload["content"])))
    except pd.errors.EmptyDataError:
        specs = pd.DataFrame(columns=SPEC_COLUMNS)
    for column in SPEC_COLUMNS:
        if column not in specs:
            specs[column] = ""
    return specs[SPEC_COLUMNS], payload["sha"]


def save_spec(department, form, parameter, lsl, usl):
    specs, sha = read_specs()
    mask = (
        specs["Plant"].astype(str).eq(st.session_state.plant)
        & specs["Department"].astype(str).eq(department)
        & specs["Form ID"].astype(str).eq(form["id"])
        & specs["Parameter ID"].astype(str).eq(parameter["id"])
    )
    specs = specs.loc[~mask].copy()
    specs = pd.concat([
        specs,
        pd.DataFrame([{
            "Plant": st.session_state.plant,
            "Department": department,
            "Form ID": form["id"],
            "Parameter ID": parameter["id"],
            "Parameter": parameter["label"],
            "LSL": lsl,
            "USL": usl,
            "Updated At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }]),
    ], ignore_index=True)
    body = {
        "message": f"Update limits for {parameter['label']}",
        "content": base64.b64encode(specs.to_csv(index=False).encode()).decode(),
        "branch": st.secrets.get("GITHUB_BRANCH", "main"),
    }
    if sha:
        body["sha"] = sha
    response = requests.put(
        specification_url(), headers=github_headers(), json=body, timeout=30
    )
    response.raise_for_status()


def get_spec(department, form, parameter):
    try:
        specs, _ = read_specs()
    except Exception:
        return None, None
    selected = specs[
        specs["Plant"].astype(str).eq(st.session_state.plant)
        & specs["Department"].astype(str).eq(department)
        & specs["Form ID"].astype(str).eq(form["id"])
        & specs["Parameter ID"].astype(str).eq(parameter["id"])
    ]
    if selected.empty:
        return None, None
    row = selected.iloc[-1]
    lsl = pd.to_numeric(row["LSL"], errors="coerce")
    usl = pd.to_numeric(row["USL"], errors="coerce")
    return (
        None if pd.isna(lsl) else float(lsl),
        None if pd.isna(usl) else float(usl),
    )


def chart_options(form):
    groups = {}
    for parameter in form["parameters"]:
        if parameter.get("chart_group"):
            groups.setdefault(parameter["chart_group"], []).append(parameter)
    singles = [p for p in form["parameters"] if p.get("chart_type") == "imr"]
    return groups, singles, [p["label"] for p in singles] + list(groups)


def record_text_map(data, parameter_id):
    part = data[data["Parameter ID"].astype(str).eq(parameter_id)][
        ["Record ID", "Text Value"]
    ].copy()
    return dict(zip(
        part["Record ID"].astype(str),
        part["Text Value"].fillna("").astype(str),
    ))


def fixed_size_group_result(data, parameters, size_label, required_n):
    size_map = record_text_map(data, "tile_size")
    record_ids = [
        record_id for record_id, value in size_map.items()
        if clean(value).upper() == size_label.upper()
    ]
    if not record_ids:
        return None

    selected_parameters = parameters[:required_n]
    pivot = data[
        data["Record ID"].astype(str).isin(record_ids)
        & data["Parameter ID"].isin([p["id"] for p in selected_parameters])
    ].pivot_table(
        index="Record ID", columns="Parameter ID", values="Value", aggfunc="first"
    ).reindex(columns=[p["id"] for p in selected_parameters])
    pivot = pivot.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if len(pivot) < 2:
        return None

    metadata = data[
        data["Record ID"].astype(str).isin(pivot.index.astype(str))
    ].groupby("Record ID", as_index=False).first().set_index("Record ID")
    order = sorted(
        pivot.index,
        key=lambda record_id: (
            str(metadata.loc[record_id, "Inspection Date"]),
            str(metadata.loc[record_id, "Created At"]),
            str(record_id),
        ),
    )
    pivot = pivot.loc[order]
    means = pivot.mean(axis=1)
    ranges = pivot.max(axis=1) - pivot.min(axis=1)
    grand_mean = float(means.mean())
    average_range = float(ranges.mean())
    sigma = average_range / D2[required_n]
    xbar_ucl = grand_mean + 3 * sigma / (required_n ** 0.5)
    xbar_lcl = grand_mean - 3 * sigma / (required_n ** 0.5)
    range_ucl = (D2[required_n] + 3 * D3[required_n]) * sigma
    range_lcl = max(0, (D2[required_n] - 3 * D3[required_n]) * sigma)

    press_map = record_text_map(data, "press_no")
    batch_map = record_text_map(data, "batch_number")
    labels = []
    hover = []
    for observation_no, record_id in enumerate(order, start=1):
        raw_date = str(metadata.loc[record_id, "Inspection Date"])
        parsed_date = pd.to_datetime(raw_date, errors="coerce")
        day_label = (
            parsed_date.strftime("%d-%b-%Y")
            if not pd.isna(parsed_date)
            else raw_date
        )
        labels.append(f"Observation {observation_no}<br>{day_label}")
        hover.append(
            f"Observation: {observation_no}"
            f"<br>Date: {day_label}"
            f"<br>Press: {press_map.get(str(record_id), '')}"
            f"<br>Batch: {batch_map.get(str(record_id), '')}"
            f"<br>Readings used: {required_n}"
        )

    return {
        "values": means,
        "center": grand_mean,
        "ucl": xbar_ucl,
        "lcl": xbar_lcl,
        "ranges": ranges,
        "rcenter": average_range,
        "rucl": range_ucl,
        "rlcl": range_lcl,
        "sizes": pd.Series([required_n] * len(means)),
        "sigma": sigma,
        "labels": labels,
        "hover": hover,
    }


def individual_result(data, parameter):
    result = imr(pd.to_numeric(
        data.loc[data["Parameter ID"].eq(parameter["id"]), "Value"],
        errors="coerce",
    ))
    if not result:
        return None
    values, center, ucl, lcl, ranges, rcenter, rucl, rlcl = result
    return {
        "values": values,
        "center": center,
        "ucl": ucl,
        "lcl": lcl,
        "ranges": ranges,
        "rcenter": rcenter,
        "rucl": rucl,
        "rlcl": rlcl,
        "sizes": pd.Series([1] * len(values)),
        "sigma": float(rcenter) / 1.128,
    }


def line_values(value, count):
    if isinstance(value, pd.Series):
        return list(value.astype(float))
    if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
        return list(value)
    return [float(value)] * count


def add_line(figure, value, name, color, count, dash="dot"):
    figure.add_trace(go.Scatter(
        x=list(range(1, count + 1)),
        y=line_values(value, count),
        name=name,
        mode="lines",
        line=dict(color=color, dash=dash, width=2),
    ))


def build_figures(result, selection, grouped, lsl, usl, title_suffix=""):
    values = list(result["values"])
    point_count = len(values)
    positions = list(range(1, point_count + 1))
    labels = result.get("labels", [f"Observation {n}" for n in positions])
    hover = result.get(
        "hover",
        [
            f"Observation: {n}<br>Subgroup size: {size}"
            for n, size in zip(positions, list(result["sizes"]))
        ],
    )

    xbar = go.Figure(go.Scatter(
        x=positions,
        y=values,
        mode="lines+markers",
        name=selection,
        text=hover,
        marker=dict(size=9, color="#0f6bca"),
        line=dict(color="#0f6bca", width=2.5),
        hovertemplate="%{text}<br>Subgroup average: %{y:.4f}<extra></extra>",
    ))
    for value, name, color, dash in [
        (result["center"], "Center Line", "#15803d", "dash"),
        (result["ucl"], "UCL", "#dc2626", "dot"),
        (result["lcl"], "LCL", "#dc2626", "dot"),
    ]:
        add_line(xbar, value, name, color, point_count, dash)
    if lsl is not None:
        add_line(xbar, lsl, "LSL", "#f59e0b", point_count, "dashdot")
    if usl is not None:
        add_line(xbar, usl, "USL", "#7c3aed", point_count, "dashdot")
    xbar.update_layout(
        title=("X-bar Chart: " if grouped else "Individuals Chart: ") + selection + title_suffix,
        xaxis_title="Observation / Inspection Date",
        yaxis_title="Average" if grouped else "Value",
        margin=dict(b=120),
        xaxis=dict(
            tickmode="array",
            tickvals=positions,
            ticktext=labels,
            tickangle=0,
            automargin=True,
        ),
    )

    ranges = list(result["ranges"])
    range_count = len(ranges)
    range_positions = list(range(1, range_count + 1))
    range_chart = go.Figure(go.Scatter(
        x=range_positions,
        y=ranges,
        mode="lines+markers",
        name="Range",
        text=hover[:range_count],
        marker=dict(size=9, color="#0f6bca"),
        line=dict(color="#0f6bca", width=2.5),
        hovertemplate="%{text}<br>Range: %{y:.4f}<extra></extra>",
    ))
    for value, name, color, dash in [
        (result["rcenter"], "Center Line", "#15803d", "dash"),
        (result["rucl"], "UCL", "#dc2626", "dot"),
        (result["rlcl"], "LCL", "#dc2626", "dot"),
    ]:
        add_line(range_chart, value, name, color, range_count, dash)
    range_chart.update_layout(
        title=("R Chart: " if grouped else "Moving Range Chart: ") + selection + title_suffix,
        xaxis_title="Observation / Inspection Date",
        yaxis_title="Range",
        margin=dict(b=120),
        xaxis=dict(
            tickmode="array",
            tickvals=range_positions,
            ticktext=labels[:range_count],
            tickangle=0,
            automargin=True,
        ),
    )
    return xbar, range_chart


def department_login():
    st.markdown(
        f"<div class='hero'><h1>🔐 Department Access</h1><p>{st.session_state.plant} plant</p></div>",
        unsafe_allow_html=True,
    )
    _, center, _ = st.columns([1, 1.6, 1])
    with center:
        with st.form("department_login"):
            department = st.selectbox("Department", DEPARTMENTS)
            password = st.text_input("Department Password", type="password")
            submitted = st.form_submit_button("Open Department →", use_container_width=True)
        if submitted:
            key = f"{slug(st.session_state.plant)}_{slug(department)}"
            specific = st.secrets.get("department_passwords", {}).get(key)
            fallback = st.secrets.get("DEFAULT_DEPARTMENT_PASSWORD")
            accepted = {clean(specific), clean(fallback)} - {""}
            if not accepted:
                st.error(f"Password not configured for: {key}")
            elif clean(password) in accepted:
                st.session_state.update(department=department, department_ok=True)
                st.rerun()
            else:
                st.error("Incorrect department password.")


def operator_page():
    st.markdown(
        f"<div class='hero'><h1>🧪 Operator Quality Data Entry</h1><p>{st.session_state.plant} · {st.session_state.department}</p></div>",
        unsafe_allow_html=True,
    )
    forms = CONFIG["departments"][st.session_state.department]["forms"]
    form = st.selectbox("Quality Check", forms, format_func=lambda item: item["title"])
    manual_tab, upload_tab, download_tab = st.tabs([
        "Manual Entry", "Excel Upload", "Download Data"
    ])

    with manual_tab:
        inspection_date = st.date_input("Inspection Date", date.today())
        shift = st.selectbox("Shift", SHIFTS)
        values = {}
        for parameter in form["parameters"]:
            if field_visible(parameter, values):
                values[parameter["id"]] = render_field(
                    parameter, f"manual_{form['id']}_{parameter['id']}"
                )
        if st.button("Save Entry", type="primary", use_container_width=True):
            invalid = []
            for parameter in form["parameters"]:
                value = values.get(parameter["id"], "")
                if parameter["type"] == "number" and value != "":
                    try:
                        values[parameter["id"]] = float(value)
                    except (TypeError, ValueError):
                        invalid.append(parameter["label"])
            if invalid:
                st.error("Enter numbers or leave blank: " + ", ".join(invalid))
            else:
                record_id = "QC-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
                rows = normalized_rows(form, inspection_date, shift, values, record_id)
                if not rows:
                    st.warning("Enter at least one parameter before saving.")
                else:
                    try:
                        append_rows(rows, f"Add quality check {record_id}")
                        st.success(f"Saved: {record_id}")
                    except Exception as error:
                        st.error(str(error))

    with upload_tab:
        st.download_button(
            "Download Blank Excel Template",
            template_bytes(form),
            file_name=f"{form['id']}_template.xlsx",
            use_container_width=True,
        )
        upload = st.file_uploader(
            "Upload completed Excel or CSV", type=["xlsx", "csv"]
        )
        if upload and st.button(
            "Validate and Save Uploaded Rows",
            type="primary",
            use_container_width=True,
        ):
            try:
                parsed = parse_upload(upload, form)
                all_rows = []
                for inspection_date, shift, values in parsed:
                    record_id = "QC-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
                    all_rows.extend(normalized_rows(
                        form, inspection_date.date(), shift, values, record_id
                    ))
                if not all_rows:
                    st.warning("No parameter values found.")
                else:
                    append_rows(all_rows, f"Add {len(parsed)} uploaded checks")
                    st.success(f"{len(parsed)} rows processed.")
            except Exception as error:
                st.error(str(error))

    with download_tab:
        output = wide_export(read_form_records(st.session_state.department, form), form)
        if output.empty:
            st.info("No saved records.")
        else:
            left, right = st.columns(2)
            left.download_button(
                "Download Data as Excel",
                excel_bytes(output),
                file_name=f"{form['id']}_data.xlsx",
                use_container_width=True,
            )
            right.download_button(
                "Download Data as CSV",
                output.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{form['id']}_data.csv",
                use_container_width=True,
            )


def chart_page(specification_mode=False):
    heading = "🎯 Specifications & Capability" if specification_mode else "📈 Control Chart Analysis"
    subtitle = (
        "Size-wise fixed-subgroup charts with observation number and date"
        if specification_mode
        else "Separate charts by tile size with observation number and date"
    )
    st.markdown(
        f"<div class='hero'><h1>{heading}</h1><p>{subtitle}</p></div>",
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    department = left.selectbox(
        "Department", DEPARTMENTS, key="spec_department" if specification_mode else "chart_department"
    )
    forms = CONFIG["departments"][department]["forms"]
    form = right.selectbox(
        "Quality Check",
        forms,
        format_func=lambda item: item["title"],
        key="spec_form" if specification_mode else "chart_form",
    )
    data = read_form_records(department, form)
    groups, singles, selections = chart_options(form)
    selection = st.selectbox(
        "Parameter / Group",
        selections,
        key="spec_parameter" if specification_mode else "chart_parameter",
    )
    parameter = (
        {"id": "group_" + slug(selection), "label": selection}
        if selection in groups
        else next(p for p in singles if p["label"] == selection)
    )

    if specification_mode:
        old_lsl, old_usl = get_spec(department, form, parameter)
        limit_left, limit_right = st.columns(2)
        lsl_text = limit_left.text_input(
            "LSL", value="" if old_lsl is None else str(old_lsl)
        )
        usl_text = limit_right.text_input(
            "USL", value="" if old_usl is None else str(old_usl)
        )
        if st.button("Save USL / LSL", type="primary", use_container_width=True):
            try:
                lsl = None if not lsl_text.strip() else float(lsl_text)
                usl = None if not usl_text.strip() else float(usl_text)
                if lsl is not None and usl is not None and lsl >= usl:
                    raise ValueError("LSL must be lower than USL.")
                save_spec(department, form, parameter, lsl, usl)
                st.success("Limits saved.")
                st.rerun()
            except Exception as error:
                st.error(str(error))

        specs, _ = read_specs()
        selected_specs = specs[
            specs["Plant"].astype(str).eq(st.session_state.plant)
            & specs["Department"].astype(str).eq(department)
            & specs["Form ID"].astype(str).eq(form["id"])
        ]
        if not selected_specs.empty:
            download_left, download_right = st.columns(2)
            download_left.download_button(
                "Download Limits as Excel",
                excel_bytes(selected_specs, "Specification Limits"),
                file_name=f"{form['id']}_limits.xlsx",
                use_container_width=True,
            )
            download_right.download_button(
                "Download Limits as CSV",
                selected_specs.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{form['id']}_limits.csv",
                use_container_width=True,
            )

    if data.empty:
        st.info("No data available.")
        return

    lsl, usl = get_spec(department, form, parameter)

    if selection in groups and form["id"] == "press_green_tile_thickness_bd":
        rendered = 0
        for size_label, required_n in SIZE_RULES:
            st.subheader(f"{size_label} | Readings 1-{required_n}")
            result = fixed_size_group_result(
                data, groups[selection], size_label, required_n
            )
            if not result:
                st.info(
                    f"At least two inspections of size {size_label}, each with "
                    f"readings 1-{required_n} complete, are required."
                )
                continue

            xbar, range_chart = build_figures(
                result,
                selection,
                True,
                lsl,
                usl,
                f" | Size {size_label}",
            )
            st.plotly_chart(xbar, use_container_width=True)
            st.plotly_chart(range_chart, use_container_width=True)
            rendered += 1

            mean = float(pd.Series(result["values"]).mean())
            sigma = result["sigma"]
            if lsl is not None and usl is not None and sigma > 0:
                cp = (usl - lsl) / (6 * sigma)
                cpk = min(
                    (usl - mean) / (3 * sigma),
                    (mean - lsl) / (3 * sigma),
                )
                metric1, metric2, metric3, metric4 = st.columns(4)
                metric1.metric("Mean", f"{mean:.3f}")
                metric2.metric("Sigma", f"{sigma:.3f}")
                metric3.metric("Cp", f"{cp:.3f}")
                metric4.metric("Cpk", f"{cpk:.3f}")
            else:
                st.info("Add both USL and LSL to display Cp and Cpk.")

            source = wide_export(
                data[data["Record ID"].astype(str).isin(
                    list(result["values"].index.astype(str))
                )],
                form,
            )
            download1, download2, download3, download4 = st.columns(4)
            download1.download_button(
                "Data Excel",
                excel_bytes(source),
                file_name=f"{form['id']}_{slug(size_label)}_{slug(selection)}.xlsx",
                use_container_width=True,
            )
            download2.download_button(
                "Data CSV",
                source.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{form['id']}_{slug(size_label)}_{slug(selection)}.csv",
                use_container_width=True,
            )
            download3.download_button(
                "X-bar HTML",
                pio.to_html(xbar, full_html=True, include_plotlyjs="cdn").encode(),
                file_name=f"{slug(size_label)}_{slug(selection)}_xbar.html",
                use_container_width=True,
            )
            download4.download_button(
                "R Chart HTML",
                pio.to_html(range_chart, full_html=True, include_plotlyjs="cdn").encode(),
                file_name=f"{slug(size_label)}_{slug(selection)}_r.html",
                use_container_width=True,
            )

        if rendered == 0:
            st.warning("No tile size has two valid fixed-size inspection subgroups yet.")
        return

    if selection in groups:
        st.info("Size-wise grouped charting is configured for the Press Thickness & BD form.")
        return

    result = individual_result(data, parameter)
    if not result:
        st.info("At least two readings are required.")
        return
    chart1, chart2 = build_figures(result, selection, False, lsl, usl)
    st.plotly_chart(chart1, use_container_width=True)
    st.plotly_chart(chart2, use_container_width=True)


def plant_login():
    st.markdown(
        "<div class='hero'><h1>Quality Parameter Control</h1>"
        "<p>Digital inspections, SPC and capability analysis</p></div>",
        unsafe_allow_html=True,
    )
    _, center, _ = st.columns([1, 1.5, 1])
    with center:
        with st.form("plant_login"):
            plant = st.selectbox("Plant", PLANTS)
            password = st.text_input("Plant Password", type="password")
            submitted = st.form_submit_button("Continue →", use_container_width=True)
        if submitted:
            expected = st.secrets.get("plant_passwords", {}).get(slug(plant))
            if clean(password) == clean(expected) and clean(expected):
                st.session_state.update(plant=plant, plant_ok=True)
                st.rerun()
            else:
                st.error("Incorrect plant password.")


def main():
    if not st.session_state.get("plant_ok"):
        plant_login()
        st.stop()
    if not st.session_state.get("department_ok"):
        department_login()
        st.stop()

    with st.sidebar:
        st.success(f"{st.session_state.plant} · {st.session_state.department}")
        if st.button("Change Department"):
            st.session_state.pop("department_ok", None)
            st.session_state.pop("department", None)
            st.rerun()
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

    module = st.radio(
        "Module",
        ["Operator Data Entry", "Control Chart Analysis", "Specifications & Capability"],
        horizontal=True,
        label_visibility="collapsed",
    )
    if module == "Operator Data Entry":
        operator_page()
    elif module == "Control Chart Analysis":
        chart_page(False)
    else:
        chart_page(True)


main()
