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
# Helper: Get Project ID
# =========================
def get_project_id(project_key):
    url = f"{JIRA_URL}/rest/api/3/project/{project_key}"
    resp = requests.get(url, auth=jira_auth(), headers=headers)
    resp.raise_for_status()
    project = resp.json()
    print("Project response:", project)
    sys.stdout.flush()
    return project["id"], project

# =========================
# Helper: Create Issue Type
# =========================
def create_issue_type(name, description=""):
    url = f"{JIRA_URL}/rest/api/3/issuetype"
    payload = {"name": name, "description": description, "type": "standard"}
    resp = requests.post(url, json=payload, auth=jira_auth(), headers=headers)
    resp.raise_for_status()
    return resp.json()

# =========================
# Helper: Get Issue Type Scheme for Project
# =========================
def get_issue_type_scheme_id(project_id):
    url = f"{JIRA_URL}/rest/api/3/issuetypescheme/project?projectId={project_id}"
    resp = requests.get(url, auth=jira_auth(), headers=headers)
    resp.raise_for_status()
    schemes = resp.json().get("issueTypeSchemeProjects", [])
    if not schemes:
        raise Exception("No issue type scheme found for project.")
    return schemes[0]["issueTypeScheme"]["id"]

# =========================
# Helper: Get Issue Types in Scheme
# =========================
def get_issue_types_in_scheme(scheme_id):
    url = f"{JIRA_URL}/rest/api/3/issuetypescheme/{scheme_id}/issuetype"
    resp = requests.get(url, auth=jira_auth(), headers=headers)
    resp.raise_for_status()
    return [it["id"] for it in resp.json().get("issueTypes", [])]

# =========================
# Helper: Update Issue Type Scheme
# =========================
def update_issue_type_scheme(scheme_id, updated_issue_type_ids):
    url = f"{JIRA_URL}/rest/api/3/issuetypescheme/{scheme_id}/issuetype"
    payload = {"issueTypeIds": updated_issue_type_ids}
    resp = requests.put(url, json=payload, auth=jira_auth(), headers=headers)
    resp.raise_for_status()
    return resp.json()

# =========================
# Helper: Create Custom Field
# =========================
def create_custom_field(name="Approval Status", description="Approve/Reject field"):
    url = f"{JIRA_URL}/rest/api/3/field"
    payload = {
        "name": name,
        "description": description,
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:select"
    }
    resp = requests.post(url, json=payload, auth=jira_auth(), headers=headers)
    resp.raise_for_status()
    return resp.json()

# =========================
# Helper: Create Field Context
# =========================
def create_field_context(field_id, context_name, project_id, issue_type_id):
    url = f"{JIRA_URL}/rest/api/3/field/{field_id}/context"
    payload = {
        "name": context_name,
        "description": f"Context for {context_name}",
        "projectIds": [project_id],
        "issueTypeIds": [issue_type_id]
    }
    resp = requests.post(url, json=payload, auth=jira_auth(), headers=headers)
    resp.raise_for_status()
    return resp.json()

# =========================
# Helper: Add Dropdown Options
# =========================
def add_dropdown_options(field_id, context_id, options_list):
    url = f"{JIRA_URL}/rest/api/3/field/{field_id}/context/{context_id}/option"
    payload = {"options": [{"value": option} for option in options_list]}
    resp = requests.post(url, json=payload, auth=jira_auth(), headers=headers)
    resp.raise_for_status()
    return resp.json()

# =========================
# API: Create Issue Type + Field
# =========================
@app.route("/admin/create-issue-type", methods=["POST"])
def create_issue_type_with_field():
    data = request.get_json()
    name = data.get("name")
    description = data.get("description", "")

    try:
        # Step 1: Create Issue Type globally
        issue_type = create_issue_type(name, description)
        issue_type_id = issue_type["id"]

        # Step 2: Get Project Info
        project_id, project = get_project_id(JIRA_PROJECT_KEY)
        project_type = project["projectTypeKey"]
        simplified = project.get("simplified", False)

        # Step 3: Handle issue type scheme for software projects
        scheme_updated = False
        note = ""

        if project_type == "software" and not simplified:
            # Classic software project
            try:
                scheme_id = get_issue_type_scheme_id(project_id)
                existing_ids = get_issue_types_in_scheme(scheme_id)
                if issue_type_id not in existing_ids:
                    updated_ids = existing_ids + [issue_type_id]
                    update_issue_type_scheme(scheme_id, updated_ids)
                scheme_updated = True
                note = f"Issue type added to project scheme {scheme_id}"
            except Exception:
                # Scheme missing → create new scheme and associate
                url = f"{JIRA_URL}/rest/api/3/issuetypescheme"
                payload = {
                    "name": f"{project['name']} Scheme",
                    "issueTypeIds": [it["id"] for it in project["issueTypes"]] + [issue_type_id]
                }
                resp = requests.post(url, json=payload, auth=jira_auth(), headers=headers)
                resp.raise_for_status()
                new_scheme_id = resp.json()["id"]

                # Associate scheme with project
                url = f"{JIRA_URL}/rest/api/3/issuetypescheme/project"
                payload = {"projectId": project_id, "issueTypeSchemeId": new_scheme_id}
                resp = requests.put(url, json=payload, auth=jira_auth(), headers=headers)
                resp.raise_for_status()

                scheme_updated = True
                note = f"Issue type scheme created and associated with project {project_id}"

        else:
            # Business project or next-gen software
            note = "Project is business or simplified software. Issue type exists globally but may not appear in project UI."

        # Step 4: Create Custom Field
        field = create_custom_field()
        field_id = field["id"]

        # Step 5: Create Field Context
        context_name = f"{name} Context"
        context = create_field_context(field_id, context_name, project_id, issue_type_id)
        context_id = context["id"]

        # Step 6: Add Dropdown Options
        options = add_dropdown_options(field_id, context_id, ["Approved", "Rejected"])

        return jsonify({
            "issue_type": issue_type,
            "custom_field": field,
            "context": context,
            "options": options,
            "scheme_updated": scheme_updated,
            "note": note
        })

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": str(e),
            "response": getattr(e.response, "text", "")
        }), 500


# =========================
@app.route("/")
def index():
    return "Flask integration hub for Jira <-> External Service (with approvals workflow)!"

if __name__ == "__main__":
    if os.getenv("AUTO_CREATE_WEBHOOK", "false").lower() == "true":
        create_jira_webhook()
    app.run(host="0.0.0.0", port=5000)