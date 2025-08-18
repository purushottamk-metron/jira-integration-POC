from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Jira Config
JIRA_URL = "https://metronlabs-team.atlassian.net"
JIRA_USER = "purushottam.kamble@metronlabs.com"
JIRA_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN")  # set in Render dashboard

@app.route("/webhooks", methods=["POST"])
def webhook():
    data = request.json
    print("👉 Incoming webhook:", data, flush=True)

    # Extract issue key correctly
    issue_key = None
    if "issue" in data:
        issue_key = data["issue"].get("key")

    if not issue_key:
        return jsonify({"error": "No issue key found"}), 400

    # Call Jira back - Add a comment
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}/comment"
    auth = (JIRA_USER, JIRA_API_TOKEN)
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Hello World from Keeper POC!"}
                    ]
                }
            ]
        }
    }

    response = requests.post(url, json=payload, auth=auth)
    print("👉 Jira response:", response.status_code, response.text, flush=True)

    return jsonify({"status": "ok"}), 200

@app.route("/")
def index():
    return "Flask app is running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
