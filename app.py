from flask import Flask, request, jsonify
import requests
import os
import sys

app = Flask(__name__)

# Jira Config
JIRA_URL = "https://metronlabs-team.atlassian.net"
JIRA_USER = "purushottam.kamble@metronlabs.com"
JIRA_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN")  # set in Render dashboard

# Keeper placeholder URL (pretend)
KEEPER_URL = "https://keeper-api-poc/receive-event"

### JIRA → KEEPER
@app.route("/webhooks", methods=["POST"])
def jira_webhook():
    data = request.json or {}

    # Extract relevant fields
    issue = data.get("issue", {})
    fields = issue.get("fields", {})
    user = data.get("user", {})

    event_type = data.get("webhookEvent", "unknown_event")   # FIXED
    issue_key = issue.get("key")
    summary = fields.get("summary")
    status = fields.get("status", {}).get("name")
    triggered_by = user.get("displayName") or user.get("emailAddress")

    keeper_event = {
        "source": "jira",
        "event_type": event_type,
        "issue_key": issue_key,
        "summary": summary,
        "status": status,
        "triggered_by": triggered_by
    }

    print("📢 Jira Event →", keeper_event)
    sys.stdout.flush()
    print("📤 Would send to Keeper:", keeper_event)
    sys.stdout.flush()

    return jsonify({"status": "ok"}), 200



### KEEPER → JIRA
@app.route("/keeper-events", methods=["POST"])
def keeper_webhook():
    data = request.json
    print("👉 Raw Keeper event:", data)
    sys.stdout.flush()

    event_type = data.get("event_type")
    user = data.get("user")

    headers = {"Content-Type": "application/json"}
    auth = (JIRA_USER, JIRA_API_TOKEN)

    # Set correct Jira project key
    project_key = "POC"  # Make sure this project exists in Jira

    # Build base payload with ADF description
    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": "",
            "description": {},
            "issuetype": {"name": "Task"}
        }
    }

    if event_type == "user_created":
        payload["fields"]["summary"] = f"New Keeper user created: {user}"
        payload["fields"]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": f"A new user {user} was created in Keeper."}
                    ]
                }
            ]
        }

    elif event_type == "user_deleted":
        payload["fields"]["summary"] = f"Keeper user deleted: {user}"
        payload["fields"]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": f"User {user} was deleted in Keeper."}
                    ]
                }
            ]
        }

    else:
        print(f"⚠️ Unknown event_type: {event_type}")
        sys.stdout.flush()
        return jsonify({"status": "ignored"}), 200

    # Attempt to create Jira issue
    try:
        resp = requests.post(f"{JIRA_URL}/rest/api/3/issue", json=payload, auth=auth, headers=headers)
        resp.raise_for_status()
        print("✅ Jira issue created:", resp.json())
    except requests.exceptions.HTTPError as e:
        print("❌ Jira API HTTP error:", e)
        print("Response:", resp.text)
    except Exception as e:
        print("❌ Unexpected error:", e)
    sys.stdout.flush()

    return jsonify({"status": "ok"}), 200



@app.route("/")
def index():
    return "Flask sync hub for Jira <-> Keeper!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
