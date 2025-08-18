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
    data = request.json
    issue_key = data.get("issue", {}).get("key")
    triggered_by = data.get("user", {}).get("emailAddress")

    print("👉 Jira event for issue:", issue_key, "by:", triggered_by)

    # Avoid loops (don’t react to your own Jira automation account)
    if triggered_by == JIRA_USER:
        print("⏩ Skipping self-triggered Jira event")
        return jsonify({"status": "skipped"}), 200

    # Send event to Keeper
    keeper_payload = {
        "source": "jira",
        "issue_key": issue_key,
        "summary": data["issue"]["fields"]["summary"],
        "status": data["issue"]["fields"]["status"]["name"],
        "triggered_by": triggered_by
    }

    try:
        resp = requests.post(KEEPER_URL, json=keeper_payload)
        print("👉 Forwarded to Keeper:", resp.status_code, resp.text)
    except Exception as e:
        print("⚠️ Error sending to Keeper:", str(e))

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
