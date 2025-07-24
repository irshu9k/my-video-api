# Video API for Render

This Flask-based API generates videos using image, ElevenLabs voice, and background music.

## 🐳 Docker Deployment on Render

1. Push to GitHub
2. Create Web Service on Render with:
   - Runtime: Docker
   - Secret file: service_account.json
   - Env Vars:
     - ELEVEN_API_KEY = your_key
     - GOOGLE_APPLICATION_CREDENTIALS = /app/service_account.json
3. POST JSON to `/generate-video` with:
   ```
   {
     "image_url": "https://...",
     "background_url": "https://...",
     "clips": [
       { "voiceText": "..." },
       ...
     ]
   }
   ```

