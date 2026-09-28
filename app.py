import io
import json
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from github_store import append_rows, read_data
from spc import imr, xbar_r

st.set_page_config(page_title="Quality Parameter Control", page_icon="📈", layout="wide")
CONFIG = json.loads(Path("config/forms.json").read_text(encoding="utf-8"))
PLANTS = CONFIG["plants"]
DEPARTMENTS = list(CONFIG["departments"])
SHIFTS = ["Shift A", "Shift B", "Shift C", "Shift R"]

st.markdown(
    """
    <style>
    .block-container{padding-top:1.1rem}
    .hero{padding:1.2rem 1.5rem;border-radius:18px;
    background:linear-gradient(135deg,#14532d,#15803d);color:white;margin-bottom:1rem}
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
    field_type = field["type"]
    if field_type == "choice":
        return st.selectbox(label, field["options"], key=key)
    if field_type == "number":
        return st.number_input(
            label,
            value=0.0,
            format=f"%.{field.get('decimals', 3)}f",
            key=key,
        )
    if field_type == "textarea":
        return st.text_area(label, key=key)
    return st.text_input(label, key=key)


def add_limit_lines(figure, center, ucl, lcl, count):
    x_values = list(range(1, count + 1))
    for values, name, color, dash in [
        ([center] * count, "Center", "#15803d", "dash"),
        ([ucl] * count, "UCL", "#dc2626", "dot"),
        ([lcl] * count, "LCL", "#dc2626", "dot"),
    ]:
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=values,
                name=name,
                mode="lines",
                line=dict(color=color, dash=dash),
            )
        )


def template_bytes(form):
    columns = ["Inspection Date", "Shift"] + [p["label"] for p in form["parameters"]]
    example = {column: "" for column in columns}
    example["Inspection Date"] = date.today().isoformat()
    example["Shift"] = "Shift A"
    for parameter in form["parameters"]:
        if parameter["type"] == "number":
            example[parameter["label"]] = 0
        elif parameter["type"] == "choice":
            example[parameter["label"]] = parameter["options"][0]
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([example], columns=columns).to_excel(
            writer, sheet_name="Quality Entry", index=False
        )
        instructions = [
            ["Form", form["title"]],
            ["Required", "Do not leave mandatory fields blank."],
            ["Shift Values", ", ".join(SHIFTS)],
            ["Conditional Fields", "Ball Mill Number is required for Batch Ball Mill; Other Tile Size is required when Tile Size is Other."],
            ["Upload Rule", "One Excel row equals one complete quality-check submission."],
        ]
        pd.DataFrame(instructions, columns=["Item", "Instruction"]).to_excel(
            writer, sheet_name="Instructions", index=False
        )
    return output.getvalue()


def clean_cell(value):
    if pd.isna(value):
        return ""
    return value.strip() if isinstance(value, str) else value


def parse_upload(upload, form):
    if upload.name.lower().endswith(".csv"):
        data = pd.read_csv(upload)
    else:
        data = pd.read_excel(upload, sheet_name="Quality Entry", engine="openpyxl")
    data = data.dropna(how="all").copy()
    if data.empty:
        raise ValueError("The uploaded file contains no data rows.")

    required_columns = ["Inspection Date", "Shift"] + [p["label"] for p in form["parameters"]]
    missing_columns = [column for column in required_columns if column not in data.columns]
    if missing_columns:
        raise ValueError("Missing columns: " + ", ".join(missing_columns))

    parsed_rows = []
    errors = []
    for index, source in data.iterrows():
        excel_row = index + 2
        inspection_date = pd.to_datetime(source["Inspection Date"], errors="coerce")
        shift = clean_cell(source["Shift"])
        if pd.isna(inspection_date):
            errors.append(f"Row {excel_row}: Inspection Date is invalid.")
        if shift not in SHIFTS:
            errors.append(f"Row {excel_row}: Shift must be one of {', '.join(SHIFTS)}.")

        values = {p["id"]: clean_cell(source[p["label"]]) for p in form["parameters"]}
        for parameter in form["parameters"]:
            if not field_visible(parameter, values):
                continue
            value = values[parameter["id"]]
            if parameter.get("required") and value == "":
                errors.append(f"Row {excel_row}: {parameter['label']} is required.")
                continue
            if parameter["type"] == "number" and value != "":
                numeric = pd.to_numeric(value, errors="coerce")
                if pd.isna(numeric):
                    errors.append(f"Row {excel_row}: {parameter['label']} must be numeric.")
                else:
                    values[parameter["id"]] = float(numeric)
            if parameter["type"] == "choice" and value not in parameter["options"]:
                errors.append(
                    f"Row {excel_row}: {parameter['label']} must be one of "
                    + ", ".join(parameter["options"])
                )
        parsed_rows.append((inspection_date, shift, values))

    if errors:
        raise ValueError("\n".join(errors[:25]))
    return parsed_rows


def normalized_rows(form, inspection_date, shift, values, record_id, created_at):
    rows = []
    for parameter in form["parameters"]:
        if not field_visible(parameter, values):
            continue
        value = values.get(parameter["id"], "")
        rows.append(
            {
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
            }
        )
    return rows


def manual_entry(form):
    inspection_date = st.date_input("Inspection Date *", date.today(), key=f"manual_date_{form['id']}")
    shift = st.selectbox("Shift *", SHIFTS, key=f"manual_shift_{form['id']}")
    values = {}
    for parameter in form["parameters"]:
        if field_visible(parameter, values):
            values[parameter["id"]] = render_field(
                parameter, f"manual_{form['id']}_{parameter['id']}"
            )

    if st.button("Save Manual Entry", type="primary", use_container_width=True):
        missing = []
        for parameter in form["parameters"]:
            if field_visible(parameter, values) and parameter.get("required"):
                value = values.get(parameter["id"])
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing.append(parameter["label"])
        if missing:
            st.error("Required fields missing: " + ", ".join(missing))
            return
        record_id = "QC-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = normalized_rows(
            form, inspection_date, shift, values, record_id, created_at
        )
        try:
            append_rows(rows, f"Add manual quality check {record_id}")
            st.success(f"Manual entry saved. Record ID: {record_id}")
        except Exception as error:
            st.error(f"Save failed: {error}")


def excel_entry(form):
    st.info("Download the form-specific template, complete one inspection per row, then upload the completed file.")
    st.download_button(
        "Download Excel Template",
        template_bytes(form),
        file_name=f"{form['id']}_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    upload = st.file_uploader(
        "Upload completed Excel or CSV",
        type=["xlsx", "csv"],
        key=f"upload_{form['id']}",
    )
    if upload is not None and st.button(
        "Validate and Save Uploaded Rows",
        type="primary",
        use_container_width=True,
        key=f"save_upload_{form['id']}",
    ):
        try:
            parsed = parse_upload(upload, form)
            all_rows = []
            for inspection_date, shift, values in parsed:
                record_id = "QC-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                all_rows.extend(
                    normalized_rows(
                        form,
                        inspection_date.date(),
                        shift,
                        values,
                        record_id,
                        created_at,
                    )
                )
            append_rows(all_rows, f"Add {len(parsed)} uploaded quality checks")
            st.success(f"{len(parsed)} quality-check rows uploaded successfully.")
        except Exception as error:
            st.error(f"Upload failed: {error}")


def operator_entry_page():
    st.title(f"Operator Quality Data Entry | {st.session_state.department}")
    forms = CONFIG["departments"][st.session_state.department]["forms"]
    form = st.selectbox("Quality Check", forms, format_func=lambda item: item["title"])
    st.caption(form["description"])
    manual_tab, excel_tab = st.tabs(["Manual Entry", "Excel Upload"])
    with manual_tab:
        manual_entry(form)
    with excel_tab:
        excel_entry(form)


def control_chart_page():
    st.title("Parameter Control Charts")
    try:
        data, _ = read_data()
    except Exception as error:
        st.error(f"Unable to read GitHub data: {error}")
        return
    data = data[data["Plant"].astype(str).eq(st.session_state.plant)]
    department_col, form_col = st.columns(2)
    department = department_col.selectbox("Department", DEPARTMENTS)
    forms = CONFIG["departments"][department]["forms"]
    form = form_col.selectbox("Quality Check", forms, format_func=lambda item: item["title"])
    filtered = data[
        data["Department"].eq(department) & data["Form ID"].eq(form["id"])
    ].copy()
    if filtered.empty:
        st.info("No data available for the selected quality check.")
        return

    filters = [p for p in form["parameters"] if p.get("role") == "filter"]
    filter_columns = st.columns(min(4, max(1, len(filters))))
    for index, parameter in enumerate(filters):
        source = "Value" if parameter["type"] == "number" else "Text Value"
        options = sorted(
            value
            for value in filtered.loc[
                filtered["Parameter ID"].eq(parameter["id"]), source
            ].dropna().astype(str).unique()
            if value
        )
        selected = filter_columns[index % len(filter_columns)].multiselect(
            parameter["label"], options, key=f"filter_{parameter['id']}"
        )
        if selected:
            record_ids = filtered[
                filtered["Parameter ID"].eq(parameter["id"])
                & filtered[source].astype(str).isin(selected)
            ]["Record ID"]
            filtered = filtered[filtered["Record ID"].isin(record_ids)]

    groups = {}
    for parameter in form["parameters"]:
        if parameter.get("chart_group"):
            groups.setdefault(parameter["chart_group"], []).append(parameter)
    singles = [p for p in form["parameters"] if p.get("chart_type") == "imr"]
    choices = [p["label"] for p in singles] + list(groups)
    selection = st.selectbox("Parameter / Group", choices)

    if selection in groups:
        parameters = groups[selection]
        pivot = filtered[
            filtered["Parameter ID"].isin([p["id"] for p in parameters])
        ].pivot_table(
            index="Record ID", columns="Parameter ID", values="Value", aggfunc="first"
        ).reindex(columns=[p["id"] for p in parameters])
        result = xbar_r(pivot)
        if not result:
            st.info("At least two complete 14-reading subgroups are required.")
            return
    else:
        parameter = next(p for p in singles if p["label"] == selection)
        series = pd.to_numeric(
            filtered.loc[filtered["Parameter ID"].eq(parameter["id"]), "Value"],
            errors="coerce",
        )
        result = imr(series)
        if not result:
            st.info("At least two readings are required.")
            return

    values, center, ucl, lcl, ranges, range_center, range_ucl, range_lcl = result
    x_values = list(range(1, len(values) + 1))
    first = go.Figure(go.Scatter(x=x_values, y=values, mode="lines+markers", name=selection))
    add_limit_lines(first, center, ucl, lcl, len(values))
    first.update_layout(title=("X-bar Chart: " if selection in groups else "Individuals Chart: ") + selection)
    st.plotly_chart(first, use_container_width=True)

    range_x = list(range(1, len(ranges) + 1))
    second = go.Figure(go.Scatter(x=range_x, y=ranges, mode="lines+markers", name="Range"))
    add_limit_lines(second, range_center, range_ucl, range_lcl, len(ranges))
    second.update_layout(title=("R Chart: " if selection in groups else "Moving Range Chart: ") + selection)
    st.plotly_chart(second, use_container_width=True)


def main():
    if not st.session_state.get("plant_ok"):
        with st.form("plant_login"):
            plant = st.selectbox("Plant", PLANTS)
            password = st.text_input("Plant Password", type="password")
            if st.form_submit_button("Continue", use_container_width=True):
                expected = st.secrets.get("plant_passwords", {}).get(slug(plant))
                if password == expected:
                    st.session_state.update(plant=plant, plant_ok=True)
                    st.rerun()
                else:
                    st.error("Incorrect plant password.")
        st.stop()

    module = st.radio(
        "Module", ["Operator Data Entry", "Control Chart Analysis"], horizontal=True
    )
    if module == "Control Chart Analysis":
        control_chart_page()
        return

    if not st.session_state.get("department_ok"):
        with st.form("department_login"):
            department = st.selectbox("Department", DEPARTMENTS)
            password = st.text_input("Department Password", type="password")
            if st.form_submit_button("Open Department", use_container_width=True):
                key = f"{slug(st.session_state.plant)}_{slug(department)}"
                expected = st.secrets.get("department_passwords", {}).get(
                    key, st.secrets.get("DEFAULT_DEPARTMENT_PASSWORD", "Dept@123")
                )
                if password == expected:
                    st.session_state.update(
                        department=department, department_ok=True
                    )
                    st.rerun()
                else:
                    st.error("Incorrect department password.")
        st.stop()
    operator_entry_page()


main()
