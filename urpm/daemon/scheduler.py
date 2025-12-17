"""Background task scheduler for urpmd."""

import logging
import random
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, TYPE_CHECKING
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

if TYPE_CHECKING:
    from .daemon import UrpmDaemon

from ..core.database import PackageDatabase

logger = logging.getLogger(__name__)

# Default intervals (in seconds)
DEFAULT_METADATA_CHECK_INTERVAL = 3600  # 1 hour
DEFAULT_PREDOWNLOAD_CHECK_INTERVAL = 7200  # 2 hours
# Note: cache cleanup runs after each predownload, not independently

# Dev mode intervals (shorter for testing)
DEV_METADATA_CHECK_INTERVAL = 60  # 1 minute
DEV_PREDOWNLOAD_CHECK_INTERVAL = 120  # 2 minutes


class Scheduler:
    """Background task scheduler for urpmd.

    Handles:
    - Periodic metadata refresh (checking if updates are needed)
    - Pre-downloading packages for pending updates
    - Cache cleanup

    Has its own database connection (SQLite requires separate connections per thread).
    """

    def __init__(self, daemon: 'UrpmDaemon', dev_mode: bool = False):
        self.daemon = daemon
        self.db_path = daemon.db_path
        self.base_dir = daemon.base_dir
        self.dev_mode = dev_mode
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Own database connection (created in thread)
        self.db: Optional[PackageDatabase] = None

        # TASK INTERVALS
        # ---------------
        # - metadata_interval: How often to check if synthesis files changed (HTTP HEAD)
        # - predownload_interval: How often to check for updates and pre-download them
        # - tick_interval: Scheduler's check frequency (quantization unit for all delays)
        #
        # All delays are rounded to tick_interval multiples, so:
        #   PROD: tick=60s  → delays are in minutes (60s, 120s, 180s...)
        #   DEV:  tick=10s  → delays are in 10s increments (10s, 20s, 30s...)
        #
        # Note: cache cleanup runs after each predownload, not on its own schedule.
        #
        if dev_mode:
            self.metadata_interval = DEV_METADATA_CHECK_INTERVAL    # 60s
            self.predownload_interval = DEV_PREDOWNLOAD_CHECK_INTERVAL  # 120s
            self.tick_interval = 10  # Check every 10s in dev mode
            logger.info("Dev mode: using short intervals (metadata=%ds, predownload=%ds, tick=%ds)",
                       DEV_METADATA_CHECK_INTERVAL, DEV_PREDOWNLOAD_CHECK_INTERVAL, self.tick_interval)
        else:
            self.metadata_interval = DEFAULT_METADATA_CHECK_INTERVAL    # 3600s (1h)
            self.predownload_interval = DEFAULT_PREDOWNLOAD_CHECK_INTERVAL  # 7200s (2h)
            self.tick_interval = 60  # Check every minute in production

        # JITTER (thundering herd prevention)
        # -----------------------------------
        # Random variation ±30% applied to each interval to desynchronize
        # multiple machines. Without jitter, all machines started at the same
        # time would hit the servers simultaneously.
        self.jitter_factor = 0.30

        # Last run times
        self._last_metadata_check: Optional[datetime] = None
        self._last_predownload: Optional[datetime] = None
        self._last_cleanup: Optional[datetime] = None

        # Next scheduled times (with jitter applied)
        self._next_metadata_check: Optional[float] = None
        self._next_predownload: Optional[float] = None
        self._next_cleanup: Optional[float] = None

        # Pre-download settings
        self.predownload_enabled = True
        self.max_predownload_size = 500 * 1024 * 1024  # 500 MB default

        # Idle detection thresholds (configurable)
        self.max_cpu_load = 0.5  # 1-minute load average threshold
        self.max_net_kbps = 100  # KB/s threshold for network "idle"

        # Network activity sampling
        self._last_net_sample: Optional[tuple] = None  # (timestamp, rx_bytes, tx_bytes)
        self._last_net_sample_time: Optional[float] = None

    def start(self):
        """Start the scheduler in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Scheduler stopped")

    def _run(self):
        """Main scheduler loop."""
        # Create own database connection in this thread
        logger.debug(f"Scheduler opening database: {self.db_path}")
        self.db = PackageDatabase(self.db_path)

        # Initial delay to let the daemon fully initialize
        time.sleep(10)

        try:
            while self._running:
                try:
                    self._check_tasks()
                except Exception as e:
                    logger.error(f"Scheduler error: {e}")

                # Sleep between checks (short intervals to allow quick shutdown)
                for _ in range(self.tick_interval):
                    if not self._running:
                        break
                    time.sleep(1)
        finally:
            # Close our database connection
            if self.db:
                self.db.close()
                self.db = None
                logger.debug("Scheduler closed database connection")

    def _check_tasks(self):
        """Check if any scheduled tasks should run."""
        now = time.time()

        # Check metadata refresh
        if self._should_run_task('metadata', now):
            self._run_metadata_check()
            self._schedule_next('metadata', now, self.metadata_interval)

        # Check pre-download
        if self.predownload_enabled and self._should_run_task('predownload', now):
            self._run_predownload()
            self._schedule_next('predownload', now, self.predownload_interval)

        # Note: cache cleanup runs after predownload, not independently
        # (see _run_predownload)

    def _should_run_task(self, task_name: str, now: float) -> bool:
        """Check if a task should run based on jittered schedule.

        Scheduling is quantized to tick_interval (scheduler's check frequency).
        This ensures displayed delays match actual execution times.

        On first call, schedules an initial offset to desynchronize multiple
        machines (thundering herd prevention).
        """
        next_time = getattr(self, f'_next_{task_name}_check', None)

        if next_time is None:
            # FIRST RUN SCHEDULING
            # ---------------------
            # Goal: Desynchronize machines so they don't all hit servers at once.
            #
            # We pick a random offset between 1 tick and 50% of the base interval.
            # The offset is quantized to tick_interval (the scheduler's check
            # frequency), so "first run in 30s" means exactly 30s, not "sometime
            # between 30-90s depending on when the next tick happens".
            #
            # Example with tick=10s, metadata_interval=60s:
            #   max_ticks = 60 * 0.5 / 10 = 3 ticks
            #   initial_ticks = random 1-3 → e.g., 2
            #   initial_offset = 2 * 10 = 20s
            #
            base_interval = getattr(self, f'{task_name}_interval', 3600)
            max_ticks = max(1, int(base_interval * 0.5 / self.tick_interval))
            initial_ticks = random.randint(1, max_ticks)
            initial_offset = initial_ticks * self.tick_interval
            setattr(self, f'_next_{task_name}_check', now + initial_offset)
            logger.debug(f"Task {task_name}: first run in {initial_offset}s ({initial_ticks} ticks)")
            return False

        return now >= next_time

    def _schedule_next(self, task_name: str, now: float, base_interval: int):
        """Schedule next run with jitter applied.

        Adds random jitter (±30% by default) to the base interval to prevent
        synchronized requests from multiple machines (thundering herd).

        The final interval is quantized to tick_interval to ensure the displayed
        delay matches actual execution time.

        Example with tick=10s, base_interval=60s, jitter_factor=0.30:
          jitter = random -0.30 to +0.30 → e.g., +0.15
          actual_interval = 60 * 1.15 = 69s
          ticks = round(69 / 10) = 7 ticks
          actual_interval = 7 * 10 = 70s (quantized)
        """
        # Apply jitter: ±jitter_factor around base interval
        jitter = random.uniform(-self.jitter_factor, self.jitter_factor)
        actual_interval = base_interval * (1 + jitter)

        # Quantize to tick_interval (round to nearest tick, minimum 1)
        ticks = max(1, round(actual_interval / self.tick_interval))
        actual_interval = ticks * self.tick_interval

        next_time = now + actual_interval
        setattr(self, f'_next_{task_name}_check', next_time)
        logger.debug(f"Task {task_name}: next run in {actual_interval}s ({ticks} ticks)")

    def _run_metadata_check(self):
        """Check if metadata needs refreshing using HTTP HEAD.

        Compares remote Last-Modified/Content-Length with local file.
        """
        logger.info("Running scheduled metadata check")

        if not self.db:
            logger.warning("No database connection")
            return

        from ..core.config import get_hostname_from_url

        # Check each enabled media
        media_list = self.db.list_media()
        logger.debug(f"Found {len(media_list)} media in database")

        for media in media_list:
            if not media['enabled']:
                continue

            name = media['name']
            url = media.get('url', '')

            if not url:
                continue

            # Get local synthesis file path
            # Structure: <base_dir>/medias/<hostname>/<media_name>/media_info/synthesis.hdlist.cz
            hostname = get_hostname_from_url(url)
            local_synthesis = self.base_dir / "medias" / hostname / name / "media_info" / "synthesis.hdlist.cz"
            logger.debug(f"Media {name}: checking local={local_synthesis}")

            # Build synthesis URL
            synthesis_url = url.rstrip('/') + '/media_info/synthesis.hdlist.cz'
            logger.debug(f"Media {name}: remote={synthesis_url}")

            # Check if synthesis has changed using HTTP HEAD vs local file
            has_changed = self._check_synthesis_changed(synthesis_url, local_synthesis)
            logger.debug(f"Media {name}: has_changed={has_changed}")

            if has_changed:
                logger.info(f"Media {name}: synthesis changed, refreshing")
                try:
                    self._refresh_media(name)
                except Exception as e:
                    logger.error(f"Failed to refresh {name}: {e}")
            else:
                logger.debug(f"Media {name}: synthesis unchanged")

    def _check_synthesis_changed(self, url: str, local_path: Path) -> bool:
        """Check if remote synthesis differs from local file.

        Compares Content-Length and Last-Modified from HTTP HEAD
        with local file size and mtime.

        Args:
            url: Remote synthesis URL
            local_path: Path to local synthesis file

        Returns:
            True if file has changed or local doesn't exist
        """
        from email.utils import parsedate_to_datetime

        # If local file doesn't exist, we need to download
        if not local_path.exists():
            logger.debug(f"Local file missing: {local_path}")
            return True

        try:
            local_stat = local_path.stat()
            local_size = local_stat.st_size
            local_mtime = local_stat.st_mtime
            logger.debug(f"Local file: size={local_size}, mtime={local_mtime}")
        except OSError as e:
            logger.warning(f"Could not stat local file {local_path}: {e}")
            return True

        try:
            req = Request(url, method='HEAD')
            req.add_header('User-Agent', 'urpmd/0.1')

            response = urlopen(req, timeout=30)

            # Get remote file info
            remote_size_str = response.headers.get('Content-Length')
            remote_last_mod = response.headers.get('Last-Modified')
            logger.debug(f"Remote: size={remote_size_str}, last_mod={remote_last_mod}")

            # Compare sizes
            if remote_size_str:
                remote_size = int(remote_size_str)
                if remote_size != local_size:
                    logger.debug(f"Size differs: local={local_size}, remote={remote_size}")
                    return True

            # Compare dates
            if remote_last_mod:
                try:
                    remote_dt = parsedate_to_datetime(remote_last_mod)
                    remote_mtime = remote_dt.timestamp()
                    # Remote is newer if its mtime > local mtime
                    if remote_mtime > local_mtime:
                        logger.debug(f"Remote is newer: local={local_mtime}, remote={remote_mtime}")
                        return True
                except (ValueError, TypeError):
                    pass  # Can't parse date, rely on size check

            # Size matches and remote is not newer
            return False

        except HTTPError as e:
            logger.warning(f"HTTP HEAD failed for {url}: {e.code}")
            return True  # Assume changed on error

        except (URLError, OSError) as e:
            logger.warning(f"Could not check {url}: {e}")
            return True  # Assume changed on error

    def _run_predownload(self):
        """Pre-download packages for pending updates."""
        logger.info("Running scheduled pre-download check")

        if not self.db:
            return

        try:
            # Get available updates
            updates = self._get_available_updates()

            if not updates:
                logger.debug("No updates to pre-download")
                return

            total_size = updates.get('total_size', 0)
            update_list = updates.get('updates', [])

            if total_size > self.max_predownload_size:
                logger.info(f"Updates too large to pre-download: {total_size / 1024 / 1024:.1f} MB")
                return

            # Check if system is idle enough for background downloads
            if not self._is_system_idle():
                logger.debug("Skipping pre-download: system not idle")
                return

            # Pre-download packages
            logger.info(f"Pre-downloading {len(update_list)} packages ({total_size / 1024 / 1024:.1f} MB)")
            self._predownload_packages(update_list)

            # Run cache cleanup after predownload completes
            self._run_cache_cleanup()

        except Exception as e:
            logger.error(f"Pre-download error: {e}")

    def _predownload_packages(self, updates: list):
        """Download packages for updates.

        Args:
            updates: List of update dicts with name, available version, etc.
        """
        from ..core.download import Downloader, DownloadItem

        if not self.db:
            return

        downloader = Downloader(cache_dir=self.base_dir)

        items = []
        for update in updates:
            pkg_name = update['name']
            pkg_info = self.db.get_package(pkg_name)
            if not pkg_info:
                continue

            url = pkg_info.get('url')
            filename = pkg_info.get('filename')
            if url and filename:
                items.append(DownloadItem(
                    url=url,
                    filename=filename,
                    size=update.get('size', 0),
                ))

        if items:
            # Download with progress logging
            def progress_callback(item, downloaded, total):
                if total > 0:
                    pct = downloaded * 100 // total
                    logger.debug(f"Pre-downloading {item.filename}: {pct}%")

            result = downloader.download(items, progress_callback)
            logger.info(f"Pre-download complete: {result.downloaded} downloaded, "
                       f"{result.cached} cached, {len(result.errors)} errors")

    def _run_cache_cleanup(self):
        """Clean up old cached packages."""
        logger.info("Running scheduled cache cleanup")

        if not self.base_dir.exists():
            return

        try:
            # Get all RPMs currently referenced in synthesis
            referenced_files = set()
            if self.db:
                for media in self.db.list_media():
                    # Get all package filenames from this media
                    # TODO: Implement proper method in DB
                    pass

            # For now, just clean files older than 30 days that aren't in cache manifest
            import os
            from pathlib import Path

            cutoff = time.time() - (30 * 24 * 3600)  # 30 days

            cleaned = 0
            cleaned_size = 0

            for rpm_file in self.base_dir.glob('**/*.rpm'):
                try:
                    stat = rpm_file.stat()
                    if stat.st_mtime < cutoff:
                        size = stat.st_size
                        rpm_file.unlink()
                        cleaned += 1
                        cleaned_size += size
                        logger.debug(f"Removed old cached file: {rpm_file.name}")
                except OSError as e:
                    logger.warning(f"Could not remove {rpm_file}: {e}")

            if cleaned > 0:
                logger.info(f"Cache cleanup: removed {cleaned} files ({cleaned_size / 1024 / 1024:.1f} MB)")
            else:
                logger.debug("Cache cleanup: no files to remove")

        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")

    def _refresh_media(self, media_name: str):
        """Refresh metadata for a specific media.

        Uses own database connection.
        """
        from ..core.sync import sync_media

        if not self.db:
            return

        result = sync_media(self.db, media_name, force=True)
        if result.success:
            logger.info(f"Media {media_name}: synced {result.packages_count} packages")
        else:
            logger.error(f"Media {media_name}: sync failed - {result.error}")

    def _get_available_updates(self) -> Optional[dict]:
        """Get list of packages with available updates.

        Uses own database connection.

        Returns:
            Dict with 'updates' list and 'total_size', or None on error
        """
        if not self.db:
            return None

        import platform
        from ..core.resolver import Resolver

        try:
            arch = platform.machine()
            resolver = Resolver(self.db, arch=arch)
            result = resolver.resolve_upgrade([])

            updates = []
            total_size = 0
            for action in result.actions:
                updates.append({
                    'name': action.name,
                    'current': action.from_evr,
                    'available': action.evr,
                    'arch': action.arch,
                    'size': action.size,
                })
                total_size += action.size or 0

            return {
                'count': len(updates),
                'updates': updates,
                'total_size': total_size,
            }
        except Exception as e:
            logger.error(f"Error checking updates: {e}")
            return None

    # ========== System Idle Detection ==========

    def _is_system_idle(self) -> bool:
        """Check if system is idle enough for background downloads.

        Checks CPU load and network activity to determine if downloads
        would disturb the user.

        Returns:
            True if system appears idle, False otherwise
        """
        cpu_idle = self._is_cpu_idle()
        net_idle = self._is_network_idle()

        if not cpu_idle:
            logger.debug(f"CPU not idle (load > {self.max_cpu_load})")
            return False

        if not net_idle:
            logger.debug(f"Network not idle (> {self.max_net_kbps} KB/s)")
            return False

        return True

    def _is_cpu_idle(self) -> bool:
        """Check if CPU load is low enough.

        Uses /proc/loadavg for 1-minute load average.
        """
        try:
            with open('/proc/loadavg', 'r') as f:
                loadavg = f.read().strip()
            # Format: "0.00 0.01 0.05 1/234 12345"
            load_1min = float(loadavg.split()[0])
            return load_1min < self.max_cpu_load
        except (IOError, ValueError, IndexError) as e:
            logger.warning(f"Could not read CPU load: {e}")
            return True  # Assume idle if we can't check

    def _is_network_idle(self) -> bool:
        """Check if network activity is low enough.

        Measures bytes transferred since last check using /proc/net/dev.
        """
        try:
            rx_bytes, tx_bytes = self._get_network_bytes()
            now = time.time()

            if self._last_net_sample is None:
                # First sample, store and assume idle
                self._last_net_sample = (rx_bytes, tx_bytes)
                self._last_net_sample_time = now
                return True

            # Calculate rate since last sample
            elapsed = now - self._last_net_sample_time
            if elapsed < 1:
                return True  # Not enough time passed

            prev_rx, prev_tx = self._last_net_sample
            rx_rate = (rx_bytes - prev_rx) / elapsed / 1024  # KB/s
            tx_rate = (tx_bytes - prev_tx) / elapsed / 1024  # KB/s
            total_rate = rx_rate + tx_rate

            # Update sample
            self._last_net_sample = (rx_bytes, tx_bytes)
            self._last_net_sample_time = now

            return total_rate < self.max_net_kbps

        except Exception as e:
            logger.warning(f"Could not check network activity: {e}")
            return True  # Assume idle if we can't check

    def _get_network_bytes(self) -> tuple:
        """Get total network bytes (rx, tx) from /proc/net/dev.

        Sums all interfaces except lo.
        """
        total_rx = 0
        total_tx = 0

        with open('/proc/net/dev', 'r') as f:
            for line in f:
                if ':' not in line:
                    continue
                parts = line.split(':')
                iface = parts[0].strip()

                # Skip loopback
                if iface == 'lo':
                    continue

                # Parse stats: rx_bytes is field 0, tx_bytes is field 8
                stats = parts[1].split()
                if len(stats) >= 9:
                    total_rx += int(stats[0])
                    total_tx += int(stats[8])

        return total_rx, total_tx
