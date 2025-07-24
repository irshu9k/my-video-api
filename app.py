from flask import Flask, request, jsonify
from moviepy import VideoFileClip, ImageClip, AudioFileClip
from pydub import AudioSegment
from PIL import Image, ImageDraw, ImageFont
import whisper, requests, subprocess, os, uuid, numpy as np, json

# Google Drive API
import os, json, base64

# Google Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ✅ Google Drive Auth via service account (from env var)
b64_creds = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64")
if not b64_creds:
    raise RuntimeError("Missing GOOGLE_SERVICE_ACCOUNT_JSON_B64 environment variable")

service_json_str = base64.b64decode(b64_creds).decode("utf-8")
service_info = json.loads(service_json_str)

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(service_info, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

def upload_and_share(filepath):
    file_metadata = {'name': os.path.basename(filepath)}
    media = MediaFileUpload(filepath, resumable=True)
    uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = uploaded.get("id")
    drive_service.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()
    return f"https://drive.google.com/uc?id={file_id}"

def download_file(url, filename):
    r = requests.get(url, stream=True)
    if r.status_code == 200:
        with open(filename, "wb") as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
        return filename
    return None

# ✅ ElevenLabs TTS + FX
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
VOICE_ID = "WffdYtALnWHwMOtLM7Hk"

def process_voice_fx(mp3_path):
    wav = mp3_path.replace(".mp3", ".wav")
    fx = mp3_path.replace(".mp3", "_fx.wav")
    subprocess.run(["sox", mp3_path, wav])
    subprocess.run(["sox", wav, fx, "vol", "1.5", "bass", "+2", "pitch", "-80", "reverb", "2", "echo", "0.3", "0.4", "20", "0.9"])
    return fx

def slow_voice(wav, speed=0.94):
    slow = wav.replace(".wav", "_slow.wav")
    subprocess.run(["sox", wav, slow, "tempo", str(speed)])
    return slow

def generate_voice(text, index):
    mp3 = f"voice_{index}.mp3"
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
        headers={"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_multilingual_v2"}
    )
    if r.status_code == 200:
        with open(mp3, "wb") as f:
            f.write(r.content)
        fx = process_voice_fx(mp3)
        slow = slow_voice(fx)
        final = f"voice_{index}_final.mp3"
        subprocess.run(["sox", slow, final])
        return final
    return None

# ✅ Peak Detection
def detect_peaks(path, frame_ms=50, threshold_db=-25):
    audio = AudioSegment.from_file(path)
    return [i / 1000.0 for i in range(0, len(audio), frame_ms) if audio[i:i+frame_ms].dBFS > threshold_db]

# ✅ Blink
def add_blinks(base, peaks, dur=0.05, fade=0.025, op=0.5):
    blinks = [
        ColorClip(base.size, (0, 0, 0), duration=dur)
        .set_opacity(op)
        .crossfadein(fade)
        .crossfadeout(fade)
        .set_start(t)
        for t in peaks
    ]
    return CompositeVideoClip([base] + blinks)

# ✅ Sway
def apply_sway(video, max_angle=2, max_shift=15, period=6):
    def transform(get_frame, t):
        frame = get_frame(t)
        angle = max_angle * np.sin(2 * np.pi * t / period)
        y_shift = max_shift * np.sin(2 * np.pi * t / period + np.pi/2)
        return ImageClip(frame).rotate(angle, resample='bilinear', expand=False).set_position(("center", 360 + y_shift)).get_frame(0)
    return video.fl(transform)

# ✅ Whisper Subtitle Generator
def generate_whisper_subs(audio_path, video_path="scene.mp4"):
    model = whisper.load_model("small")
    result = model.transcribe(audio_path, word_timestamps=True, language="en")
    words = []
    for seg in result["segments"]:
        for w in seg["words"]:
            wtxt = w["word"].strip()
            if wtxt:
                words.append({"word": wtxt, "start": w["start"], "end": w["end"]})

    def fmt(t):
        cs = int(round(t * 100))
        return f"{cs//360000}:{(cs//6000)%60:02}:{(cs//100)%60:02}.{cs%100:02}"

    chunks, i = [], 0
    while i < len(words):
        line, chars = [], 0
        while i < len(words):
            w = words[i]
            wlen = len(w["word"])
            extra = 1 if line else 0
            if chars + wlen + extra > 12:
                break
            line.append(w)
            chars += wlen + extra
            i += 1
            if w["word"][-1] in ".!?":
                break
        if line:
            s, e = fmt(line[0]["start"]), fmt(line[-1]["end"])
            txt = " ".join(w["word"] for w in line)
            chunks.append((s, e, txt))

    ass = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n[V4+ Styles]\n"
    ass += "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
    ass += "Style: Default,LiberationMono-Italic,38,&H22FFFCF8,&H11FFFCF8,&H44000007,&H00000000,-1,1,0,0,100,100,0,0,1,2,1,5,0,0,60,1\n[Events]\n"
    ass += "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    for s, e, t in chunks:
        ass += f"Dialogue: 0,{s},{e},Default,,0,0,0,,{t}\n"

    with open("captions.ass", "w", encoding="utf-8") as f:
        f.write(ass)

    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vf",
                   "ass=captions.ass:fontsdir=/usr/share/fonts/truetype/liberation",
                   "-c:a", "copy", "output_with_subs.mp4"])

# ✅ Flask App
app = Flask(__name__)

@app.route("/generate-video", methods=["POST"])
def generate_video():
    data = request.get_json()
    image_url = data.get("image_url", "")
    background_url = data.get("background_url", "")
    clips = data.get("clips", [])

    if not image_url or not background_url or not clips:
        return jsonify({"error": "Missing inputs"}), 400

    if not download_file(image_url, "scene.png") or not download_file(background_url, "background.mp3"):
        return jsonify({"error": "Download failed"}), 400

    scenes, current_time = [], 0
    full_audio = AudioSegment.silent(duration=0)

    for i, clip in enumerate(clips):
        text = clip.get("voiceText", "")
        path = generate_voice(text, i)
        if not path:
            continue
        audio = AudioFileClip(path)
        img = ImageClip("scene.png").set_duration(audio.duration).resize(height=720).set_position("center")
        scene = img.set_audio(audio).set_start(current_time)
        scenes.append(scene)
        full_audio += AudioSegment.from_file(path)
        current_time += audio.duration

    if not scenes:
        return jsonify({"error": "No valid clips"}), 400

    base = concatenate_videoclips(scenes, method="compose")
    full_audio.export("combined_voice.mp3", format="mp3")

    blinked = add_blinks(base, detect_peaks("combined_voice.mp3"))
    swayed = apply_sway(blinked)

    duration = int(swayed.duration * 1000)
    music = AudioSegment.from_file("background.mp3")
    looped = (music * (duration // len(music) + 1))[:duration]
    final_audio = full_audio.overlay(looped - 5)
    final_audio.export("mixed_audio.mp3", format="mp3")

    swayed.set_audio(AudioFileClip("mixed_audio.mp3")).write_videofile("scene.mp4", fps=24)

    # ✅ Whisper captions
    generate_whisper_subs("combined_voice.mp3", "scene.mp4")
    out = f"video_{uuid.uuid4().hex[:6]}.mp4"
    os.rename("output_with_subs.mp4", out)
    return jsonify({"video_url": upload_and_share(out)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
