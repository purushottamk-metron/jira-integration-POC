from flask import Flask, request, jsonify
import requests
import os
import sys

app = Flask(__name__)

# =========================
# Config (from environment)
# =========================
JIRA_URL = os.getenv("JIRA_URL", "https://metronlabs-team.atlassian.net")
JIRA_USER = os.getenv("JIRA_USER", "purushottam.kamble@metronlabs.com")  # e.g. email
JIRA_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN")  # Atlassian API token
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "AV")  # must exist in Jira
EXTERNAL_SERVICE_URL = os.getenv("EXTERNAL_SERVICE_URL", "https://jira-integration-poc.onrender.com")
APPROVAL_FIELD_NAME = os.getenv("APPROVAL_FIELD_NAME", "Approval Status")

def jira_auth():
    return (JIRA_USER, JIRA_API_TOKEN)
headers = {"Content-Type": "application/json"} 

# ========================= 
# Utility: Create Jira webhook 
# ========================= 
def create_jira_webhook(): 
    """Ensure Jira webhook exists (create if missing).""" 
    url = f"{JIRA_URL}/rest/webhooks/1.0/webhook" 
    auth = jira_auth() 

    try: 
        resp = requests.get(url, auth=auth, headers=headers) 
        resp.raise_for_status() 
        existing_hooks = resp.json() 
    except Exception as e: 
        print("❌ Failed to fetch Jira webhooks:", e) 
        sys.stdout.flush() 
        return 
    
    webhook_url = f"{EXTERNAL_SERVICE_URL}/jira-events" 

    for hook in existing_hooks: 
        if hook.get("url") == webhook_url: 
            print(f"ℹ️ Webhook already exists, skipping creation (id={hook.get('self')})") 
            sys.stdout.flush() 
            return 

    payload = { 
        "name": "Integration Webhook", 
        "url": webhook_url, 
        "events": ["jira:issue_created", "jira:issue_updated"], 
        "filters": {"issue-related-events-section": f"project = {JIRA_PROJECT_KEY}"}, 
        "excludeBody": False 
    } 

    try: 
        resp = requests.post(url, json=payload, auth=auth, headers=headers) 
        resp.raise_for_status() 
        print("✅ Jira webhook created:", resp.json()) 
    except requests.exceptions.HTTPError as e: 
        print("❌ Jira webhook creation failed:", e) 
        print("Response:", resp.text) 
    except Exception as e: 
        print("❌ Unexpected error creating webhook:", e) 
    sys.stdout.flush()
# =========================
# Utility: Jira API helpers
# =========================
def get_custom_field_id(field_name):
    """Find Jira custom field ID by name."""
    url = f"{JIRA_URL}/rest/api/3/field"
    resp = requests.get(url, auth=jira_auth())
    resp.raise_for_status()
    for field in resp.json():
        if field.get("name") == field_name:
            return field.get("id")
    return None

def update_jira_issue(issue_key, fields_update):
    """Update fields on a Jira issue."""
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}"
    headers = {"Content-Type": "application/json"}
    resp = requests.put(url, json={"fields": fields_update}, auth=jira_auth(), headers=headers)
    resp.raise_for_status()
    return resp.json() if resp.text else {}

# =========================
# JIRA → External Service
# =========================
@app.route("/jira-events", methods=["POST"])
def jira_webhook():
    data = request.json or {}
    issue = data.get("issue", {})
    fields = issue.get("fields", {})
    issue_key = issue.get("key")
    event_type = data.get("webhookEvent", "unknown_event")

    summary = fields.get("summary")
    status = fields.get("status", {}).get("name")

    # Look for approval status custom field
    approval_field_id = get_custom_field_id(APPROVAL_FIELD_NAME)
    approval_value = fields.get(approval_field_id) if approval_field_id else None

    print(f"📢 Jira Event {event_type} on {issue_key}: Approval={approval_value}")
    sys.stdout.flush()

    # Forward to external service only when Approval is set
    if approval_value in ("Approved", "Rejected"):
        payload = {
            "event_type": "access_request_update",
            "issue_key": issue_key,
            "summary": summary,
            "status": status,
            "approval": approval_value
        }
        try:
            resp = requests.post(f"{EXTERNAL_SERVICE_URL}/external-events", json=payload)
            resp.raise_for_status()
            print(f"📤 Forwarded to external service: {payload}")
        except Exception as e:
            print("❌ Failed to forward to external service:", e)

    return jsonify({"status": "ok"}), 200

# =========================
# External Service → JIRA
# =========================
@app.route("/external-events", methods=["POST"])
def external_webhook():
    data = request.json or {}
    issue_key = data.get("issue_key")
    approval = data.get("approval")
    result_message = data.get("result", "No result provided")

    if not issue_key:
        return jsonify({"error": "Missing issue_key"}), 400

    # Update Jira ticket with external service result
    try:
        fields_update = {
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{
                        "type": "text",
                        "text": f"External service processed request: {approval}. Result: {result_message}"
                    }]
                }]
            }
        }
        update_jira_issue(issue_key, fields_update)
        print(f"✅ Updated Jira issue {issue_key} with external result")
    except Exception as e:
        print("❌ Failed to update Jira issue:", e)

    return jsonify({"status": "ok"}), 200

# =========================
# Helper: Get project ID
# =========================
def get_project_id(project_key):
    url = f"{JIRA_URL}/rest/api/3/project/{project_key}"
    resp = requests.get(url, auth=jira_auth(), headers=headers)
    resp.raise_for_status()
    project = resp.json()
    # Debug log
    print("Project response:", project)
    sys.stdout.flush()
    return project["id"]   # this is the numeric ID we need

def safe_json(resp):
    """Safely parse JSON from a response, return empty dict if no content."""
    try:
        return resp.json()
    except ValueError:
        return {}

# =========================
# Create Issue Type + Field + Screen + Scheme
# =========================
@app.route("/admin/create-access-request", methods=["POST"])
def create_access_request():
    data = request.get_json()
    name = data.get("name", "Access Request")
    description = data.get("description", "Workflow for approvals")

    try:
        # 1️⃣ Get project ID
        project_id = get_project_id(JIRA_PROJECT_KEY)

        # 2️⃣ Create/Get Issue Type
        issue_types_resp = requests.get(f"{JIRA_URL}/rest/api/3/issuetype", auth=jira_auth(), headers=headers)
        issue_types_resp.raise_for_status()
        existing_issue_types = safe_json(issue_types_resp)
        issue_type = next((i for i in existing_issue_types if i["name"] == name), None)
        if not issue_type:
            payload = {"name": name, "description": description, "type": "standard"}
            resp = requests.post(f"{JIRA_URL}/rest/api/3/issuetype", json=payload, auth=jira_auth(), headers=headers)
            resp.raise_for_status()
            issue_type = safe_json(resp)
        issue_type_id = issue_type["id"]

        # 3️⃣ Create/Get Custom Field
        fields_resp = requests.get(f"{JIRA_URL}/rest/api/3/field", auth=jira_auth(), headers=headers)
        fields_resp.raise_for_status()
        existing_fields = safe_json(fields_resp)
        field = next((f for f in existing_fields if f["name"] == "Approval Status"), None)
        if not field:
            payload = {
                "name": "Approval Status",
                "description": "Approve/Reject field",
                "type": "com.atlassian.jira.plugin.system.customfieldtypes:select"
            }
            resp = requests.post(f"{JIRA_URL}/rest/api/3/field", json=payload, auth=jira_auth(), headers=headers)
            resp.raise_for_status()
            field = safe_json(resp)
        field_id = field["id"]

        # 4️⃣ Create or get Admin Screen for Access Request
        screens_resp = requests.get(f"{JIRA_URL}/rest/api/3/screens", auth=jira_auth(), headers=headers)
        screens_resp.raise_for_status()
        screens_list = safe_json(screens_resp).get("values", [])
        screen = next((s for s in screens_list if s["name"] == f"{name} Admin Screen"), None)
        if not screen:
            payload = {"name": f"{name} Admin Screen", "description": "Screen for admin updates"}
            resp = requests.post(f"{JIRA_URL}/rest/api/3/screens", json=payload, auth=jira_auth(), headers=headers)
            resp.raise_for_status()
            screen = safe_json(resp)
        
        screen_id = screen["id"]

        # 5️⃣ Add custom field to first tab (tab 1)
        requests.post(
            f"{JIRA_URL}/rest/api/3/screens/{screen_id}/tabs/1/fields",
            json={"fieldId": field_id},
            auth=jira_auth(),
            headers=headers
        )

        # 6️⃣ Create or get Screen Scheme for Access Request
        screenschemes_resp = requests.get(f"{JIRA_URL}/rest/api/3/screenscheme", auth=jira_auth(), headers=headers)
        screenschemes_resp.raise_for_status()
        existing_schemes = safe_json(screenschemes_resp).get("values", [])
        screen_scheme = next((s for s in existing_schemes if s["name"] == f"{name} Screen Scheme"), None)
        if not screen_scheme:
            payload = {
                "name": f"{name} Screen Scheme",
                "description": f"Screen scheme for {name}",
                "screens": {
                    "create": screen_id,
                    "edit": screen_id,
                    "view": screen_id
                }
            }
            resp = requests.post(f"{JIRA_URL}/rest/api/3/screenscheme", json=payload, auth=jira_auth(), headers=headers)
            resp.raise_for_status()
            screen_scheme = safe_json(resp)

        screen_scheme_id = screen_scheme["id"]

        # 7️⃣ Attach Screen Scheme to project's Issue Type Screen Scheme
        its_resp = requests.get(f"{JIRA_URL}/rest/api/3/issuetypescreenscheme/project?projectId={project_id}",
                                auth=jira_auth(), headers=headers)
        its_resp.raise_for_status()
        its_values = safe_json(its_resp).get("values", [])

        if not its_values:
            return jsonify({"error": "No Issue Type Screen Scheme found for project"}), 400

        its_scheme_id = its_values[0]["issueTypeScreenScheme"]["id"]

        # Update mapping for Access Request only
        mapping_payload = {
            "issueTypeMappings": [
                {"issueTypeId": issue_type_id, "screenSchemeId": screen_scheme_id}
            ]
        }
        mapping_resp = requests.put(
            f"{JIRA_URL}/rest/api/3/issuetypescreenscheme/{its_scheme_id}/mapping",
            json=mapping_payload,
            auth=jira_auth(),
            headers=headers
        )
        mapping_resp.raise_for_status()

        return jsonify({
            "issue_type": issue_type,
            "custom_field": field,
            "screen_id": screen_id,
            "screen_scheme": screen_scheme
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e), "response": getattr(e.response, "text", "")}), 500



# =========================
@app.route("/")
def index():
    return "Flask integration hub for Jira <-> External Service (with approvals workflow)!"

if __name__ == "__main__":
    if os.getenv("AUTO_CREATE_WEBHOOK", "false").lower() == "true":
        create_jira_webhook()
    app.run(host="0.0.0.0", port=5000)