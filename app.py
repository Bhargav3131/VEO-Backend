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
    # ✅ Make ending frame optional
    image_urls = data.get("imageUrls", [])
    if not image_urls:
        return jsonify({
            "code": 400,
            "msg": "At least one image URL is required (start frame)"
        }), 400
    
    veo_request = {
        "prompt": data.get("prompt", ""),
        "imageUrls": image_urls,  # Can be [start] or [start, end]
        "model": data.get("model", "veo3_fast"),
        "generationType": data.get("generationType", "FIRST_AND_LAST_FRAMES_2_VIDEO"),
        "aspect_ratio": data.get("aspect_ratio", "9:16"),
        "enableTranslation": data.get("enableTranslation", True),
        "callBackUrl": data.get("callBackUrl", f"{request.host_url}/api/veo/callback")
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
    """Get status of a specific video task - Check if video URL is available"""
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
                    
                    # Check the CODE field (not status field!)
                    code = k_data.get("code", 200)
                    msg = k_data.get("msg", "")
                    error = k_data.get("error", "")
                    
                    # Handle different response codes
                    if code == 200:
                        # Video is ready - mark as completed
                        video_results[task_id]["status"] = "completed"
                        video_results[task_id]["completed_at"] = datetime.now().isoformat()
                        print(f"Video completed: {task_id}")
                    elif code == 400:
                        # Still processing
                        video_results[task_id]["status"] = "processing"
                        video_results[task_id]["msg"] = msg
                        print(f"Video still processing: {task_id} -> {msg}")
                    elif code == 501:
                        # Generation failed
                        video_results[task_id]["status"] = "failed"
                        video_results[task_id]["error"] = error or msg
                        print(f"Video failed: {task_id} -> {error or msg}")
                    else:
                        # Other error codes
                        video_results[task_id]["status"] = "failed"
                        video_results[task_id]["error"] = msg or error or f"Error code: {code}"
                        print(f"Video failed: {task_id} -> {msg or error or f'Error code: {code}'}")
                    
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
    """Handle Veo 3.1 API callback when video is ready (Sora-style approach)"""
    data = request.json
    
    print(f"=== CALLBACK RECEIVED ===")
    print(f"Full callback data: {json.dumps(data, indent=2)}")
    
    # Try to find task_id from callback (Sora-style)
    task_id = None
    
    # Method 1: Check for taskId field
    if 'taskId' in data:
        task_id = data.get('taskId')
    
    # Method 2: Check for actualTaskId field
    if not task_id and 'actualTaskId' in data:
        task_id = data.get('actualTaskId')
    
    # Method 3: Check for data.taskId field (Sora-style)
    if not task_id and 'data' in data:
        task_id = data.get('data', {}).get('taskId')
    
    # Method 4: Check for resultJson.resultUrls (Sora-style)
    if not task_id and 'data' in data:
        result_json = data.get('data', {}).get('resultJson', '{}')
        try:
            result_data = json.loads(result_json)
            urls = result_data.get('resultUrls', [])
            if urls:
                # Find task_id from mapping
                for actual_id, our_id in task_id_mapping.items():
                    if actual_id in str(data):
                        task_id = our_id
                        print(f"Found mapping: {actual_id} -> {task_id}")
                        break
        except:
            pass
    
    # If still not found, try to match with our mapping
    if not task_id:
        for actual_id, our_id in task_id_mapping.items():
            if actual_id in str(data):
                task_id = our_id
                print(f"Found mapping: {actual_id} -> {task_id}")
                break
    
    # Extract video URLs (Sora-style)
    video_url = None
    video_urls = []
    
    # Method 1: Direct videoUrl field
    if 'videoUrl' in data:
        video_url = data.get('videoUrl')
    
    # Method 2: resultUrls array (Sora-style)
    if not video_url and 'resultUrls' in data:
        video_urls = data.get('resultUrls', [])
        if video_urls:
            video_url = video_urls[0]
    
    # Method 3: resultJson.resultUrls (Sora-style)
    if not video_url and 'data' in data:
        result_json = data.get('data', {}).get('resultJson', '{}')
        try:
            result_data = json.loads(result_json)
            urls = result_data.get('resultUrls', [])
            if urls:
                video_url = urls[0]
        except:
            pass
    
    # Method 4: Check for state == 'success' (Sora-style)
    if not video_url and 'data' in data:
        state = data.get('data', {}).get('state')
        if state == 'success':
            result_json = data.get('data', {}).get('resultJson', '{}')
            try:
                result_data = json.loads(result_json)
                urls = result_data.get('resultUrls', [])
                if urls:
                    video_url = urls[0]
            except:
                pass
    
    print(f"Task ID: {task_id}")
    print(f"Video URL: {video_url}")
    print(f"Video URLs: {video_urls}")
    
    if task_id and task_id in video_results:
        if video_url:
            video_results[task_id]["status"] = "completed"
            video_results[task_id]["videoUrl"] = video_url
            video_results[task_id]["completed_at"] = datetime.now().isoformat()
            print(f"Video completed: {task_id} -> {video_url}")
        else:
            video_results[task_id]["status"] = "completed"
            video_results[task_id]["completed_at"] = datetime.now().isoformat()
            print(f"Video completed (URL pending): {task_id}")
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
        save_history_to_file(video_history)  # Save to file
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
