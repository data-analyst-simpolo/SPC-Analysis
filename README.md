# Manufacturing SPC & Daily Analysis - Final Robust Package

Upload every file and folder to the repository, preserving paths. `app.py` is the Streamlit main file.

The data CSV files are intentionally header-only. Do not replace them with blank zero-byte files.

Streamlit secrets:
GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH.

Default users:
- plant_admin / ChangeMe@2026
- sliphouse_user / SlipHouse@2026
- press_user / Press@2026
- kiln_user / Kiln@2026

The application safely handles missing, blank and header-only CSV files; creates GitHub files when absent; stores manual and Excel data; and filters charts by plant, department, parameter and Press size.

