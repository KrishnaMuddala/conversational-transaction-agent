"""
Configuration for the DBS DCTA backend on Tencent Cloud.
All secrets are read from environment variables.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # FastAPI
    APP_NAME: str = "DBS Direct Conversational Transaction Agent"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")

    # Tencent Cloud credentials
    TENCENT_SECRET_ID: str = os.getenv("TENCENT_SECRET_ID", "")
    TENCENT_SECRET_KEY: str = os.getenv("TENCENT_SECRET_KEY", "")
    TENCENT_REGION: str = os.getenv("TENCENT_REGION", "ap-singapore")

    # Parser — Tencent Cloud Agent Development Platform (ADP)
    # The model and base system prompt are configured on the published ADP
    # application in the console, not per request.
    #
    # Host and request schema must agree. Four combinations exist; only the two
    # matched pairs authenticate:
    #   international console  (adp.tencentcloud.com)  ->  wss.lke.tencentcloud.com
    #       v2  /adp/v2/chat         AppKey / ConversationId / Contents
    #       v1  /v1/qbot/chat/sse    bot_app_key / session_id / content
    #   China console        (adp.cloud.tencent.com)  ->  wss.lke.cloud.tencent.com
    #       v2  /adp/v2/chat         AppKey / ConversationId / Contents
    #       v1  /v1/qbot/chat/sse    bot_app_key / session_id / content
    #
    # The default is the international v2 endpoint, per the AI CAN DO IT
    # Hackathon Guide. The v1 path is labelled "Previous Version" upstream and
    # is documented to sunset 2026-12-31, so it is a fallback only.
    #
    # A key sent to the wrong host, or with the wrong field names for the path,
    # returns HTTP 200 with an SSE error event carrying code 4505004 "APPKEY is
    # invalid" — identical to a genuinely bad key, so status codes never reveal
    # the cause. parser.py selects the wire format from this URL.
    USE_MOCK_PARSER: bool = os.getenv("USE_MOCK_PARSER", "true").lower() in ("1", "true", "yes")
    ADP_APP_KEY: str = os.getenv("ADP_APP_KEY", "")
    ADP_BASE_URL: str = os.getenv(
        "ADP_BASE_URL", "https://wss.lke.tencentcloud.com/adp/v2/chat"
    )
    ADP_VISITOR_ID: str = os.getenv("ADP_VISITOR_ID", "dcta-parser")
    ADP_TIMEOUT_SECONDS: int = int(os.getenv("ADP_TIMEOUT_SECONDS", "60"))

    # TRTC — Tencent Real-Time Communication (Conversational AI)
    # SDKAppID + SDKSecretKey from TRTC Console > App Management.
    # Used for: UserSig generation (HMAC-SHA256), TRTC ASR v3 API auth.
    # The ASR v3 endpoint is asr-intl.cloud-rtc.com (international) or
    # asr.cloud-rtc.com (China).  Use the international site for ap-singapore.
    TRTC_SDK_APP_ID: int = int(os.getenv("TRTC_SDK_APP_ID", "0"))
    TRTC_SDK_SECRET_KEY: str = os.getenv("TRTC_SDK_SECRET_KEY", "")
    TRTC_ASR_ENDPOINT: str = os.getenv(
        "TRTC_ASR_ENDPOINT", "https://asr-intl.cloud-rtc.com/v3/transcribe"
    )

    # ASR (legacy Tencent ASR — blocked: FailedOperation.UserNotRegistered)
    ASR_ENGINE: str = os.getenv("ASR_ENGINE", "16k_en")  # 16k_en for Singapore English

    # TTS — Tencent Cloud TextToVoice
    # VoiceType 101001 = Zhiyu (female, English-capable, good for SG banking).
    # Full list: https://cloud.tencent.com/document/product/1073/92668
    # PrimaryLanguage 2 = English (primary), supports Chinese-English mix.
    TTS_VOICE_TYPE: int = int(os.getenv("TTS_VOICE_TYPE", "101001"))
    TTS_PRIMARY_LANGUAGE: int = int(os.getenv("TTS_PRIMARY_LANGUAGE", "2"))  # 1=Chinese, 2=English
    TTS_VOLUME: float = float(os.getenv("TTS_VOLUME", "0"))  # [-10, 10], 0 = normal
    TTS_SPEED: float = float(os.getenv("TTS_SPEED", "0"))  # [-2, 6], 0 = 1.0x

    # Crypto / KMS
    KMS_KEY_ID: str = os.getenv("KMS_KEY_ID", "")
    KMS_KEY_ALGORITHM: str = os.getenv("KMS_KEY_ALGORITHM", "RSA_PKCS1_SHA_256")
    # If KMS_KEY_ID is provided, signatures are verified via Tencent KMS
    # using VerifyByAsymmetricKey (algorithm defaults to RSA_PKCS1_SHA_256).
    # Otherwise a local PEM public key can be used for dev/testing.
    LOCAL_PUBLIC_KEY_PEM: str = os.getenv("LOCAL_PUBLIC_KEY_PEM", "")

    # Database (TDSQL-C / PostgreSQL)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/dbs_dcta"
    )

    # COS
    COS_SECRET_ID: str = os.getenv("COS_SECRET_ID", "") or os.getenv("TENCENT_SECRET_ID", "")
    COS_SECRET_KEY: str = os.getenv("COS_SECRET_KEY", "") or os.getenv("TENCENT_SECRET_KEY", "")
    COS_REGION: str = os.getenv("COS_REGION", "ap-singapore")
    COS_BUCKET: str = os.getenv("COS_BUCKET", "")

    # DBS Payment API
    DBS_PAYMENT_API_URL: str = os.getenv(
        "DBS_PAYMENT_API_URL",
        "https://mock-dbs-payment.example.com"
    )
    DBS_PAYMENT_API_KEY: str = os.getenv("DBS_PAYMENT_API_KEY", "")

    # Risk thresholds
    HIGH_VALUE_THRESHOLD: float = float(os.getenv("HIGH_VALUE_THRESHOLD", "50000"))
    SIGNATURE_TTL_SECONDS: int = int(os.getenv("SIGNATURE_TTL_SECONDS", "60"))


@lru_cache()
def get_settings() -> Settings:
    return Settings()
