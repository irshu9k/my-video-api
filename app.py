import os
import json
import base64
import requests
import tempfile

from flask import Flask, request, jsonify
from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    concatenate_videoclips,
    CompositeAudioClip
)
from pydub import AudioSegment
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Flask App
app = Flask(__name__)

# Load ENV Vars
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
SERVICE_ACCOUNT_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64")

# Save service account json
with open("service_account.json", "w") as f:
    f.write(base64.b64decode(SERVICE_ACCOUNT_B64).decode())

# Setup Google Drive Auth
creds = service_account.Credentials.from_service_account_file(
    "service_account.json",
    scopes=["https://www.googleapis.com/auth/drive"]
)
drive_service = build("drive", "v3", credentials=creds)

# Voice Generator (ElevenLabs)
def generate_voice(text, output_path):
    url = "https://api.elevenlabs.io/v1/text-to-speech/EXAVITQu4vr4xnSDxMaL"
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }
    body = {
        "text": text,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.7
        }
    }

    r = requests.post(url, headers=headers, json=body)
    if r.status_code != 200:
        print("ElevenLabs error:", r.text)
        return None

    with open(output_path, "wb") as f:
        f.write(r.content)
    return output_path

# Main API
@app.route("/generate-video", methods=["POST"])
def generate_video():
    try:
        data = request.get_json()

        image_url = data.get("image_url")
        background_url = data.get("background_url")
        clips = data.get("clips", [])

        if not image_url or not background_url or not clips:
            return jsonify({"error": "Missing fields"}), 400

        # Download shared image
        img_path = tempfile.mktemp(suffix=".jpg")
        with open(img_path, "wb") as f:
            f.write(requests.get(image_url).content)

        voice_clips = []
        scene_videos = []

        for i, clip in enumerate(clips):
            voice_text = clip.get("voiceText", "").strip()
            if not voice_text:
                continue

            voice_path = tempfile.mktemp(suffix=".mp3")
            if not generate_voice(voice_text, voice_path):
                continue

            audio = AudioSegment.from_file(voice_path)
            duration = audio.duration_seconds

            img_clip = (
                ImageClip(img_path)
                .set_duration(duration)
                .resize(height=720)
                .set_position("center")
                .zoom_in(1.05)
            )

            video = img_clip.set_audio(AudioFileClip(voice_path))
            scene_videos.append(video)

        if not scene_videos:
            return jsonify({"error": "No valid clips"}), 400

        final_video = concatenate_videoclips(scene_videos, method="compose")

        # Add background music
        bg_path = tempfile.mktemp(suffix=".mp3")
        with open(bg_path, "wb") as f:
            f.write(requests.get(background_url).content)

        final_duration = final_video.duration
        bg_audio = AudioFileClip(bg_path).subclip(0, final_duration)
        final_audio = CompositeAudioClip([final_video.audio, bg_audio.volumex(0.2)])
        final_video = final_video.set_audio(final_audio)

        # Save and Upload
        out_path = "final_video.mp4"
        final_video.write_videofile(out_path, fps=24)

        file_metadata = {"name": "final_video.mp4", "mimeType": "video/mp4"}
        media = MediaFileUpload(out_path, mimetype="video/mp4")
        uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()

        # Make file public
        file_id = uploaded.get("id")
        drive_service.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()
        file_url = f"https://drive.google.com/uc?id={file_id}"

        return jsonify({"video_url": file_url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
