# Quality Parameter Control App

The app supports:

- Plant login for Tirupati and Maliya
- Separate department passwords for Slip House, Press and Spray Dryer
- Manual operator data entry
- Form-specific Excel template download and bulk Excel/CSV upload
- GitHub-backed CSV storage
- I-MR charts for single continuous readings
- X-bar and R charts for Thickness 1-14 and Bulk Density 1-14

## Excel upload flow

1. Open Operator Data Entry.
2. Select the department and quality-check form.
3. Open **Excel Upload**.
4. Download the form-specific template.
5. Enter one complete quality inspection per row.
6. Upload the completed `.xlsx` or `.csv` file.
7. Select **Validate and Save Uploaded Rows**.

The validator checks required columns, mandatory fields, numeric fields, choice values, shifts, and conditional fields.
