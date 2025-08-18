from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Jira Config (use your Jira Cloud domain + API token + email)
JIRA_URL = "https://metronlabs-team.atlassian.net"
JIRA_USER = "purushottam.kamble@metronlabs.com"
JIRA_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN")


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    issue_key = data.get("issueKey")

    # Log incoming webhook
    print(f"Received webhook for issue {issue_key}: {data}")

    # Call Jira back - Add a comment
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}/comment"
    auth = (JIRA_USER, JIRA_API_TOKEN)
    payload = {"body": "Hello World from Keeper POC!"}

    response = requests.post(url, json=payload, auth=auth)
    print("Jira response:", response.status_code, response.text)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
