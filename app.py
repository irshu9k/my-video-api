import os
import base64
import tempfile
import requests
from flask import Flask, request, jsonify
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
from pydub import AudioSegment
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
SERVICE_ACCOUNT_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64")

# --- Voice synthesis ---
def synthesize_voice(text, voice_id="WffdYtALnWHwMOtLM7Hk"):
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.8}
    }
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.content
    else:
        print(f"❌ ElevenLabs failed: {response.text}")
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
    # Make public
    service.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()
    return f"https://drive.google.com/uc?id={file_id}&export=download"

# --- Utility download ---
def download_file(url):
    response = requests.get(url)
    if response.status_code != 200:
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(response.content)
    tmp.close()
    return tmp.name

# --- Main Endpoint ---
@app.route("/generate-video", methods=["POST"])
def generate_video():
    data = request.get_json()
    image_url = data.get("image_url")
    music_url = data.get("background_url")
    clips = data.get("clips", [])

    if not image_url or not music_url or not clips:
        return jsonify({"error": "Missing required fields"}), 400

    # Download assets
    image_path = download_file(image_url)
    music_path = download_file(music_url)

    if not image_path or not music_path:
        return jsonify({"error": "Failed to download image or music"}), 400

    video_clips = []
    full_audio = AudioSegment.empty()

    for idx, clip in enumerate(clips):
        text = clip.get("voiceText", "").strip()
        if not text:
            continue
        audio_bytes = synthesize_voice(text)
        if not audio_bytes:
            continue
        audio_path = f"/tmp/audio_{idx}.mp3"
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

        # Add to full_audio
        full_audio += AudioSegment.from_file(audio_path)

        # Calculate duration for image
        segment = AudioSegment.from_file(audio_path)
        duration = segment.duration_seconds

        img_clip = ImageClip(image_path).set_duration(duration).resize(height=720).set_position("center").fadein(0.5).fadeout(0.5)
        img_clip = img_clip.set_audio(AudioFileClip(audio_path))
        video_clips.append(img_clip)

    if not video_clips:
        return jsonify({"error": "No valid clips"}), 400

    final_video = concatenate_videoclips(video_clips)

    # Add background music
    bg_music = AudioSegment.from_file(music_path)
    bg_music = bg_music - 10  # lower volume
    bg_music = bg_music[:len(full_audio)]  # trim to duration
    final_mix = full_audio.overlay(bg_music)

    final_audio_path = "/tmp/final_audio.mp3"
    final_mix.export(final_audio_path, format="mp3")
    final_video = final_video.set_audio(AudioFileClip(final_audio_path))

    output_path = "/tmp/final_output.mp4"
    final_video.write_videofile(output_path, fps=24)

    drive_url = upload_to_drive("final_video.mp4", output_path)
    return jsonify({"video_url": drive_url})


@app.route("/", methods=["GET"])
def health():
    return "✅ Video API running", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
