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
# Map our task_id to actual_task_id from Kie.ai
task_id_mapping = {}
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
        "created_at": datetime.now().isoformat(),
        "actual_task_id": None
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
            
            # Create mapping for callback lookup
            task_id_mapping[actual_task_id] = task_id
            
            print(f"Task created: {task_id} -> actual: {actual_task_id}")
            
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
    """Get status of a specific video task - Poll Kie.ai directly"""
    if task_id in video_results:
        task_info = video_results[task_id]
        
        # If already completed, return cached result
        if task_info.get("status") == "completed":
            return jsonify(task_info), 200
        
        # If failed, return cached result
        if task_info.get("status") == "failed":
            return jsonify(task_info), 200
        
        # If we have an actual_task_id, poll Kie.ai directly
        actual_task_id = task_info.get("actual_task_id")
        if actual_task_id:
            try:
                # Poll Kie.ai's API directly
                k_response = requests.get(
                    f"{KIE_API_BASE}/api/v1/veo/status/{actual_task_id}",
                    headers={
                        "Authorization": f"Bearer {KIE_API_KEY}",
                        "Content-Type": "application/json"
                    }
                )
                
                if k_response.status_code == 200:
                    k_data = k_response.json()
                    
                    # DEBUG: Log the full response
                    print(f"=== Kie.ai Response ===")
                    print(json.dumps(k_data, indent=2))
                    
                    # Update our cache with Kie.ai's response
                    if k_data.get("status") == "completed":
                        video_results[task_id]["status"] = "completed"
                        
                        # Try multiple possible field names for video URL
                        video_url = (
                            k_data.get("videoUrl") or
                            k_data.get("video_url") or
                            k_data.get("resultUrls", [None])[0] or
                            k_data.get("outputUrl") or
                            k_data.get("result", {}).get("videoUrl") or
                            k_data.get("data", {}).get("videoUrl")
                        )
                        
                        if video_url:
                            video_results[task_id]["videoUrl"] = video_url
                            video_results[task_id]["completed_at"] = datetime.now().isoformat()
                            print(f"Video completed: {task_id} -> {video_url}")
                        else:
                            video_results[task_id]["error"] = "Video URL not found in response"
                            print(f"Video completed but URL not found: {task_id}")
                    elif k_data.get("status") == "failed":
                        video_results[task_id]["status"] = "failed"
                        video_results[task_id]["error"] = k_data.get("error", k_data.get("msg", "Unknown error"))
                        print(f"Video failed: {task_id} -> {video_results[task_id]['error']}")
                    else:
                        video_results[task_id]["status"] = "processing"
                        print(f"Video still processing: {task_id}")
                    
                    return jsonify(video_results[task_id]), 200
                    
            except Exception as e:
                print(f"Error polling Kie.ai: {str(e)}")
                video_results[task_id]["status"] = "failed"
                video_results[task_id]["error"] = str(e)
                return jsonify(video_results[task_id]), 200
        
        # Return current status if no actual_task_id
        return jsonify(task_info), 200
    
    return jsonify({"status": "not_found"}), 404

@app.route('/api/veo/callback', methods=['POST'])
def video_callback():
    """Handle Veo 3.1 API callback when video is ready"""
    data = request.json
    
    print(f"=== CALLBACK RECEIVED ===")
    print(f"Full callback data: {json.dumps(data, indent=2)}")
    
    # Try to find task_id from callback
    task_id = data.get('taskId')
    
    # If not found, try actual_task_id
    if not task_id:
        task_id = data.get('actualTaskId')
    
    # If still not found, try to match with our mapping
    if not task_id:
        # Check if any actual_task_id matches
        for actual_id, our_id in task_id_mapping.items():
            if actual_id in str(data):
                task_id = our_id
                print(f"Found mapping: {actual_id} -> {task_id}")
                break
    
    video_url = data.get('videoUrl') or data.get('video_url') or data.get('resultUrls', [None])[0]
    status = data.get('status', 'completed')
    
    print(f"Task ID: {task_id}")
    print(f"Video URL: {video_url}")
    print(f"Status: {status}")
    
    if task_id and task_id in video_results:
        video_results[task_id]["status"] = status
        if video_url:
            video_results[task_id]["videoUrl"] = video_url
            video_results[task_id]["completed_at"] = datetime.now().isoformat()
            print(f"Video completed: {task_id} -> {video_url}")
        else:
            video_results[task_id]["error"] = data.get('error', 'Unknown error')
            print(f"Video failed: {task_id} -> {data.get('error', 'Unknown error')}")
    else:
        print(f"Task ID not found in video_results: {task_id}")
        print(f"Available task IDs: {list(video_results.keys())}")
    
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
    global video_results, task_id_mapping
    video_results = {}
    task_id_mapping = {}
    print("Backend reset: video_results cleared")
    return jsonify({'status': 'reset'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
