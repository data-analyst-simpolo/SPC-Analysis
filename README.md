 Manufacturing SPC & Daily Analysis App

## GitHub structure

```text
repository-root/
├── app.py
├── github_store.py
├── requirements.txt
├── config/
│   └── forms.json
├── data/
│   ├── quality_readings.csv
│   └── spec_limits.csv
└── excel_templates/
    ├── slip_house_process_checks.xlsx
    ├── press_green_tile_thickness_bd.xlsx
    └── kiln_firing_zone_temperature.xlsx
```

## Streamlit secrets for shared GitHub data

```toml
GITHUB_TOKEN = "fine-grained token with Contents: Read and write"
GITHUB_OWNER = "repository owner"
GITHUB_REPO = "repository name"
GITHUB_BRANCH = "main"
```

## Analysis logic

- Observation-wise individual parameters: I-MR chart.
- Observation-wise Press Thickness and Bulk Density subgroups: Xbar-R chart.
- Every observation label shows `Observation N` first and the inspection date below it.
- Day-wise individual parameters: one daily average per date, plotted with I-MR.
- Day-wise subgrouped parameters: average of subgroup averages for each date, one point per date, plotted with I-MR.
- Firing-zone temperatures: zone-wise observation I-MR and date-wise daily-average I-MR.

## Firing-zone fields

K6, K8, K10, S11, S13, S15, all even zones S26-S54, and all odd zones S25-S53.
