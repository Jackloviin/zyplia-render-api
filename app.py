import os
import uuid
import base64
import subprocess
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Zyplia Video Cloud Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = "/tmp/zyplia_renders"
os.makedirs(TEMP_DIR, exist_ok=True)

class RenderRequest(BaseModel):
    video_url: str
    card_image_base64: str
    trim_start: float = 0.0
    trim_end: Optional[float] = None
    text_y_percent: float = 50.0
    scale: float = 1.0
    flip: bool = False
    orig_vol: float = 100.0

@app.get("/")
def health_check():
    return {"status": "online", "engine": "Zyplia Cloud Render ⚡"}

@app.post("/render")
def render_video(req: RenderRequest):
    job_id = str(uuid.uuid4())[:8]
    input_video_path = os.path.join(TEMP_DIR, f"{job_id}_input.mp4")
    card_img_path = os.path.join(TEMP_DIR, f"{job_id}_card.png")
    output_video_path = os.path.join(TEMP_DIR, f"{job_id}_output.mp4")

    try:
        resp = requests.get(req.video_url, stream=True, timeout=60)
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Erro ao baixar o vídeo base.")
        with open(input_video_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024*1024):
                f.write(chunk)

        card_data = req.card_image_base64
        if "base64," in card_data:
            card_data = card_data.split("base64,")[1]
        with open(card_img_path, "wb") as f:
            f.write(base64.b64decode(card_data))

        y_pos = f"(H-h)*{req.text_y_percent / 100.0}"
        
        video_filters = []
        if req.flip:
            video_filters.append("hflip")
        
        vf_base = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        if video_filters:
            vf_base += "," + ",".join(video_filters)
            
        filter_complex = f"[0:v]{vf_base}[bg]; [bg][1:v]overlay=(W-w)/2:{y_pos}:shortest=1[v]"

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(req.trim_start)
        ]

        if req.trim_end and req.trim_end > req.trim_start:
            cmd.extend(["-to", str(req.trim_end)])

        cmd.extend([
            "-i", input_video_path,
            "-loop", "1", "-i", card_img_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-r", "60",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            output_video_path
        ])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            error_msg = result.stderr.decode("utf-8", errors="ignore")
            raise HTTPException(status_code=500, detail=f"Erro FFmpeg: {error_msg[-300:]}")

        return FileResponse(
            output_video_path, 
            media_type="video/mp4", 
            filename="zyplia-reel.mp4"
        )

    finally:
        if os.path.exists(input_video_path): os.remove(input_video_path)
        if os.path.exists(card_img_path): os.remove(card_img_path)
