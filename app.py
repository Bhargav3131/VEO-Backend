from flask import Flask, request, jsonify
import json
from flask_cors import CORS
from datetime import datetime
import os
import requests
import uuid

app = Flask(__name__)
CORS(app)

# Store videos by task ID
video_results = {}

# Map our task_id to actual_task_id from Kie.ai
task_id_mapping = {}

video_history = []
HISTORY_FILE = 'video_history.json'

# Kie.ai API Configuration
KIE_API_KEY = "YOUR_KIE_API_KEY"
KIE_API_BASE = "https://api.kie.ai"


# ---------------- HISTORY FUNCTIONS ----------------

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try:
                return json.load(f)
            except:
                return []
    return []


def save_history_to_file(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)


video_history = load_history()


# ---------------- GENERATE VIDEO ----------------

@app.route('/api/veo/generate', methods=['POST'])
def generate_video():

    data = request.json

    # safer unique task id
    task_id = f"veo_task_{uuid.uuid4().hex}"

    video_results[task_id] = {
        "status": "processing",
        "task_id": task_id,
        "created_at": datetime.now().isoformat(),
        "actual_task_id": None
    }

    image_urls = data.get("imageUrls", [])

    if not image_urls:
        return jsonify({
            "code": 400,
            "msg": "At least one image URL required"
        }), 400

    veo_request = {
        "prompt": data.get("prompt", ""),
        "imageUrls": image_urls,
        "model": data.get("model", "veo3_fast"),
        "generationType": data.get("generationType", "FIRST_AND_LAST_FRAMES_2_VIDEO"),
        "aspect_ratio": data.get("aspect_ratio", "9:16"),
        "enableTranslation": data.get("enableTranslation", True),
        "callBackUrl": data.get("callBackUrl")
    }

    try:

        response = requests.post(
            f"{KIE_API_BASE}/api/v1/veo/generate",
            headers={
                "Authorization": f"Bearer {KIE_API_KEY}",
                "Content-Type": "application/json"
            },
            json=veo_request
        )

        veo_response = response.json()

        if response.status_code == 200:

            actual_task_id = veo_response.get("data", {}).get("taskId")

            video_results[task_id]["actual_task_id"] = actual_task_id
            task_id_mapping[actual_task_id] = task_id

            print(f"Task created: {task_id} -> {actual_task_id}")

            return jsonify({
                "code": 200,
                "msg": "success",
                "data": {
                    "taskId": task_id
                }
            }), 200

        else:

            video_results[task_id]["status"] = "failed"
            video_results[task_id]["error"] = veo_response.get("msg")

            return jsonify({
                "code": response.status_code,
                "msg": veo_response.get("msg")
            }), response.status_code

    except Exception as e:

        video_results[task_id]["status"] = "failed"
        video_results[task_id]["error"] = str(e)

        return jsonify({
            "code": 500,
            "msg": str(e)
        }), 500


# ---------------- POLLING STATUS ----------------

@app.route('/api/veo/status/<task_id>', methods=['GET'])
def get_video_status(task_id):

    if task_id not in video_results:
        return jsonify({"status": "not_found"}), 404

    task_info = video_results[task_id]

    if task_info["status"] == "completed":
        return jsonify(task_info)

    if task_info["status"] == "failed":
        return jsonify(task_info)

    actual_task_id = task_info.get("actual_task_id")

    if not actual_task_id:
        return jsonify(task_info)

    try:

        k_response = requests.get(
            f"{KIE_API_BASE}/api/v1/veo/status/{actual_task_id}",
            headers={
                "Authorization": f"Bearer {KIE_API_KEY}",
                "Content-Type": "application/json"
            }
        )

        k_data = k_response.json()

        print("=== KIE STATUS RESPONSE ===")
        print(json.dumps(k_data, indent=2))

        code = k_data.get("code")

        if code == 200:

            result_json = k_data.get("data", {}).get("resultJson", "{}")

            video_url = None

            try:
                result_data = json.loads(result_json)
                urls = result_data.get("resultUrls", [])

                if urls:
                    video_url = urls[0]

            except:
                pass

            video_results[task_id]["status"] = "completed"
            video_results[task_id]["videoUrl"] = video_url
            video_results[task_id]["completed_at"] = datetime.now().isoformat()

            print(f"Video completed: {video_url}")

        elif code == 400:

            video_results[task_id]["status"] = "processing"

        elif code == 501:

            video_results[task_id]["status"] = "failed"
            video_results[task_id]["error"] = k_data.get("msg")

        return jsonify(video_results[task_id])

    except Exception as e:

        video_results[task_id]["status"] = "failed"
        video_results[task_id]["error"] = str(e)

        return jsonify(video_results[task_id])


# ---------------- CALLBACK ----------------

@app.route('/api/veo/callback', methods=['POST'])
def video_callback():

    data = request.json

    print("=== CALLBACK RECEIVED ===")
    print(json.dumps(data, indent=2))

    video_url = None
    task_id = None

    if "taskId" in data:
        task_id = data["taskId"]

    if not video_url and "data" in data:

        result_json = data.get("data", {}).get("resultJson", "{}")

        try:
            result_data = json.loads(result_json)
            urls = result_data.get("resultUrls", [])

            if urls:
                video_url = urls[0]

        except:
            pass

    if task_id and task_id in video_results:

        video_results[task_id]["status"] = "completed"
        video_results[task_id]["videoUrl"] = video_url
        video_results[task_id]["completed_at"] = datetime.now().isoformat()

        print("Video stored from callback")

    return jsonify({"status": "ok"})


# ---------------- HISTORY ----------------

@app.route('/api/saveHistory', methods=['POST'])
def save_history():

    data = request.json
    url = data.get("url")

    if url:

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        video_history.insert(0, {
            "url": url,
            "timestamp": timestamp
        })

        save_history_to_file(video_history)

    return jsonify({"status": "ok"})


@app.route('/api/history', methods=['GET'])
def get_history():

    return jsonify({
        "history": video_history
    })


# ---------------- RESET ----------------

@app.route('/api/reset', methods=['POST'])
def reset_videos():

    global video_results, task_id_mapping

    video_results = {}
    task_id_mapping = {}

    return jsonify({"status": "reset"})


# ---------------- RUN SERVER ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
