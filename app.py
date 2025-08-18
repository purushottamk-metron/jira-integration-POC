from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Jira Config
JIRA_URL = "https://metronlabs-team.atlassian.net"
JIRA_USER = "purushottam.kamble@metronlabs.com"
JIRA_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN")  # set in Render dashboard

# Keeper placeholder (replace with actual Keeper API base URL)
KEEPER_URL = "https://keeper-api-poc/receive-event"

# ------------------------
# Jira -> Keeper
# ------------------------
@app.route("/webhooks", methods=["POST"])
def jira_webhook():
    data = request.json or {}
    issue = data.get("issue")
    user = data.get("user", {})
    triggered_by = user.get("emailAddress")

    if not issue:
        print("⚠️ No issue info in payload:", data)
        return jsonify({"status": "ignored", "reason": "no issue in payload"}), 200

    issue_key = issue.get("key")
    fields = issue.get("fields", {})
    summary = fields.get("summary", "N/A")
    status = fields.get("status", {}).get("name", "N/A")

    print(f"👉 Jira event for {issue_key} (summary={summary}, status={status}) by {triggered_by}")

    # Avoid loops
    if triggered_by == JIRA_USER:
        print("⏩ Skipping self-triggered Jira event")
        return jsonify({"status": "skipped"}), 200

    # Build Keeper payload
    keeper_payload = {
        "source": "jira",
        "issue_key": issue_key,
        "summary": summary,
        "status": status,
        "triggered_by": triggered_by,
    }

    print("📤 Would send to Keeper:", keeper_payload)

    try:
        resp = requests.post(KEEPER_URL, json=keeper_payload, timeout=5)
        print("👉 Forwarded to Keeper:", resp.status_code, resp.text)
    except Exception:
        print("⚠️ Keeper not available (simulated POC only)")

    return jsonify({"status": "ok"}), 200


# ------------------------
# Keeper -> Jira
# ------------------------
@app.route("/keeper-webhook", methods=["POST"])
def keeper_webhook():
    data = request.json
    action = data.get("action")   # "created" / "updated" / "deleted"
    user_email = data.get("email")

    print(f"👉 Keeper event: {action} for {user_email}")

    # Create issue in Jira when a Keeper user is created
    if action == "created":
        url = f"{JIRA_URL}/rest/api/3/issue"
        auth = (JIRA_USER, JIRA_API_TOKEN)
        payload = {
            "fields": {
                "project": {"key": "POC"},  # replace with your Jira project key
                "summary": f"New Keeper user: {user_email}",
                "description": "User created in Keeper",
                "issuetype": {"name": "Task"}
            }
        }
        resp = requests.post(url, json=payload, auth=auth)
        print("👉 Jira response:", resp.status_code, resp.text)

    elif action == "deleted":
        # Example: find related Jira issue and close it
        print(f"⚠️ Deletion handling not implemented for {user_email}")

    return jsonify({"status": "ok"}), 200


@app.route("/")
def index():
    return "Flask app is running and integrated with Jira + Keeper!"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
