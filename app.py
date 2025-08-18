from flask import Flask, request, jsonify
import requests
import os

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
    data = request.json
    print("👉 Raw Jira Event:", data)

    # Simplified payload for Keeper
    keeper_event = {
        "source": "jira",
        "event_type": data.get("webhookEvent", "unknown"),
        "data": data  # forward the full payload so nothing is lost
    }

    print("📤 Would send to Keeper:", keeper_event)

    # (pretend sending to Keeper)
    try:
        response = requests.post(KEEPER_URL, json=keeper_event, timeout=5)
        print("✅ Sent to Keeper:", response.status_code)
    except Exception as e:
        print("⚠️ Could not send to Keeper:", e)

    return jsonify({"status": "ok"}), 200


### KEEPER → JIRA
@app.route("/keeper-events", methods=["POST"])
def keeper_webhook():
    data = request.json
    print("👉 Raw Keeper event:", data)

    event_type = data.get("event_type")
    user = data.get("user")

    headers = {"Content-Type": "application/json"}
    auth = (JIRA_USER, JIRA_API_TOKEN)

    if event_type == "user_created":
        payload = {
            "fields": {
                "project": {"key": "POC"},  # change project key
                "summary": f"New Keeper user created: {user}",
                "description": f"A new user {user} was created in Keeper.",
                "issuetype": {"name": "Task"}
            }
        }
        resp = requests.post(f"{JIRA_URL}/rest/api/3/issue", json=payload, auth=auth, headers=headers)
        print("👉 Jira create issue:", resp.status_code, resp.text)

    elif event_type == "user_deleted":
        # Example: create issue about deletion
        payload = {
            "fields": {
                "project": {"key": "POC"},
                "summary": f"Keeper user deleted: {user}",
                "description": f"User {user} was deleted in Keeper.",
                "issuetype": {"name": "Task"}
            }
        }
        resp = requests.post(f"{JIRA_URL}/rest/api/3/issue", json=payload, auth=auth, headers=headers)
        print("👉 Jira create deletion issue:", resp.status_code, resp.text)

    # Other events (update, vault shared, etc.) → add more elif blocks

    return jsonify({"status": "ok"}), 200


@app.route("/")
def index():
    return "Flask sync hub for Jira <-> Keeper!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
