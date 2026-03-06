from flask import Flask, request, jsonify
import json
from flask_cors import CORS
from datetime import datetime
import os
import requests

app = Flask(__name__)
CORS(app)

# Store videos by task ID (instance-specific)
video_results = {}
video_history = []
HISTORY_FILE = 'video_history.json'

# Kie.ai API Configuration
KIE_API_KEY = "416127f06c4433f3aac9ea71c9e81ffc"
KIE_API_BASE = "https://api.kie.ai"

# Load history from file on startup
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try:
                return json.load(f)
            except:
                return []
    return []

# Save history to file
def save_history_to_file(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

video_history = load_history()

@app.route('/api/veo/generate', methods=['POST'])
def generate_video():
    """Create a new Veo 3.1 video generation task"""
    data = request.json
    
    # Generate unique task ID
    task_id = f"veo_task_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Store task info
    video_results[task_id] = {
        "status": "processing",
        "task_id": task_id,
        "created_at": datetime.now().isoformat()
    }
    
    # Prepare Veo 3.1 API request
    veo_request = {
        "prompt": data.get("prompt", ""),
        "imageUrls": data.get("imageUrls", []),
        "model": data.get("model", "veo3_fast"),
        "generationType": data.get("generationType", "FIRST_AND_LAST_FRAMES_2_VIDEO"),
        "aspect_ratio": data.get("aspect_ratio", "9:16"),
        "enableTranslation": data.get("enableTranslation", True),
        "callBackUrl": data.get("callBackUrl", f"{request.host_url}api/veo/callback")
    }
    
    try:
        # Call actual Veo 3.1 API
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
            # Store the actual task ID from Veo API
            actual_task_id = veo_response.get("data", {}).get("taskId", task_id)
            video_results[task_id]["actual_task_id"] = actual_task_id
            
            return jsonify({
                "code": 200,
                "msg": "success",
                "data": {
                    "taskId": task_id
                }
            }), 200
        else:
            video_results[task_id]["status"] = "failed"
            video_results[task_id]["error"] = veo_response.get("msg", "API Error")
            return jsonify({
                "code": response.status_code,
                "msg": veo_response.get("msg", "Failed to create task")
            }), response.status_code
            
    except Exception as e:
        video_results[task_id]["status"] = "failed"
        video_results[task_id]["error"] = str(e)
        return jsonify({
            "code": 500,
            "msg": f"Error: {str(e)}"
        }), 500

@app.route('/api/veo/status/<task_id>', methods=['GET'])
def get_video_status(task_id):
    """Get status of a specific video task"""
    if task_id in video_results:
        return jsonify(video_results[task_id]), 200
    return jsonify({"status": "not_found"}), 404

@app.route('/api/veo/callback', methods=['POST'])
def video_callback():
    """Handle Veo 3.1 API callback when video is ready"""
    data = request.json
    task_id = data.get('taskId')
    video_url = data.get('videoUrl')
    status = data.get('status', 'completed')
    
    if task_id and task_id in video_results:
        video_results[task_id]["status"] = status
        if video_url:
            video_results[task_id]["videoUrl"] = video_url
            video_results[task_id]["completed_at"] = datetime.now().isoformat()
            print(f"Video completed: {task_id} -> {video_url}")
        else:
            video_results[task_id]["error"] = data.get('error', 'Unknown error')
            print(f"Video failed: {task_id} -> {data.get('error', 'Unknown error')}")
    
    return jsonify({'status': 'ok'}), 200

@app.route('/api/saveHistory', methods=['POST'])
def save_history():
    """Save video to history"""
    data = request.json
    url = data.get('url')
    if url:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        video_history.insert(0, {"url": url, "timestamp": timestamp})
        save_history_to_file(video_history)
        print(f"Saved to history: {url}")
    return jsonify({'status': 'ok'}), 200

@app.route('/api/history', methods=['GET'])
def get_history():
    """Get all saved videos from history"""
    return jsonify({'history': video_history}), 200

@app.route('/api/reset', methods=['POST'])
def reset_videos():
    """Reset video results (for new generation)"""
    global video_results
    video_results = {}
    print("Backend reset: video_results cleared")
    return jsonify({'status': 'reset'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
