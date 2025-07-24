import os
import json
import base64
import tempfile
import requests
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.VideoClip import ImageClip
from moviepy.audio.AudioClip import AudioFileClip, CompositeAudioClip
from pydub import AudioSegment
from PIL import Image
from io import BytesIO

app = Flask(__name__)

# Load and decode Google service account from base64
GOOGLE_CREDENTIALS_B64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_B64")
creds = json.loads(base64.b64decode(GOOGLE_CREDENTIALS_B64))
SCOPES = ['https://www.googleapis.com/auth/drive.file']
credentials = service_account.Credentials.from_service_account_info(creds, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

ELEVEN_API_KEY = os.environ.get("ELEVEN_API_KEY")
HEADERS = {
    "xi-api-key": ELEVEN_API_KEY,
    "Content-Type": "application/json"
}

def download_file(url, suffix):
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to download from {url}")
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.write(response.content)
    temp_file.close()
    return temp_file.name

def synthesize_voice(text, voice_id="WffdYtALnWHwMOtLM7Hk"):
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.8}
    }
    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers=HEADERS,
        json=payload
    )
    if response.status_code != 200:
        raise Exception("Voice generation failed")

    audio_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    with open(audio_path, 'wb') as f:
        f.write(response.content)
    return audio_path

def upload_to_drive(file_path, filename):
    file_metadata = {'name': filename}
    media = MediaFileUpload(file_path, mimetype='video/mp4')
    uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = uploaded_file['id']
    drive_service.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
    return f"https://drive.google.com/uc?id={file_id}"

def create_clip(image_path, audio_path, duration=5):
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration
    image_clip = ImageClip(image_path).resize((1280, 720)).set_duration(duration).set_audio(audio_clip)

    # Apply a zoom-in effect
    zoom_clip = image_clip.fx(lambda clip: clip.resize(lambda t: 1 + 0.03 * t))
    return zoom_clip

@app.route("/generate-video", methods=["POST"])
def generate_video():
    try:
        data = request.get_json()

        image_url = data.get("image_url")
        background_url = data.get("background_url")
        clips_data = data.get("clips", [])

        if not clips_data or not image_url or not background_url:
            return jsonify({"error": "Missing image_url, background_url or clips"}), 400

        image_path = download_file(image_url, ".jpg")
        bg_music_path = download_file(background_url, ".mp3")

        final_clips = []

        for i, clip in enumerate(clips_data):
            voice_text = clip.get("voiceText")
            if not voice_text:
                continue

            voice_path = synthesize_voice(voice_text)
            video_clip = create_clip(image_path, voice_path)
            final_clips.append(video_clip)

        if not final_clips:
            return jsonify({"error": "No valid clips generated"}), 400

        from moviepy.video.compositing.concatenate import concatenate_videoclips
        final_video = concatenate_videoclips(final_clips, method="compose")

        # Add background music
        final_audio = AudioSegment.from_file(bg_music_path)
        video_duration_ms = int(final_video.duration * 1000)
        bg_music = final_audio[:video_duration_ms].fade_in(2000).fade_out(2000)

        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
        bg_music.export(temp_audio, format="mp3")

        final_audio_clip = AudioFileClip(temp_audio)
        final_video = final_video.set_audio(final_audio_clip)

        output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
        final_video.write_videofile(output_path, fps=24, codec='libx264')

        drive_link = upload_to_drive(output_path, "final_video.mp4")
        return jsonify({"video_url": drive_link})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
