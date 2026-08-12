"""Z-AI + ComfyUI + Fish.Audio + OmniVoice + UploadPost provider tools.

Image generation:
- ComfyImage: local Stable Diffusion (preferred when available)
- ZaiImage: cloud image gen via z-ai CLI (fallback)

TTS:
- FishAudioTTS: premium voice cloning (preferred when API key set)
- OmniVoiceTTS: multi-voice with emotion control
- ZaiTTS: cloud TTS via z-ai CLI (fallback)
- PiperTTS: offline local TTS (last resort, in tools/audio/)

Video:
- ZaiVideo: cloud video gen via z-ai CLI

Publishing:
- UploadPostTool: publish to 22+ social networks (YouTube, TikTok, Instagram, etc.)
"""

from tools.llm.comfy_image import ComfyImage
from tools.llm.fish_audio_tts import FishAudioTTS
from tools.llm.omnivoice_tts import OmniVoiceTTS
from tools.llm.uploadpost import UploadPostTool, SUPPORTED_PLATFORMS
from tools.llm.zai_image import ZaiImage
from tools.llm.zai_tts import ZaiTTS
from tools.llm.zai_video import ZaiVideo

__all__ = [
    "ComfyImage",
    "FishAudioTTS",
    "OmniVoiceTTS",
    "UploadPostTool",
    "SUPPORTED_PLATFORMS",
    "ZaiImage",
    "ZaiTTS",
    "ZaiVideo",
]
