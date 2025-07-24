import os
import base64
import tempfile
import requests
import json
from flask import Flask, request, jsonify
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
from pydub import AudioSegment
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
SERVICE_ACCOUNT_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64")
DEFAULT_VOICE_ID = "WffdYtALnWHwMOtLM7Hk"  # Your chosen free voice ID from ElevenLabs

def synthesize(voice_text, voice_id, api_key, output_path):
    import requests
    import os

    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "text": voice_text,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

    response = requests.post(tts_url, headers=headers, json=payload)

    if response.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(response.content)
        return output_path
    else:
        print(f"❌ Failed to synthesize audio: {response.status_code} - {response.text}")
        return None

# --- Google Drive Upload ---
def upload_to_drive(filename, filepath):
    creds_data = base64.b64decode(SERVICE_ACCOUNT_B64)
    creds_dict = json.loads(creds_data)
    creds = service_account.Credentials.from_service_account_info(creds_dict)
    service = build("drive", "v3", credentials=creds)

    file_metadata = {"name": filename, "mimeType": "video/mp4"}
    media = MediaFileUpload(filepath, mimetype="video/mp4", resumable=True)
    uploaded_file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()

    file_id = uploaded_file.get("id")
    service.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()
    return f"https://drive.google.com/uc?id={file_id}&export=download"

# --- Utility download ---
def download_file(url, filename):
    import requests
    response = requests.get(url)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            f.write(response.content)
        return filename
    else:
        raise Exception(f"Failed to download file from {url}")

# --- Main Endpoint ---
@app.route('/generate-video', methods=['POST'])
def generate_video():
    try:
        data = request.json
        image_url = data.get("image_url")
        background_url = data.get("background_url")
        clips = data.get("clips", [])

        if not clips:
            return jsonify({"error": "No clips provided"}), 400

        print(f"[INFO] Received {len(clips)} clip(s)")

        # Download image
        image_path = download_file(image_url, "image.jpg")
        background_path = download_file(background_url, "background.mp3")

        all_clips = []
        for index, clip in enumerate(clips):
            voice_text = clip.get("voiceText", "").strip()
            if not voice_text:
                print(f"[WARN] Skipping empty voiceText at index {index}")
                continue

            print(f"[INFO] Synthesizing clip {index}: {voice_text[:60]}...")
            try:
                audio_path = synthesize_voice(voice_text, index)
                if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
                    print(f"[ERROR] Audio generation failed or empty for clip {index}")
                    continue
                scene = create_scene(image_path, audio_path, index)
                all_clips.append(scene)
            except Exception as e:
                print(f"[ERROR] ElevenLabs synthesis failed at index {index}: {e}")
                continue

        if not all_clips:
            return jsonify({"error": "No valid clips (audio synthesis failed)"}), 400

        print(f"[INFO] Combining {len(all_clips)} clips into final video...")
        final_video = concatenate_videoclips(all_clips)
        final_video_path = "final_output.mp4"
        final_video.write_videofile(final_video_path, fps=24)

        drive_url = upload_to_drive(final_video_path)
        return jsonify({"video_url": drive_url})

    except Exception as e:
        print(f"[ERROR] Exception: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def health():
    return "✅ Video API running", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
