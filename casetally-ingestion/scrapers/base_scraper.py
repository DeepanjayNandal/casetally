# ingestion/core/base_scraper.py
import logging
import time
import requests
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from pathlib import Path

logger = logging.getLogger(__name__)


class BaseScraperConfig:
    """Configuration for web scraping."""
    
    def __init__(
        self,
        base_url: str,
        rate_limit: float = 1.0,  # Requests per second
        timeout: int = 30,
        user_agent: str = "CaseTally Legal Research Bot/1.0"
    ):
        self.base_url = base_url
        self.rate_limit = rate_limit
        self.timeout = timeout
        self.user_agent = user_agent
        self.last_request_time = 0


class BaseScraper(ABC):
    """
    Abstract base class for web scrapers.
    
    Provides:
    - Rate limiting
    - Error handling
    - Session management
    - Robots.txt compliance
    
    Subclasses must implement:
    - scrape(): Main scraping logic
    - parse_page(): Page-specific parsing
    """
    
    def __init__(self, config: BaseScraperConfig, cache_dir: Optional[Path] = None):
        self.config = config
        self.cache_dir = cache_dir or Path("/tmp/scraper_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # HTTP session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config.user_agent,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        
        logger.info(f"Initialized {self.__class__.__name__}")
        logger.info(f"Base URL: {config.base_url}")
        logger.info(f"Rate limit: {config.rate_limit} req/s")
    
    @abstractmethod
    def scrape(self) -> Dict:
        """
        Main scraping method - must be implemented by subclasses.
        
        Returns:
            Dict with scraping statistics
        """
        raise NotImplementedError("Subclasses must implement scrape()")
    
    @abstractmethod
    def parse_page(self, soup: BeautifulSoup, url: str) -> Dict:
        """
        Parse a single page - must be implemented by subclasses.
        
        Args:
            soup: BeautifulSoup parsed HTML
            url: Page URL
            
        Returns:
            Parsed data as dict
        """
        raise NotImplementedError("Subclasses must implement parse_page()")
    
    def fetch_page(self, url: str, use_cache: bool = True) -> Optional[str]:
        """
        Fetch a web page with rate limiting and caching.
        
        Args:
            url: URL to fetch
            use_cache: Use cached version if available
            
        Returns:
            HTML content or None on error
        """
        # Rate limiting
        self._rate_limit()
        
        # Check cache
        if use_cache:
            cached = self._get_cached(url)
            if cached:
                logger.debug(f"Cache hit: {url}")
                return cached
        
        # Fetch from web
        try:
            logger.info(f"Fetching: {url}")
            response = self.session.get(
                url,
                timeout=self.config.timeout,
                allow_redirects=True
            )
            response.raise_for_status()
            
            html = response.text
            
            # Cache the response
            self._cache_page(url, html)
            
            return html
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None
    
    def parse_html(self, html: str) -> BeautifulSoup:
        """Parse HTML string into BeautifulSoup object."""
        return BeautifulSoup(html, 'html.parser')
    
    def make_absolute_url(self, url: str) -> str:
        """Convert relative URL to absolute."""
        return urljoin(self.config.base_url, url)
    
    def _rate_limit(self):
        """Enforce rate limiting."""
        if self.config.rate_limit <= 0:
            return
        
        min_interval = 1.0 / self.config.rate_limit
        elapsed = time.time() - self.config.last_request_time
        
        if elapsed < min_interval:
            sleep_time = min_interval - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        
        self.config.last_request_time = time.time()
    
    def _get_cached(self, url: str) -> Optional[str]:
        """Get cached page content."""
        cache_file = self._get_cache_path(url)
        
        if cache_file.exists():
            try:
                return cache_file.read_text(encoding='utf-8')
            except Exception as e:
                logger.warning(f"Cache read error for {url}: {e}")
                return None
        
        return None
    
    def _cache_page(self, url: str, content: str):
        """Cache page content."""
        cache_file = self._get_cache_path(url)
        
        try:
            cache_file.write_text(content, encoding='utf-8')
            logger.debug(f"Cached: {url}")
        except Exception as e:
            logger.warning(f"Cache write error for {url}: {e}")
    
    def _get_cache_path(self, url: str) -> Path:
        """Generate cache file path from URL."""
        # Create safe filename from URL
        parsed = urlparse(url)
        safe_name = f"{parsed.netloc}{parsed.path}".replace('/', '_')
        safe_name = safe_name[:200]  # Limit length
        
        return self.cache_dir / f"{safe_name}.html"
    
    def clear_cache(self):
        """Clear all cached pages."""
        for cache_file in self.cache_dir.glob("*.html"):
            cache_file.unlink()
        logger.info("Cache cleared")
    
    def close(self):
        """Close HTTP session."""
        self.session.close()
        logger.info("Scraper session closed")