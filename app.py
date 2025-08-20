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
def admin_create_custom_field():
    data = request.json or {}
    headers = {"Content-Type": "application/json"}

    # Step 0: Resolve project ID
    try:
        proj_url = f"{JIRA_URL}/rest/api/3/project/{JIRA_PROJECT_KEY}"
        proj_resp = requests.get(proj_url, auth=jira_auth(), headers=headers)
        proj_resp.raise_for_status()
        project_id = proj_resp.json()["id"]
    except Exception as e:
        return jsonify({"error": f"Failed to fetch project ID for {JIRA_PROJECT_KEY}: {str(e)}"}), 400

    # Step 1: Create custom field
    field_payload = {
        "name": data.get("name"),
        "description": data.get("description", "Created via integration app"),
        "type": data.get("field_type", "com.atlassian.jira.plugin.system.customfieldtypes:select"),
        "searcherKey": data.get(
            "searcherKey",
            "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher"
        )
    }
    try:
        resp = requests.post(f"{JIRA_URL}/rest/api/3/field", json=field_payload, auth=jira_auth(), headers=headers)
        resp.raise_for_status()
        custom_field = resp.json()
        field_id = custom_field["id"]
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": "Failed to create custom field", "response": resp.text}), resp.status_code

    # Step 2: Create project-specific context
    try:
        ctx_url = f"{JIRA_URL}/rest/api/3/field/{field_id}/context"
        ctx_payload = {
            "name": f"{JIRA_PROJECT_KEY} Context",
            "projectIds": [project_id],
            "issueTypeIds": []  # empty = all issue types in that project
        }
        ctx_resp = requests.post(ctx_url, json=ctx_payload, auth=jira_auth(), headers=headers)
        ctx_resp.raise_for_status()
        context = ctx_resp.json()["values"][0]
        context_id = context["id"]
    except Exception as e:
        return jsonify({"error": f"Failed to create project-specific context: {str(e)}"}), 400

    # Step 3: Add Approved/Rejected options
    try:
        options_url = f"{JIRA_URL}/rest/api/3/field/{field_id}/context/{context_id}/option"
        options_payload = {
            "options": [{"value": "Approved"}, {"value": "Rejected"}]
        }
        opt_resp = requests.post(options_url, json=options_payload, auth=jira_auth(), headers=headers)
        opt_resp.raise_for_status()
        options = opt_resp.json()
    except Exception as e:
        return jsonify({"error": f"Failed to add options: {str(e)}"}), 400

    # Step 4: Link field to project’s screens
    added_screens, skipped_screens = [], []
    try:
        # Get all screens
        screens_resp = requests.get(f"{JIRA_URL}/rest/api/3/screens", auth=jira_auth(), headers=headers)
        screens_resp.raise_for_status()
        screens = screens_resp.json().get("values", [])

        # Attach only to screens belonging to this project (by name check)
        for screen in screens:
            if JIRA_PROJECT_KEY not in screen["name"]:
                continue  # skip screens from other projects

            try:
                # Get tabs for this screen
                tabs_resp = requests.get(f"{JIRA_URL}/rest/api/3/screens/{screen['id']}/tabs",
                                         auth=jira_auth(), headers=headers)
                tabs_resp.raise_for_status()
                tabs = tabs_resp.json()
                if not tabs:
                    skipped_screens.append({"screen_id": screen["id"], "reason": "no tabs"})
                    continue

                first_tab_id = tabs[0]["id"]

                # Add field to this screen/tab
                field_url = f"{JIRA_URL}/rest/api/3/screens/{screen['id']}/tabs/{first_tab_id}/fields"
                add_resp = requests.post(field_url, json={"fieldId": field_id}, auth=jira_auth(), headers=headers)

                if add_resp.status_code in (200, 201):
                    added_screens.append(screen["id"])
                else:
                    skipped_screens.append({
                        "screen_id": screen["id"],
                        "reason": f"HTTP {add_resp.status_code}: {add_resp.text}"
                    })
            except Exception as e:
                skipped_screens.append({"screen_id": screen["id"], "reason": str(e)})
    except Exception as e:
        skipped_screens.append({"screen_id": None, "reason": f"Failed to fetch screens: {str(e)}"})

    # Final response
    return jsonify({
        "custom_field": custom_field,
        "context": context,
        "options": options,
        "linked_screens": added_screens,
        "skipped_screens": skipped_screens
    }), 201

# =========================
@app.route("/")
def index():
    return "Flask integration hub for Jira <-> External Service (with approvals workflow)!"

if __name__ == "__main__":
    if os.getenv("AUTO_CREATE_WEBHOOK", "false").lower() == "true":
        create_jira_webhook()
    app.run(host="0.0.0.0", port=5000)