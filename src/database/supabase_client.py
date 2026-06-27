import logging
from functools import lru_cache

from supabase import Client, create_client

from src.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
    client: Client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    logger.info("Supabase client initialized for %s", settings.supabase_url)
    return client
