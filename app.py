import os
import io
import json
import base64
import requests
from flask import Flask, request, jsonify
from pydub import AudioSegment
from moviepy import VideoFileClip, ImageClip, AudioFileClip
from PIL import Image
from datetime import datetime
import tempfile
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

# Load ElevenLabs API key from env
ELEVEN_API_KEY = os.environ.get("ELEVEN_API_KEY")
VOICE_ID = "WffdYtALnWHwMOtLM7Hk"  # Replace with your ElevenLabs voice ID

# Setup Google Drive client
def setup_drive_service():
    json_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_B64")
    info = json.loads(base64.b64decode(json_b64))
    creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive.file"])
    return build("drive", "v3", credentials=creds)

drive_service = setup_drive_service()

def text_to_speech(text):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1"
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return AudioSegment.from_file(io.BytesIO(response.content), format="mp3")
    else:
        raise Exception("Voice generation failed")

def download_file(url):
    response = requests.get(url)
    if response.status_code == 200:
        return io.BytesIO(response.content)
    else:
        raise Exception(f"Failed to download: {url}")

def generate_video_from_clips(clips_data, image_url):
    scene_clips = []

    # Download image once
    image_data = download_file(image_url)
    image = Image.open(image_data).convert("RGB")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
        image.save(img_file.name)
        image_path = img_file.name

    for i, clip in enumerate(clips_data):
        voice_text = clip.get("voiceText")
        if not voice_text:
            continue

        voice_audio = text_to_speech(voice_text)
        audio_path = f"temp_audio_{i}.mp3"
        voice_audio.export(audio_path, format="mp3")

        duration = voice_audio.duration_seconds
        if duration < 1:
            duration = 2  # fallback minimum duration

        image_clip = ImageClip(image_path, duration=duration).resize((1280, 720)).fadein(0.5).fadeout(0.5)
        audio_clip = AudioFileClip(audio_path)
        image_clip = image_clip.set_audio(audio_clip)

        scene_clips.append(image_clip)

    if not scene_clips:
        raise Exception("No valid clips")

    return concatenate_videoclips(scene_clips, method="compose")

def overlay_background_music(video_path, music_path):
    final = AudioFileClip(video_path)
    bg_music = AudioSegment.from_file(music_path).fade_in(2000).fade_out(2000)
    bg_music = bg_music - 12  # reduce volume

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as bg_file:
        bg_music.export(bg_file.name, format="mp3")
        bg_path = bg_file.name

    music_clip = AudioFileClip(bg_path).set_duration(final.duration)
    final_video = CompositeAudioClip([final.audio, music_clip])
    output_path = "final_output.mp4"

    from moviepy.video.io.VideoFileClip import VideoFileClip
    video = VideoFileClip(video_path)
    video = video.set_audio(final_video)
    video.write_videofile(output_path, fps=24)

    return output_path

def upload_to_drive(file_path):
    file_name = f"video_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp4"
    media = MediaFileUpload(file_path, mimetype="video/mp4")
    file_metadata = {"name": file_name}
    uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()

    # Make file public
    drive_service.permissions().create(fileId=uploaded["id"], body={"role": "reader", "type": "anyone"}).execute()
    return f"https://drive.google.com/uc?id={uploaded['id']}"

@app.route("/generate-video", methods=["POST"])
def generate_video():
    try:
        data = request.get_json()
        image_url = data.get("image_url")
        background_url = data.get("background_url")
        clips = data.get("clips")

        if not clips or not image_url or not background_url:
            return jsonify({"error": "Missing parameters"}), 400

        print("⏬ Generating video scenes...")
        final_clip_path = "temp_scene.mp4"
        video = generate_video_from_clips(clips, image_url)
        video.write_videofile(final_clip_path, fps=24)

        print("🎵 Adding background music...")
        bg_music_data = download_file(background_url)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as music_file:
            music_file.write(bg_music_data.read())
            music_path = music_file.name

        final_video_path = overlay_background_music(final_clip_path, music_path)

        print("📤 Uploading to Google Drive...")
        drive_url = upload_to_drive(final_video_path)

        return jsonify({"video_url": drive_url})

    except Exception as e:
        print("❌ Error:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
