from typing import Optional
import httpx
from supabase import create_client, Client, ClientOptions
from app.config import settings

_supabase_client: Optional[Client] = None

def get_supabase() -> Client:
    """
    Returns an authenticated Supabase client using project URL and Service Role Key.
    This client has superuser access, bypasses RLS, and executes queries against the cloud database.
    Configured with persistent HTTP/2 connection pooling and 120s keep-alive reuse.
    """
    global _supabase_client
    if _supabase_client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured in environment.")
        
        limits = httpx.Limits(
            max_keepalive_connections=50,
            max_connections=100,
            keepalive_expiry=120.0
        )
        custom_http = httpx.Client(
            http2=True,
            limits=limits,
            timeout=30.0
        )
        opts = ClientOptions(
            httpx_client=custom_http,
            postgrest_client_timeout=30.0
        )
        _supabase_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_ROLE_KEY,
            options=opts
        )
    return _supabase_client

