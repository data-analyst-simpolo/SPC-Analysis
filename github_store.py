import base64
import os
import requests

API = "https://api.github.com"


def configured():
    return all(str(os.getenv(k, "")).strip() for k in ("GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO"))


def _headers():
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Cache-Control": "no-cache",
    }


def _url(path):
    return f"{API}/repos/{os.environ['GITHUB_OWNER']}/{os.environ['GITHUB_REPO']}/contents/{path}"


def read_text(path):
    if not configured():
        return None
    response = requests.get(
        _url(path), headers=_headers(), params={"ref": os.getenv("GITHUB_BRANCH", "main")}, timeout=30
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    return base64.b64decode(payload.get("content", "")).decode("utf-8-sig")


def write_text(path, text, message="Update SPC data"):
    if not configured():
        return False
    branch = os.getenv("GITHUB_BRANCH", "main")
    for _ in range(8):
        current = requests.get(_url(path), headers=_headers(), params={"ref": branch}, timeout=30)
        if current.status_code == 404:
            sha = None
        else:
            current.raise_for_status()
            sha = current.json().get("sha")
        body = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        result = requests.put(_url(path), headers=_headers(), json=body, timeout=30)
        if result.status_code in (200, 201):
            return True
        if result.status_code not in (409, 422):
            result.raise_for_status()
    raise RuntimeError("GitHub file update conflict. Please click Import/Save once again.")
