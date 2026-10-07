# Manufacturing SPC Portal - Subgroup and Capability Version

## Correct Press logic
- Thickness is one parameter.
- Each Press inspection contributes one Thickness observation containing 12 samples.
- Bulk Density is one parameter.
- Each Press inspection contributes one Bulk Density observation containing 12 samples.
- The app uses X-bar R for observation-wise Thickness and Bulk Density analysis with subgroup size n=12.
- The supplied Press workbook maps TH.2-TH.13 to Thickness samples 1-12 and B.D 2-B.D 13 to Bulk Density samples 1-12.
- The separate trailing Bulk Density 13 and Bulk Density 14 columns are preserved by the importer but are not mixed into the 12-sample subgroup.

## Capability
The analysis page accepts LSL and USL and displays Cp and Cpk. For n=12 subgroups, within-process sigma is estimated as R-bar / d2, where d2=3.258.

## Plants
Maliya, Tirupati Unit 1, Tirupati Unit 2, Tirupati Unit 3.

## Default credentials
- plant_admin / ChangeMe@2026
- sliphouse_user / SlipHouse@2026
- press_user / Press@2026
- kiln_user / Kiln@2026

Upload all files preserving the folder structure. Main file: app.py.
