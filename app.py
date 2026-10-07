from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"
USERS = ROOT / "config" / "users.json"

if not APP.exists():
    raise FileNotFoundError("Place update_plants.py in the repository root beside app.py.")
if not USERS.exists():
    raise FileNotFoundError("config/users.json was not found.")

text = APP.read_text(encoding="utf-8")
# 1. Add the shared plant master immediately after SHIFTS.
old = "SHIFTS=['A','B','C','General','Not provided']"
new = "SHIFTS=['A','B','C','General','Not provided']\nPLANTS=['Maliya','Tirupati Unit 1','Tirupati Unit 2','Tirupati Unit 3']"
if old not in text and "PLANTS=['Maliya'" not in text:
    raise RuntimeError("Could not find the SHIFTS configuration in app.py.")
text = text.replace(old, new, 1)

# 2. Make the login plant selector use all four plants.
text = text.replace("plant=st.selectbox('Plant',['Maliya'])", "plant=st.selectbox('Plant',PLANTS)")

# 3. Authorize against the user's allowed plant list and preserve backward compatibility.
old_auth = "u=USERS.get(username.strip());ok=u and hashlib.sha256(password.encode()).hexdigest()==u['password_sha256'] and plant==u['plant']"
new_auth = "u=USERS.get(username.strip());allowed_plants=(u.get('plants') or [u.get('plant')]) if u else [];ok=u and hashlib.sha256(password.encode()).hexdigest()==u['password_sha256'] and plant in allowed_plants"
if old_auth not in text:
    raise RuntimeError("Could not find the login authorization line in app.py.")
text = text.replace(old_auth, new_auth, 1)

# 4. Store the selected plant in the authenticated session.
old_session = "if ok:st.session_state.logged=True;st.session_state.user=u;st.rerun()"
new_session = "if ok:st.session_state.logged=True;st.session_state.user=u;st.session_state.selected_plant=plant;st.rerun()"
if old_session not in text:
    raise RuntimeError("Could not find the login session line in app.py.")
text = text.replace(old_session, new_session, 1)

# 5. Save every manual and Excel-uploaded record against the selected plant.
text = text.replace("'Plant':'Maliya'", "'Plant':st.session_state.get('selected_plant','Maliya')")

# 6. Show the selected plant in the sidebar.
text = text.replace("st.caption('Plant: '+st.session_state.user['plant'])", "st.caption('Plant: '+st.session_state.get('selected_plant','Maliya'))")

# 7. Restrict data and analysis to the selected plant as well as the department.
old_readings = "x=readings();x=x[x['Form ID'].eq(form['id'])]"
new_readings = "x=readings();x=x[(x['Plant'].astype(str).eq(st.session_state.get('selected_plant','Maliya'))) & (x['Form ID'].eq(form['id']))]"
if old_readings not in text:
    raise RuntimeError("Could not find the form data filter in app.py.")
text = text.replace(old_readings, new_readings, 1)

old_data = "x=readings();x=x[x.Department.isin(departments())]"
new_data = "x=readings();x=x[(x['Plant'].astype(str).eq(st.session_state.get('selected_plant','Maliya'))) & (x.Department.isin(departments()))]"
if old_data not in text:
    raise RuntimeError("Could not find the data-page filter in app.py.")
text = text.replace(old_data, new_data, 1)

APP.write_text(text, encoding="utf-8")

users = json.loads(USERS.read_text(encoding="utf-8"))
for user in users.get("users", {}).values():
    user.pop("plant", None)
    user["plants"] = ["Maliya", "Tirupati Unit 1", "Tirupati Unit 2", "Tirupati Unit 3"]
USERS.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")

print("Plant update completed successfully.")
print("Plants: Maliya, Tirupati Unit 1, Tirupati Unit 2, Tirupati Unit 3")
