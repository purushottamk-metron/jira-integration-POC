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
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "SMS")  # must exist in Jira
EXTERNAL_SERVICE_URL = os.getenv("EXTERNAL_SERVICE_URL", "https://jira-integration-poc.onrender.com")
APPROVAL_FIELD_NAME = os.getenv("APPROVAL_FIELD_NAME", "Approval Status")

def jira_auth():
    return (JIRA_USER, JIRA_API_TOKEN)

# ========================= 
# Utility: Create Jira webhook 
# ========================= 
def create_jira_webhook(): 
    """Ensure Jira webhook exists (create if missing).""" 
    url = f"{JIRA_URL}/rest/webhooks/1.0/webhook" 
    headers = {"Content-Type": "application/json"} 
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
# Admin: Create Issue Type and Link to Project
# =========================
@app.route("/admin/create-issue-type", methods=["POST"])
def admin_create_issue_type():
    data = request.json or {}
    url = f"{JIRA_URL}/rest/api/3/issuetype"
    headers = {"Content-Type": "application/json"}
    payload = {
        "name": data.get("name"),
        "description": data.get("description", "Created via integration app"),
        "type": data.get("type", "standard")  # "standard" or "subtask"
    }
    try:
        # Step 1: Create issue type
        resp = requests.post(url, json=payload, auth=jira_auth(), headers=headers)
        resp.raise_for_status()
        issue_type = resp.json()

        # Step 2: Associate issue type with project
        project_url = f"{JIRA_URL}/rest/api/3/issuetype/project"
        project_payload = {
            "issueTypeId": issue_type["id"],
            "projectId": data.get("project_id") or JIRA_PROJECT_KEY
        }
        assoc_resp = requests.put(project_url, json=project_payload, auth=jira_auth(), headers=headers)
        assoc_resp.raise_for_status()

        return jsonify({"issue_type": issue_type, "association": assoc_resp.json()}), 201
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": str(e), "response": resp.text}), resp.status_code

# =========================
# Admin: Create Custom Field and Link to Project Screens
# =========================
@app.route("/admin/create-custom-field", methods=["POST"])
def create_custom_field():
    data = request.get_json()
    name = data.get("name")
    description = data.get("description", "")
    field_type = data.get("field_type")

    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    try:
        # 1️⃣ Create custom field
        field_payload = {
            "name": name,
            "description": description,
            "type": field_type,
            "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher"
        }
        field_resp = requests.post(
            f"{JIRA_URL}/rest/api/3/field",
            auth=jira_auth(),
            headers=headers,
            json=field_payload,
        )
        field_resp.raise_for_status()
        custom_field = field_resp.json()
        field_key = custom_field.get("id")  # e.g. "customfield_10095"

        # 2️⃣ Get project ID
        proj_resp = requests.get(
            f"{JIRA_URL}/rest/api/3/project/{JIRA_PROJECT_KEY}",
            auth=jira_auth(),
            headers=headers,
        )
        proj_resp.raise_for_status()
        project_id = proj_resp.json()["id"]

        # 3️⃣ Create project-specific context
        ctx_url = f"{JIRA_URL}/rest/api/3/field/{field_key}/context"
        ctx_payload = {
            "name": f"{JIRA_PROJECT_KEY} Context",
            "description": f"Context for {name} in {JIRA_PROJECT_KEY}",
            "projectIds": [project_id],
            "issueTypeIds": []  # all issue types
        }
        ctx_resp = requests.post(ctx_url, json=ctx_payload, auth=jira_auth(), headers=headers)
        ctx_resp.raise_for_status()
        ctx_data = ctx_resp.json()
        context_id = ctx_data["values"][0]["id"]

        # 4️⃣ Add options to the field context
        options_url = f"{JIRA_URL}/rest/api/3/field/{field_key}/context/{context_id}/option"
        options_payload = {"options": [{"value": "Approved"}, {"value": "Rejected"}]}
        opt_resp = requests.post(options_url, json=options_payload, auth=jira_auth(), headers=headers)
        opt_resp.raise_for_status()
        options = opt_resp.json()

        # 5️⃣ Add field to all screens of the project
        screens_resp = requests.get(f"{JIRA_URL}/rest/api/3/screens", auth=jira_auth(), headers=headers)
        screens_resp.raise_for_status()
        screens = screens_resp.json().get("values", [])

        linked_screens = []
        skipped_screens = []
        for screen in screens:
            screen_id = screen["id"]
            try:
                # get first tab of screen
                tabs_resp = requests.get(
                    f"{JIRA_URL}/rest/api/3/screens/{screen_id}/tabs",
                    auth=jira_auth(),
                    headers=headers,
                )
                tabs_resp.raise_for_status()
                tabs = tabs_resp.json()
                if not tabs:
                    continue
                tab_id = tabs[0]["id"]

                # add field to tab
                add_resp = requests.post(
                    f"{JIRA_URL}/rest/api/3/screens/{screen_id}/tabs/{tab_id}/fields",
                    json={"fieldId": field_key},
                    auth=jira_auth(),
                    headers=headers,
                )
                add_resp.raise_for_status()
                linked_screens.append(screen_id)
            except Exception as e:
                skipped_screens.append({"screen_id": screen_id, "reason": str(e)})

        return jsonify({
            "custom_field": custom_field,
            "context": ctx_data,
            "options": options,
            "linked_screens": linked_screens,
            "skipped_screens": skipped_screens,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 400

# =========================
@app.route("/")
def index():
    return "Flask integration hub for Jira <-> External Service (with approvals workflow)!"

if __name__ == "__main__":
    if os.getenv("AUTO_CREATE_WEBHOOK", "false").lower() == "true":
        create_jira_webhook()
    app.run(host="0.0.0.0", port=5000)