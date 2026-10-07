# Manufacturing SPC & Daily Analysis Portal

Upload the entire package to GitHub without changing the folder structure. Main file: `app.py`.

## Plants
- Maliya
- Unit 1
- Unit 2
- Unit 3

## Default credentials
- Plant admin: `plant_admin` / `ChangeMe@2026`
- Slip House: `sliphouse_user` / `SlipHouse@2026`
- Press: `press_user` / `Press@2026`
- Kiln: `kiln_user` / `Kiln@2026`

## Press Excel upload
The app accepts `press_green_tile_thickness_bd.xlsx` exactly as supplied, including blank spacer columns, mixed time formats, `B.D 13`, `Bulk Density 13`, `Bulk Density 14`, and Remarks.

## Shared GitHub storage
Set `GITHUB_TOKEN`, `GITHUB_OWNER`, `GITHUB_REPO`, and `GITHUB_BRANCH` in Streamlit secrets.
