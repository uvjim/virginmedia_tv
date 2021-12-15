"""Constants and defaults"""

DEF_SCHEDULES_MAX: int = 250
DEF_URL_BASE: str = "https://web-api-prod-obo.horizon.tv/oesp/v4/GB/eng/web"
DEF_URL_CHANNELS: str = f"{DEF_URL_BASE}/channels"
DEF_URL_AUTH: str = f"{DEF_URL_BASE}/authorization"
DEF_URL_LOGIN: str = "https://id.virginmedia.com/rest/v40/session/start?protocol=oidc&rememberMe=true"
DEF_URL_SCHEDULES: str = f"{DEF_URL_BASE}/listings"
DEF_URL_SESSION: str = f"{DEF_URL_BASE}/session"
