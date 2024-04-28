from flask import Flask, jsonify
import cv2
from collections import deque
import threading
import base64
import requests
import os
from datetime import datetime

# Create a Flask application
app = Flask(__name__)



BUFFER_MAX_FRAMES = int(os.environ['BUFFER_MAX_FRAMES'])
EXTRACTED_FRAMES_COUNT = int(os.environ['EXTRACTED_FRAMES_COUNT'])
OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
VIDEO_SOURCE_1 = os.environ['VIDEO_SOURCE_1']
VIDEO_SOURCE_2 = os.environ['VIDEO_SOURCE_2']


# Initialize a deque as a circular buffer to hold the frames
frame_buffer_1 = deque(maxlen=BUFFER_MAX_FRAMES)
frame_buffer_2 = deque(maxlen=BUFFER_MAX_FRAMES)

def capture_frames_1():
    """ Function to capture frames from the video source and store them in a buffer """
    cap = cv2.VideoCapture(VIDEO_SOURCE_1)
    while True:
        ret, frame = cap.read()
        if ret:
            frame_buffer_1.append(frame)
        else:
            print("Failed to grab frame")
            break
    cap.release()

def capture_frames_2():
    """ Function to capture frames from the video source and store them in a buffer """
    cap = cv2.VideoCapture(VIDEO_SOURCE_2)
    while True:
        ret, frame = cap.read()
        if ret:
            frame_buffer_2.append(frame)
        else:
            print("Failed to grab frame")
            break
    cap.release()

def start_capture():
    """ Starts the frame capture in a separate thread """
    thread_1 = threading.Thread(target=capture_frames_1)
    thread_1.daemon = True  # This ensures the thread will close when the main program exits
    thread_1.start()
    thread_2 = threading.Thread(target=capture_frames_2)
    thread_2.daemon = True  # This ensures the thread will close when the main program exits
    thread_2.start()

@app.route('/latest_frame', methods=['GET'])
def latest_frame():
    images_html = []
    
    
    # Extract frames
    step_1 = max(1, len(frame_buffer_1) // EXTRACTED_FRAMES_COUNT)
    selected_frames = [frame_buffer_1[i] for i in range(0, len(frame_buffer_1), step_1)]
    step_2 = max(1, len(frame_buffer_2) // EXTRACTED_FRAMES_COUNT)
    selected_frames += [frame_buffer_2[i] for i in range(0, len(frame_buffer_2), step_2)]
    for frame in selected_frames:  # Get the last 10 frames
        _, buffer = cv2.imencode('.jpg', frame)
        encoded_image = base64.b64encode(buffer).decode('utf-8')
        images_html.append(f'<img src="data:image/jpeg;base64,{encoded_image}" style="width:50%; height:auto;">')

    # HTML template to display images in a grid layout with two columns
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <title>Last 10 Frames</title>
    <style>
        body, html {{
            margin: 0;
            padding: 0;
            height: 100%;
            width: 100%;
        }}
        .grid {{
            display: flex;
            flex-wrap: wrap;
            height: 100%;
        }}
        .grid img {{
            flex: 1 1 50%;  /* Flex grow, flex shrink, and basis set to fill half the width */
            object-fit: cover; /* Cover ensures the image covers the allotted space without distorting aspect ratio */
            min-height: 50vh;  /* Minimum height for each image */
        }}
    </style>
    </head>
    <body>
        <div class="grid">
            {''.join(images_html)}
        </div>
    </body>
    </html>
    """
    return html

def analyze_images(images):
    content = [
            {
            "type": "text",
            "text": """
            Objective: You are tasked with analyzing a series of 8 CCTV images to detect any suspicious activities. These images are split between two camera views: 4 images from a high-angle camera and 4 images focusing on the driveway, which has motion detection enabled. Note the time of day, which will be indicated in the prompt, as it's critical for assessing the context of the activities.
            Instructions:
            Review each image carefully. Look for suspicious looking individuals or vehicles entering the driveway, unusual behavior, signs of forced entry, or any other elements that seem out of the ordinary given the time of day.
            Time of Day: %s
            
            Response Formatting:
            If no suspicious activity is detected across all images, state: "No suspicious activity detected. Followed by what could of triggured the event"
            If suspicious activity is observed in any of the images, respond with the phrase: "RAISEDTHEALARM." Immediately follow this keyword with a brief description of what specifically triggered the alarm, such as "person detected at night" or "unidentified vehicle entering during early hours."
            Note: Do not mention the keyword "RAISEDTHEALARM" unless you are reporting detected suspicious activity.""" % datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            }
        ]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for idx, frame in enumerate(images):
        
        directory = f"./images/{timestamp}"
        os.makedirs(directory, exist_ok=True)
        image_path = f"{directory}/image_{idx+1}.jpg"
        # Save the frame to filesystem
        cv2.imwrite(image_path, frame)

        # Encode the image to base64 to send it via API
        _, buffer = cv2.imencode('.jpg', frame)
        encoded_image = base64.b64encode(buffer).decode('utf-8')
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}
        })

    for frame in images:
        _, buffer = cv2.imencode('.jpg', frame)
        encoded_image = base64.b64encode(buffer).decode('utf-8')
        headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{encoded_image}"
                }
                })
        payload = {
        "model": "gpt-4-turbo",
        "messages": [
            {
            "role": "user",
            "content": content
            }
        ],
        "max_tokens": 300
        }
    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    print(response.json())
    return(response.json())


@app.route('/analyse', methods=['GET'])
def analyze_video():
    step_1 = max(1, len(frame_buffer_1) // EXTRACTED_FRAMES_COUNT)
    selected_frames = [frame_buffer_1[i] for i in range(0, len(frame_buffer_1), step_1)]
    step_2 = max(1, len(frame_buffer_2) // EXTRACTED_FRAMES_COUNT)
    selected_frames += [frame_buffer_2[i] for i in range(0, len(frame_buffer_2), step_2)]
    # Send images for analysis
    if selected_frames:
        result = analyze_images(selected_frames)
    else:
        result = {"error": "No valid images to analyze"}
    return jsonify(result.get("choices")[0].get("message").get("content"))

if __name__ == '__main__':
    start_capture()  # Start capturing video frames when the application starts
    app.run(host="0.0.0.0", debug=True, use_reloader=False)  # Disable reloader if not developing
