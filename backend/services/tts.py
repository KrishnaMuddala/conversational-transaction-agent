"""
Tencent Cloud TTS integration.
Synthesises text into audio for voice-based clarification prompts
and confirmation overlays in the conversational banking experience.

Uses Tencent Cloud TTS TextToVoice (synchronous, short-form).
For long-form synthesis (>150 Chinese chars / >500 English letters),
switch to CreateTtsTask + DescribeTtsTaskStatus (async polling).
"""

from __future__ import annotations

import base64
import uuid

from config import get_settings


def synthesize_speech(text: str) -> dict:
    """
    Convert text to speech via Tencent Cloud TTS TextToVoice.

    Returns:
        {"audio": <base64-encoded mp3>, "format": "mp3", "text": <original text>}
    """
    if not text or not text.strip():
        raise ValueError("TTS input text is empty.")

    try:
        from tencentcloud.tts.v20190823 import tts_client, models
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
    except ImportError as e:
        raise RuntimeError(f"Tencent TTS SDK not installed: {e}")

    settings = get_settings()
    cred = credential.Credential(settings.TENCENT_SECRET_ID, settings.TENCENT_SECRET_KEY)
    http_profile = HttpProfile(endpoint="tts.tencentcloudapi.com")
    client_profile = ClientProfile(httpProfile=http_profile)
    client = tts_client.TtsClient(cred, settings.TENCENT_REGION, client_profile)

    req = models.TextToVoiceRequest()
    req.Text = text
    req.SessionId = uuid.uuid4().hex
    req.Volume = settings.TTS_VOLUME
    req.Speed = settings.TTS_SPEED
    req.ModelType = 1  # default model
    req.VoiceType = settings.TTS_VOICE_TYPE
    req.PrimaryLanguage = settings.TTS_PRIMARY_LANGUAGE
    req.SampleRate = 16000
    req.Codec = "mp3"

    try:
        resp = client.TextToVoice(req)
        # TextToVoice returns base64-encoded audio in resp.Audio
        audio_b64 = resp.Audio
        return {
            "audio": audio_b64,
            "format": "mp3",
            "text": text,
        }
    except TencentCloudSDKException as e:
        raise RuntimeError(f"Tencent TTS error: {e}")
