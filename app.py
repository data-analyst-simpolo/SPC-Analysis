import hashlib
import io
import json
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import github_store

st.set_page_config(page_title="Manufacturing SPC Portal", page_icon="📈", layout="wide")
ROOT = Path(__file__).parent
CONFIG = json.loads((ROOT / "config/forms.json").read_text(encoding="utf-8"))
USERS = json.loads((ROOT / "config/users.json").read_text(encoding="utf-8"))["users"]
DATA_PATH = ROOT / "data/quality_readings.csv"
LIMITS_PATH = ROOT / "data/spec_limits.csv"
PLANTS = ["Maliya", "Tirupati Unit 1", "Tirupati Unit 2", "Tirupati Unit 3"]
SHIFTS = ["A", "B", "C", "General", "Not provided"]
DATA_COLUMNS = [
    "Record ID", "Plant", "Department", "Form ID", "Form Title",
    "Inspection Date", "Shift", "Parameter ID", "Parameter", "Sample No",
    "Value", "Text Value", "Unit", "Created At"
]
LIMIT_COLUMNS = [
    "Plant", "Department", "Form ID", "Parameter ID", "Parameter",
    "LSL", "USL", "Target"
]

st.markdown(
    """
    <style>
    .stApp {background:#f5faf6}
    .block-container {max-width:1450px; padding-top:1rem}
    .hero {background:linear-gradient(120deg,#102d20,#16803d); color:white;
           border-radius:20px; padding:1.25rem 1.5rem; margin-bottom:1rem}
    .note {background:#eef8f0; border:1px solid #cce4d1; border-radius:12px;
           padding:.8rem 1rem; color:#18432c}
    .stButton>button,.stDownloadButton>button {border-radius:10px}
    </style>
    """,
    unsafe_allow_html=True,
)

for secret_name in ("GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO", "GITHUB_BRANCH"):
    if secret_name in st.secrets:
        os.environ[secret_name] = str(st.secrets[secret_name])


def allowed_departments():
    permitted = st.session_state.get("user", {}).get("departments", [])
    return list(CONFIG["departments"]) if "*" in permitted else permitted


def login_page():
    st.markdown(
        "<div class='hero'><b>MANUFACTURING EXCELLENCE</b>"
        "<h2 style='margin:.4rem 0'>SPC & Daily Analysis Portal</h2>"
        "<div>Secure plant and department access</div></div>",
        unsafe_allow_html=True,
    )
    _, center, _ = st.columns([1.2, 1, 1.2])
    with center:
        with st.form("login_form"):
            plant = st.selectbox("Plant", PLANTS)
            department = st.selectbox(
                "Department", ["Plant Administration"] + list(CONFIG["departments"])
            )
            user_id = st.text_input("User ID")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button(
                "Secure Login", type="primary", use_container_width=True
            )
        if submitted:
            user = USERS.get(user_id.strip())
            valid = bool(user)
            valid = valid and hashlib.sha256(password.encode()).hexdigest() == user.get("password_sha256")
            valid = valid and plant in user.get("plants", [user.get("plant")])
            valid = valid and (
                (department == "Plant Administration" and user.get("role") == "admin")
                or "*" in user.get("departments", [])
                or department in user.get("departments", [])
            )
            if valid:
                st.session_state.logged = True
                st.session_state.user = user
                st.session_state.plant = plant
                st.rerun()
            else:
                st.error("Invalid plant, department, user ID or password.")


def read_shared_csv(path, columns):
    relative_path = str(path.relative_to(ROOT)).replace("\\", "/")
    remote_text = github_store.read_text(relative_path)
    if remote_text is not None:
        frame = pd.read_csv(io.StringIO(remote_text))
    elif path.exists() and path.stat().st_size:
        frame = pd.read_csv(path)
    else:
        frame = pd.DataFrame(columns=columns)
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame[columns]


def save_shared_csv(path, frame, message):
    text = frame.to_csv(index=False)
    path.write_text(text, encoding="utf-8")
    github_store.write_text(str(path.relative_to(ROOT)).replace("\\", "/"), text, message)


def readings():
    return read_shared_csv(DATA_PATH, DATA_COLUMNS)


def specification_limits():
    return read_shared_csv(LIMITS_PATH, LIMIT_COLUMNS)


def all_forms():
    return [
        (department, form)
        for department, department_config in CONFIG["departments"].items()
        for form in department_config["forms"]
    ]


def selected_form(department, title):
    return next(form for dep, form in all_forms() if dep == department and form["title"] == title)


def choose_form(key_prefix):
    department = st.selectbox("Department", allowed_departments(), key=f"{key_prefix}_department")
    titles = [form["title"] for dep, form in all_forms() if dep == department]
    form = selected_form(
        department,
        st.selectbox("Form", titles, key=f"{key_prefix}_form"),
    )
    return department, form


def normalize(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def scalar(value):
    if isinstance(value, pd.Series):
        valid = value.dropna()
        return "" if valid.empty else valid.iloc[0]
    return value


def normalize_time(value):
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")
    raw = re.sub(r"\s+", "", str(value).strip()).upper().rstrip(".")
    raw = re.sub(r"(?<=\d)\.(?=\d)", ":", raw)
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?(AM|PM)?", raw)
    if not match:
        return str(value).strip()
    hour, minute, second, suffix = match.groups()
    hour, minute, second = int(hour), int(minute), int(second or 0)
    if suffix == "PM" and hour < 12:
        hour += 12
    if suffix == "AM" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def parse_press_excel(upload):
    source = pd.read_excel(upload, sheet_name="Quality Entry", engine="openpyxl").dropna(how="all")
    source = source.loc[:, ~source.columns.astype(str).str.startswith("Unnamed:")]
    aliases = {
        "date": "inspection_date",
        "time": "inspection_time",
        "supopename": "supervisor_operator_name",
        "pcrno": "press_number",
        "finalsize": "tile_size",
        "batchnumber": "batch_number",
        "bodycode": "body_code",
        "silonumber": "silo_number",
        "grlengthmm": "green_length_mm",
        "grweidthmm": "green_width_mm",
        "greenwidthmm": "green_width_mm",
        "greendiagonal1mm": "green_diagonal_1_mm",
        "greendiagonal2mm": "green_diagonal_2_mm",
        "bulkdensity13": "bulk_density_13",
        "bulkdensity14": "bulk_density_14",
        "remarkscommentsifany": "remarks",
    }
    # Existing operational workbook TH.2-TH.13 represents positions 1-12.
    # B.D 2-B.D 13 represents positions 1-12. Trailing named fields are 13 and 14.
    for excel_number in range(2, 14):
        aliases[normalize(f"TH. {excel_number}")] = f"thickness_{excel_number - 1}"
        aliases[normalize(f"B.D {excel_number}")] = f"bulk_density_{excel_number - 1}"

    mapped = {}
    for source_column in source.columns:
        target = aliases.get(normalize(source_column))
        if not target:
            continue
        series = source[source_column]
        if isinstance(series, pd.DataFrame):
            series = series.bfill(axis=1).iloc[:, 0]
        mapped[target] = mapped[target].combine_first(series) if target in mapped else series
    frame = pd.DataFrame(mapped, index=source.index)
    if "inspection_date" not in frame.columns:
        raise ValueError("Date column was not found in the Press workbook.")

    records = []
    numeric_ids = (
        ["green_length_mm", "green_width_mm", "green_diagonal_1_mm", "green_diagonal_2_mm"]
        + [f"thickness_{i}" for i in range(1, 15)]
        + [f"bulk_density_{i}" for i in range(1, 15)]
    )
    metadata_ids = [
        "inspection_time", "supervisor_operator_name", "press_number", "tile_size",
        "batch_number", "body_code", "silo_number", "remarks"
    ]
    for _, row in frame.iterrows():
        inspection_date = pd.to_datetime(scalar(row.get("inspection_date", "")), errors="coerce")
        if pd.isna(inspection_date):
            continue
        values = {}
        for field_id in metadata_ids:
            value = scalar(row.get(field_id, ""))
            if value is None or pd.isna(value) or value == "":
                continue
            values[field_id] = normalize_time(value) if field_id == "inspection_time" else str(value).strip()
        for parameter_id in numeric_ids:
            value = pd.to_numeric(scalar(row.get(parameter_id, "")), errors="coerce")
            if not pd.isna(value):
                values[parameter_id] = float(value)
        records.append((inspection_date.date(), "Not provided", values))
    if not records:
        raise ValueError("No valid inspection rows were found in the Press workbook.")
    return records


def parse_generic_excel(upload, form):
    source = pd.read_excel(upload, sheet_name="Quality Entry", engine="openpyxl").dropna(how="all")
    aliases = {normalize("Inspection Date"): "inspection_date", normalize("Shift"): "shift"}
    for field in form.get("metadata", []) + form["parameters"]:
        aliases[normalize(field["label"])] = field["id"]
    source = source.rename(columns={column: aliases.get(normalize(column), column) for column in source.columns})
    records = []
    for _, row in source.iterrows():
        inspection_date = pd.to_datetime(scalar(row.get("inspection_date", "")), errors="coerce")
        if pd.isna(inspection_date):
            continue
        shift = str(scalar(row.get("shift", "Not provided")))
        shift = shift if shift in SHIFTS else "Not provided"
        values = {}
        for field in form.get("metadata", []) + form["parameters"]:
            value = scalar(row.get(field["id"], ""))
            if value is None or pd.isna(value) or value == "":
                continue
            if field["type"] == "number":
                value = pd.to_numeric(value, errors="coerce")
                if pd.isna(value):
                    continue
                value = float(value)
            elif field["type"] == "time":
                value = normalize_time(value)
            values[field["id"]] = value
        records.append((inspection_date.date(), shift, values))
    return records


def append_record(department, form, inspection_date, shift, values):
    record_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for field in form.get("metadata", []) + form["parameters"]:
        value = values.get(field["id"], "")
        if value is None or value == "":
            continue
        is_number = field["type"] == "number"
        rows.append({
            "Record ID": record_id,
            "Plant": st.session_state.plant,
            "Department": department,
            "Form ID": form["id"],
            "Form Title": form["title"],
            "Inspection Date": str(inspection_date),
            "Shift": shift,
            "Parameter ID": field["id"],
            "Parameter": field["label"],
            "Sample No": "",
            "Value": float(value) if is_number else "",
            "Text Value": "" if is_number else str(value),
            "Unit": field.get("unit", ""),
            "Created At": created_at,
        })
    updated = pd.concat([readings(), pd.DataFrame(rows)], ignore_index=True)
    save_shared_csv(DATA_PATH, updated, "Append SPC inspection")


def manual_entry_page():
    st.subheader("Manual Inspection Entry")
    department, form = choose_form("manual")
    with st.form("manual_entry_form"):
        date_col, shift_col = st.columns(2)
        inspection_date = date_col.date_input("Inspection Date")
        shift = shift_col.selectbox("Shift", SHIFTS)
        values = {}
        fields = form.get("metadata", []) + form["parameters"]
        columns = st.columns(3)
        for index, field in enumerate(fields):
            with columns[index % 3]:
                key = f"manual_{form['id']}_{field['id']}"
                if field["type"] == "number":
                    values[field["id"]] = st.number_input(field["label"], value=None, key=key)
                elif field["type"] == "time":
                    values[field["id"]] = st.time_input(field["label"], value=None, key=key)
                else:
                    values[field["id"]] = st.text_input(field["label"], key=key)
        submitted = st.form_submit_button("Save Inspection", type="primary", use_container_width=True)
    if submitted:
        append_record(department, form, inspection_date, shift, values)
        st.success("Inspection saved successfully.")


def excel_upload_page():
    st.subheader("Excel Upload")
    department, form = choose_form("upload")
    template_path = ROOT / "excel_templates" / f"{form['id']}.xlsx"
    if template_path.exists():
        st.download_button(
            "Download Excel Template", template_path.read_bytes(),
            file_name=template_path.name, use_container_width=True
        )
    upload = st.file_uploader("Upload completed Excel", type=["xlsx"], key="excel_upload_file")
    if upload and st.button("Import Excel", type="primary", key="import_excel_button"):
        try:
            records = parse_press_excel(upload) if form["id"] == "press_green_tile_thickness_bd" else parse_generic_excel(upload, form)
            for inspection_date, shift, values in records:
                append_record(department, form, inspection_date, shift, values)
            st.success(f"{len(records)} inspections imported successfully from {upload.name}.")
        except Exception as error:
            st.error(f"Import failed: {error}")


def parameter_data(form, parameter):
    frame = readings()
    common = (
        frame["Plant"].astype(str).eq(st.session_state.plant)
        & frame["Form ID"].astype(str).eq(form["id"])
    )
    direct = frame[common & frame["Parameter ID"].astype(str).eq(parameter["id"])].copy()

    # Backward compatibility for the previous subgroup-storage version.
    position_match = re.fullmatch(r"(thickness|bulk_density)_(\d+)", parameter["id"])
    if position_match:
        legacy_id, sample_number = position_match.group(1), int(position_match.group(2))
        sample_values = pd.to_numeric(frame["Sample No"], errors="coerce")
        legacy = frame[
            common
            & frame["Parameter ID"].astype(str).eq(legacy_id)
            & sample_values.eq(sample_number)
        ].copy()
        direct = pd.concat([direct, legacy], ignore_index=True)

    direct["Numeric Value"] = pd.to_numeric(direct["Value"], errors="coerce")
    direct["Date"] = pd.to_datetime(direct["Inspection Date"], errors="coerce").dt.date
    direct["Created"] = pd.to_datetime(direct["Created At"], errors="coerce")
    return direct.dropna(subset=["Numeric Value", "Date"]).sort_values(
        ["Date", "Created", "Record ID"], kind="stable"
    )


def imr(values):
    x = pd.Series(values, dtype=float).dropna().reset_index(drop=True)
    if len(x) < 2:
        return None
    moving_ranges = x.diff().abs().dropna()
    mr_bar = moving_ranges.mean()
    center = x.mean()
    sigma_within = mr_bar / 1.128 if mr_bar > 0 else 0.0
    return (
        x, center, center + 2.66 * mr_bar, center - 2.66 * mr_bar,
        moving_ranges, mr_bar, 3.267 * mr_bar, 0.0, sigma_within
    )


def control_chart(title, labels, values, center, ucl, lcl, unit):
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=labels, y=values, mode="lines+markers", name="Value",
        line=dict(color="#16803d", width=2.5), marker=dict(size=7)
    ))
    for value, name, color, dash in [
        (ucl, "UCL", "#c43d32", "dash"),
        (center, "CL", "#2563eb", "dot"),
        (lcl, "LCL", "#c43d32", "dash"),
    ]:
        figure.add_hline(
            y=value, line_color=color, line_dash=dash,
            annotation_text=f"{name}: {value:.3f}"
        )
    figure.update_layout(
        title=title, xaxis_title="Observation / Inspection Date",
        yaxis_title=unit, height=430, margin=dict(bottom=105)
    )
    figure.update_xaxes(tickangle=-45, automargin=True)
    return figure


def spec_group_label(parameter):
    group = parameter.get("spec_group", parameter["id"])
    if group == "thickness_all":
        return "Common specification for Thickness 1-14"
    if group == "bulk_density_all":
        return "Common specification for Bulk Density 1-14"
    if group == "green_diagonal":
        return "Common specification for Green Diagonal 1-2"
    return f"Specification for {parameter['label']}"


def load_saved_limits(department, form, parameter):
    group_id = parameter.get("spec_group", parameter["id"])
    limits = specification_limits()
    selected = limits[
        limits["Plant"].astype(str).eq(st.session_state.plant)
        & limits["Department"].astype(str).eq(department)
        & limits["Form ID"].astype(str).eq(form["id"])
        & limits["Parameter ID"].astype(str).eq(group_id)
    ]
    if selected.empty:
        return None, None
    lsl = pd.to_numeric(selected.iloc[-1]["LSL"], errors="coerce")
    usl = pd.to_numeric(selected.iloc[-1]["USL"], errors="coerce")
    return (None if pd.isna(lsl) else float(lsl), None if pd.isna(usl) else float(usl))


def save_limits(department, form, parameter, lsl, usl):
    group_id = parameter.get("spec_group", parameter["id"])
    limits = specification_limits()
    same = (
        limits["Plant"].astype(str).eq(st.session_state.plant)
        & limits["Department"].astype(str).eq(department)
        & limits["Form ID"].astype(str).eq(form["id"])
        & limits["Parameter ID"].astype(str).eq(group_id)
    )
    limits = limits[~same]
    row = {
        "Plant": st.session_state.plant,
        "Department": department,
        "Form ID": form["id"],
        "Parameter ID": group_id,
        "Parameter": spec_group_label(parameter),
        "LSL": lsl,
        "USL": usl,
        "Target": (lsl + usl) / 2,
    }
    save_shared_csv(
        LIMITS_PATH,
        pd.concat([limits, pd.DataFrame([row])], ignore_index=True),
        "Update SPC specification limits",
    )


def analysis_page(day_wise=False):
    st.subheader("Day-wise Analysis" if day_wise else "Observation-wise SPC & Capability")
    department, form = choose_form("day" if day_wise else "observation")

    parameter_labels = [parameter["label"] for parameter in form["parameters"]]
    selected_label = st.selectbox(
        "Parameter",
        parameter_labels,
        key=f"{'day' if day_wise else 'observation'}_parameter",
    )
    # This separate statement fixes StreamlitDuplicateElementId. The selectbox is
    # created exactly once, instead of being created repeatedly inside next().
    parameter = next(p for p in form["parameters"] if p["label"] == selected_label)

    frame = parameter_data(form, parameter)
    if day_wise:
        from_col, to_col = st.columns(2)
        from_date = from_col.date_input("From Date", date.today().replace(day=1), key="day_from")
        to_date = to_col.date_input("To Date", date.today(), key="day_to")
        frame = frame[(frame["Date"] >= from_date) & (frame["Date"] <= to_date)]
        frame = frame.groupby("Date", as_index=False)["Numeric Value"].mean()
        labels = frame["Date"].astype(str).tolist()
        values = frame["Numeric Value"].tolist()
    else:
        labels = [
            f"Observation {number}<br>{inspection_date.strftime('%d-%b-%Y')}"
            for number, inspection_date in enumerate(frame["Date"], start=1)
        ]
        values = frame["Numeric Value"].tolist()

    result = imr(values)
    if not result:
        st.warning("At least two observations or selected dates are required.")
        return
    values, center, ucl, lcl, ranges, r_center, r_ucl, r_lcl, sigma = result

    saved_lsl, saved_usl = load_saved_limits(department, form, parameter)
    st.markdown(f"<div class='note'>{spec_group_label(parameter)}</div>", unsafe_allow_html=True)
    lsl_col, usl_col = st.columns(2)
    lsl = lsl_col.number_input(
        "LSL", value=saved_lsl,
        key=f"lsl_{st.session_state.plant}_{form['id']}_{parameter.get('spec_group', parameter['id'])}_{day_wise}",
    )
    usl = usl_col.number_input(
        "USL", value=saved_usl,
        key=f"usl_{st.session_state.plant}_{form['id']}_{parameter.get('spec_group', parameter['id'])}_{day_wise}",
    )

    if lsl is not None and usl is not None:
        if usl <= lsl:
            st.error("USL must be greater than LSL.")
        elif sigma <= 0:
            st.warning("Cp and Cpk require measurable process variation.")
        else:
            cp = (usl - lsl) / (6 * sigma)
            cpk = min((usl - center) / (3 * sigma), (center - lsl) / (3 * sigma))
            metric_a, metric_b, metric_c = st.columns(3)
            metric_a.metric("Cp", f"{cp:.3f}")
            metric_b.metric("Cpk", f"{cpk:.3f}")
            metric_c.metric("Process Mean", f"{center:.3f}")
            if st.button(
                "Save Common Specification Limits",
                key=f"save_specs_{parameter.get('spec_group', parameter['id'])}_{day_wise}",
            ):
                save_limits(department, form, parameter, lsl, usl)
                st.success("Specification limits saved and will apply to all parameters in this group.")

    st.plotly_chart(
        control_chart(parameter["label"], labels, values, center, ucl, lcl, parameter.get("unit", "")),
        use_container_width=True,
    )
    if not day_wise:
        range_labels = labels[1:] if len(labels) == len(ranges) + 1 else labels[:len(ranges)]
        st.plotly_chart(
            control_chart(
                f"{parameter['label']} - Moving Range",
                range_labels, ranges, r_center, r_ucl, r_lcl, parameter.get("unit", ""),
            ),
            use_container_width=True,
        )


def data_page():
    frame = readings()
    frame = frame[
        frame["Plant"].astype(str).eq(st.session_state.plant)
        & frame["Department"].astype(str).isin(allowed_departments())
    ]
    st.subheader("Data")
    st.dataframe(frame.tail(500), use_container_width=True, hide_index=True)
    st.download_button(
        "Download Data CSV", frame.to_csv(index=False).encode(),
        file_name="quality_readings.csv"
    )


if not st.session_state.get("logged"):
    login_page()
    st.stop()

with st.sidebar:
    st.success(st.session_state.user["display_name"])
    st.caption(f"Plant: {st.session_state.plant}")
    if st.button("Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.markdown(
    "<div class='hero'><h2>Manufacturing SPC & Daily Analysis</h2>"
    "<div>Individual position SPC, common specification groups, Cp/Cpk, daily averages and Excel upload</div></div>",
    unsafe_allow_html=True,
)
page = st.sidebar.radio(
    "Page",
    ["Manual Entry", "Excel Upload", "Observation-wise Analysis", "Day-wise Analysis", "Data"],
)
{
    "Manual Entry": manual_entry_page,
    "Excel Upload": excel_upload_page,
    "Observation-wise Analysis": lambda: analysis_page(False),
    "Day-wise Analysis": lambda: analysis_page(True),
    "Data": data_page,
}[page]()
