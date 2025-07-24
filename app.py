import os
import json
import base64
import tempfile
import requests
from flask import Flask, request, jsonify
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip
from pydub import AudioSegment
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

# Load ElevenLabs API Key from env
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")

# Setup Google Drive credentials
b64_creds = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64")
creds_json = base64.b64decode(b64_creds).decode()
creds = service_account.Credentials.from_service_account_info(json.loads(creds_json))
drive_service = build('drive', 'v3', credentials=creds)

# Helper: download file from URL
def download_file(url):
    response = requests.get(url)
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file.write(response.content)
    temp_file.close()
    return temp_file.name

# Helper: generate voice clip using ElevenLabs
def generate_voice(text, index):
    url = "https://api.elevenlabs.io/v1/text-to-speech/WffdYtALnWHwMOtLM7Hk/stream"
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8
        }
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        raise Exception("Voice generation failed")

    path = f"voice_{index}.mp3"
    with open(path, 'wb') as f:
        f.write(response.content)
    return path

# Helper: upload video to Google Drive
def upload_to_drive(filepath):
    file_metadata = {
        "name": os.path.basename(filepath),
        "mimeType": "video/mp4"
    }
    media = MediaFileUpload(filepath, mimetype='video/mp4')
    uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = uploaded_file.get("id")

    # Make it public
    drive_service.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()
    return f"https://drive.google.com/uc?id={file_id}"

# Zoom-in effect
def create_zoom_clip(image_path, audio_path, duration):
    clip = ImageClip(image_path, duration=duration).resize((1280, 720))
    clip = clip.fx(lambda c: c.zoom(1.05))
    audio = AudioFileClip(audio_path)
    return clip.set_audio(audio)

@app.route("/generate-video", methods=["POST"])
def generate_video():
    data = request.get_json()
    clips_data = data.get("clips", [])
    image_url = data.get("image_url")
    background_url = data.get("background_url")

    if not clips_data or not image_url:
        return jsonify({"error": "No valid clips or image_url"}), 400

    try:
        image_path = download_file(image_url)
        voice_clips = []
        video_clips = []

        for idx, clip in enumerate(clips_data):
            voice_text = clip.get("voiceText")
            if not voice_text:
                continue
            voice_path = generate_voice(voice_text, idx)
            audio = AudioSegment.from_file(voice_path)
            duration = max(audio.duration_seconds, 2.0)  # fallback minimum

            video_clip = create_zoom_clip(image_path, voice_path, duration)
            video_clips.append(video_clip)

        final_video = concatenate_videoclips(video_clips, method="compose")
        final_audio = final_video.audio

        if background_url:
            music_path = download_file(background_url)
            music = AudioSegment.from_file(music_path)
            music = music - 20  # lower volume
            temp_music = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
            music.export(temp_music, format="mp3")

            bg_music_clip = AudioFileClip(temp_music).subclip(0, final_video.duration)
            mixed_audio = CompositeAudioClip([final_audio, bg_music_clip])
            final_video = final_video.set_audio(mixed_audio)

        output_path = "final_video.mp4"
        final_video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")

        video_url = upload_to_drive(output_path)
        return jsonify({"video_url": video_url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
