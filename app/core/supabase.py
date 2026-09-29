from typing import Optional
from supabase import create_client, Client
from app.config import settings

_supabase_client: Optional[Client] = None

def get_supabase() -> Client:
    """
    Returns an authenticated Supabase client using project URL and Service Role Key.
    This client has superuser access, bypasses RLS, and executes queries against the cloud database.
    """
    global _supabase_client
    if _supabase_client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured in environment.")
        _supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _supabase_client
