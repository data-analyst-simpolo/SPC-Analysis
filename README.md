# Manufacturing SPC & Daily Analysis with Login

Upload all files preserving folder structure. Main file: `app.py`.

Default login credentials (change before use):
- Plant admin: `plant_admin` / `ChangeMe@2026`
- Slip House: `sliphouse_user` / `SlipHouse@2026`
- Press: `press_user` / `Press@2026`
- Kiln: `kiln_user` / `Kiln@2026`

Passwords are stored as SHA-256 hashes in `config/users.json`.

Shared GitHub data requires Streamlit secrets: `GITHUB_TOKEN`, `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_BRANCH`.
