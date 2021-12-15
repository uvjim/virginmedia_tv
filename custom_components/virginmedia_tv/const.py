"""Constants and defaults"""

DOMAIN: str = "virginmedia_tv"

CONF_CACHE_CLEAR: str = "cache_clear"
CONF_CACHE_CONFIRM: str = "cache_confirm"
CONF_CHANNEL_FETCH_ENABLE: str = "channel_enable_fetch"
CONF_CHANNEL_INTERVAL: str = "channel_interval"
CONF_CHANNEL_LISTINGS_CACHE: str = "listings_cache"
CONF_CHANNEL_PWD: str = "channel_password"
CONF_CHANNEL_REGION: str = "channel_region"
CONF_CHANNEL_USE_MEDIA_BROWSER: str = "channel_use_media_browser"
CONF_CHANNEL_USER: str = "channel_user"
CONF_COMMAND_TIMEOUT: str = "command_timeout"
CONF_CONNECT_TIMEOUT: str = "connect_timeout"
CONF_CREDS_CLEAR: str = "creds_clear"
CONF_DEVICE_PLATFORM: str = "device_platform"
CONF_FLOW_NAME: str = "name"
CONF_HOST: str = "host"
CONF_IDLE_TIMEOUT: str = "idle_timeout"
CONF_PORT: str = "port"
CONF_SCAN_INTERVAL: str = "scan_interval"
CONF_SWVERSION: str = "swversion"
CONF_TITLE_PLACEHOLDERS: str = "title_placeholders"
CONF_ZNAME: str = "zname"

DEF_AUTH_FILE: str = "auth.json"
DEF_CACHE_CLEAR: bool = True
DEF_CACHE_CONFIRM: bool = False
DEF_CHANNEL_CACHE: str = ""
DEF_CHANNEL_FETCH_ENABLE: bool = False
DEF_CHANNEL_FILE: str = "channels.json"
DEF_CHANNEL_INTERVAL: int = 24
DEF_CHANNEL_INTERVAL_MIN: int = 1
DEF_CHANNEL_LISTINGS_CACHE: int = 48
DEF_CHANNEL_MAPPINGS_FILE: str = "tvc.json"
DEF_CHANNEL_REGION: str = "Eng-Lon"
DEF_CHANNEL_USE_MEDIA_BROWSER: bool = False
DEF_COMMAND_TIMEOUT: float = 1
DEF_CONNECT_TIMEOUT: float = 1
DEF_CREDS_CLEAR: bool = True
DEF_DEVICE_PLATFORM: str = "v6"
DEF_FLOW_NAME: str = "Virgin TiVo"
DEF_IDLE_TIMEOUT: float = 0
DEF_PORT: int = 31339
DEF_SCAN_INTERVAL: int = 5

KNOWN_PLATFORMS = {
    "360": "TV 360",
    "v6": "V6",
}
KNOWN_V6_REGIONS = {
    "Eng+Lon": "England inside London",
    "Eng-Lon": "England outside London",
    "NI": "Northern Ireland",
    "Scot": "Scotland",
    "Wales": "Wales",
}

SIGNAL_CLEAR_CACHE: str = f"{DOMAIN}_clear_cache"
SIGNAL_SWVERSION: str = f"{DOMAIN}_swversion"

STEP_CACHE_CONFIRM: str = "cache_confirm"
STEP_CACHE_MANAGE: str = "cache_manage"
STEP_DEVICE_PLATFORM: str = "device_platform"
STEP_OPTIONS: str = "options"
STEP_V6_REGION: str = "v6_region"
STEP_TIMEOUTS: str = "timeouts"
STEP_TIVO: str = "tivo"
STEP_VIRGIN_CREDS: str = "virgin_creds"

ZEROCONF_TYPE: str = "_tivo-remote._tcp.local."
