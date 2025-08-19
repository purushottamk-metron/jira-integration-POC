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
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")  # Atlassian API token
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "SMS")  # must exist in Jira
EXTERNAL_SERVICE_URL = os.getenv("EXTERNAL_SERVICE_URL", "https://jira-integration-poc.onrender.com")

# =========================
# Utility: Create Jira webhook
# =========================
def create_jira_webhook():
    """Programmatically create Jira webhook (requires admin API token)."""
    url = f"{JIRA_URL}/rest/webhooks/1.0/webhook"
    headers = {"Content-Type": "application/json"}
    auth = (JIRA_USER, JIRA_API_TOKEN)

    payload = {
        "name": "Integration Webhook",
        "url": f"{EXTERNAL_SERVICE_URL}/jira-events",
        "events": ["jira:issue_created", "jira:issue_updated"],
        "filters": {
            "issue-related-events-section": f"project = {JIRA_PROJECT_KEY}"
        },
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
# JIRA → External Service
# =========================
@app.route("/jira-events", methods=["POST"])
def jira_webhook():
    data = request.json or {}

    issue = data.get("issue", {})
    fields = issue.get("fields", {})
    user = data.get("user", {})

    event_type = data.get("webhookEvent", "unknown_event")
    issue_key = issue.get("key")
    summary = fields.get("summary")
    status = fields.get("status", {}).get("name")
    triggered_by = user.get("displayName") or user.get("emailAddress")

    event_payload = {
        "source": "jira",
        "event_type": event_type,
        "issue_key": issue_key,
        "summary": summary,
        "status": status,
        "triggered_by": triggered_by
    }

    print("📢 Incoming Jira Event:", event_payload)
    sys.stdout.flush()

    # Normally send to external service (mocked here)
    print("📤 Would forward to external service:", event_payload)
    sys.stdout.flush()

    return jsonify({"status": "ok"}), 200

# =========================
# External Service → JIRA
# =========================
@app.route("/external-events", methods=["POST"])
def external_webhook():
    data = request.json
    print("👉 Incoming external event:", data)
    sys.stdout.flush()

    event_type = data.get("event_type")
    user = data.get("user")

    headers = {"Content-Type": "application/json"}
    auth = (JIRA_USER, JIRA_API_TOKEN)

    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": "",
            "description": {},
            "issuetype": {"name": "Task"}
        }
    }

    if event_type == "user_created":
        payload["fields"]["summary"] = f"New user created: {user}"
        payload["fields"]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": f"A new user {user} was created."}]}]
        }

    elif event_type == "user_deleted":
        payload["fields"]["summary"] = f"User deleted: {user}"
        payload["fields"]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": f"User {user} was deleted."}]}]
        }

    elif event_type == "user_updated":
        payload["fields"]["summary"] = f"User updated: {user}"
        payload["fields"]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": f"User {user} was updated. Please review."}]}]
        }

    else:
        print(f"⚠️ Ignoring unknown event_type: {event_type}")
        sys.stdout.flush()
        return jsonify({"status": "ignored"}), 200

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

# =========================
@app.route("/")
def index():
    return "Flask integration hub for Jira <-> External Service!"

if __name__ == "__main__":
    # Optional: auto-create webhook on startup
    if os.getenv("AUTO_CREATE_WEBHOOK", "false").lower() == "true":
        create_jira_webhook()

    app.run(host="0.0.0.0", port=5000)