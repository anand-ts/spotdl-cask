"""Spotify client wrapper for spotDL integration."""

from typing import Dict, Any, Optional

try:
    from spotdl.utils.spotify import SpotifyClient  # type: ignore
    from spotdl.types.song import Song  # type: ignore
    from spotdl.utils.config import get_config  # type: ignore
except ImportError as e:
    raise SystemExit("spotdl>=4 must be installed: pip install spotdl") from e


class SpotifyManager:
    """Manages Spotify client initialization and song metadata retrieval."""
    
    def __init__(self):
        self._ready = False
    
    def ensure_client(self) -> None:
        """Initialize Spotify client if not already done."""
        if self._ready:
            return
            
        try:
            # Load config from SpotDL's config file
            config = get_config()
            client_id = config.get("client_id", "")
            client_secret = config.get("client_secret", "")
            
            if not client_id or not client_secret:
                raise RuntimeError("SpotDL config file missing valid Spotify credentials")
            
            SpotifyClient.init(
                client_id=client_id,
                client_secret=client_secret,
                user_auth=config.get("user_auth", False),
                cache_path=config.get("cache_path"),
                no_cache=config.get("no_cache", False),
            )
            self._ready = True
            
        except Exception as e:
            # If client is already initialized, that's fine - we can use it
            if "already been initialized" in str(e):
                self._ready = True
                return
            raise RuntimeError(f"Failed to initialize Spotify client: {e}") from e
    
    def get_metadata(self, link: str) -> Dict[str, Any]:
        """
        Get song metadata from Spotify/YouTube link.
        
        Args:
            link: Spotify or YouTube URL
            
        Returns:
            Dictionary containing title, artist, album, and cover URL
        """
        self.ensure_client()
        
        try:
            song: Song = Song.from_url(link)  # type: ignore[arg-type]
            artists = [getattr(a, "name", a) for a in song.artists]
            
            return {
                "title": song.name,
                "artist": ", ".join(artists),
                "album": song.album_name or "",
                "cover": song.cover_url or "",
            }
        except Exception as e:
            print(f"Metadata error for {link}: {e}")
            return {
                "title": "(unknown)",
                "artist": "",
                "album": "",
                "cover": ""
            }


# Global instance
spotify_manager = SpotifyManager()
