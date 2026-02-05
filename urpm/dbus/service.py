"""D-Bus service for urpm package management.

Exposes urpm PackageOperations over the system bus at:
    Bus name:    org.mageia.Urpm.v1
    Object path: /org/mageia/Urpm/v1

Authorization is handled via PolicyKit for all privileged operations.
Read-only operations (search, info, list updates) require no auth.

Write operations (install, remove, upgrade, refresh) run in a background
thread and emit OperationProgress/OperationComplete D-Bus signals.

Usage:
    urpm-dbus-service          # Run as D-Bus activated service
    urpm-dbus-service --debug  # Run with debug logging
"""

import json
import logging
import os
import platform
import signal
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# D-Bus names
BUS_NAME = "org.mageia.Urpm.v1"
OBJECT_PATH = "/org/mageia/Urpm/v1"
INTERFACE_NAME = "org.mageia.Urpm.v1"


class UrpmDBusService:
    """D-Bus service exposing urpm operations.

    Each method:
    1. Identifies the caller (pid/uid via D-Bus credentials)
    2. Checks PolicyKit authorization
    3. Calls PackageOperations
    4. Emits progress signals
    5. Returns result
    """

    def __init__(self):
        self._ops = None
        self._db = None
        self._polkit = None
        self._audit = None
        self._loop = None
        self._connection = None
        self._active_operations = {}
        self._lock = threading.Lock()

    def _init_core(self):
        """Lazy-init core components."""
        if self._db is not None:
            return

        from ..core.database import PackageDatabase
        from ..core.operations import PackageOperations
        from ..auth.polkit import PolicyKitBackend
        from ..auth.audit import AuditLogger

        self._db = PackageDatabase()
        self._audit = AuditLogger()
        self._ops = PackageOperations(self._db, audit_logger=self._audit)
        self._polkit = PolicyKitBackend()

    def _get_caller_credentials(self, bus, sender):
        """Get caller PID and UID from D-Bus sender."""
        try:
            import gi
            gi.require_version('Gio', '2.0')
            from gi.repository import Gio, GLib

            result = bus.call_sync(
                'org.freedesktop.DBus',
                '/org/freedesktop/DBus',
                'org.freedesktop.DBus',
                'GetConnectionUnixProcessID',
                GLib.Variant('(s)', (sender,)),
                GLib.VariantType.new('(u)'),
                Gio.DBusCallFlags.NONE,
                -1, None,
            )
            pid = result.unpack()[0]

            result = bus.call_sync(
                'org.freedesktop.DBus',
                '/org/freedesktop/DBus',
                'org.freedesktop.DBus',
                'GetConnectionUnixUser',
                GLib.Variant('(s)', (sender,)),
                GLib.VariantType.new('(u)'),
                Gio.DBusCallFlags.NONE,
                -1, None,
            )
            uid = result.unpack()[0]

            return pid, uid
        except Exception as e:
            logger.error(f"Cannot get caller credentials: {e}")
            return None, None

    def _authorize(self, bus, sender, permission):
        """Authorize a caller for a permission. Returns AuthContext or None."""
        pid, uid = self._get_caller_credentials(bus, sender)
        if pid is None:
            return None

        try:
            context, denied = self._polkit.create_auth_context(
                pid, uid, permission
            )
            if denied:
                logger.info(f"Denied {denied} for pid={pid} uid={uid}")
                return None
            return context
        except Exception as e:
            logger.error(f"Authorization failed: {e}")
            return None

    # =====================================================================
    # D-Bus signal emission
    # =====================================================================

    def _emit_progress(self, op_id, phase, package, current, total, message=""):
        """Emit OperationProgress signal on the main loop thread."""
        from gi.repository import GLib

        def _emit():
            if self._connection:
                self._connection.emit_signal(
                    None, OBJECT_PATH, INTERFACE_NAME,
                    "OperationProgress",
                    GLib.Variant('(sssuus)', (
                        op_id, phase, package,
                        current, total, message
                    ))
                )
            return False  # Don't repeat

        GLib.idle_add(_emit)

    def _emit_complete(self, op_id, success, message=""):
        """Emit OperationComplete signal on the main loop thread."""
        from gi.repository import GLib

        def _emit():
            if self._connection:
                self._connection.emit_signal(
                    None, OBJECT_PATH, INTERFACE_NAME,
                    "OperationComplete",
                    GLib.Variant('(sbs)', (op_id, success, message))
                )
            return False

        GLib.idle_add(_emit)

    def _return_invocation(self, invocation, success, error=""):
        """Return D-Bus method result on the main loop thread."""
        from gi.repository import GLib

        def _return():
            try:
                invocation.return_value(
                    GLib.Variant('(bs)', (success, error))
                )
            except Exception as e:
                logger.error(f"Failed to return invocation: {e}")
            return False

        GLib.idle_add(_return)

    # =====================================================================
    # Read-only handlers (synchronous)
    # =====================================================================

    def handle_search_packages(self, bus, sender, pattern, search_provides):
        """SearchPackages(pattern: s, search_provides: b) -> s (JSON)"""
        self._init_core()
        return self._ops.search_packages(
            pattern, search_provides=search_provides, limit=200
        )

    def handle_get_package_info(self, bus, sender, identifier):
        """GetPackageInfo(identifier: s) -> s (JSON)"""
        self._init_core()
        return self._ops.get_package_info(identifier)

    def handle_get_updates(self, bus, sender):
        """GetUpdates() -> s (JSON)"""
        self._init_core()
        success, upgrades, problems = self._ops.get_updates()

        upgrade_dicts = []
        for u in upgrades:
            upgrade_dicts.append({
                'name': u.name,
                'nevra': u.nevra,
                'evr': u.evr,
                'arch': u.arch,
                'size': u.size or 0,
            })

        return success, upgrade_dicts, problems

    # =====================================================================
    # Write handlers (async via thread)
    # =====================================================================

    def _run_install(self, op_id, context, package_names, invocation):
        """Install packages in a background thread."""
        from ..core.resolver import Resolver
        from ..core.operations import InstallOptions

        try:
            self._emit_progress(op_id, "resolving", "", 0, 0)

            resolver = Resolver(self._db, arch=platform.machine())
            result = resolver.resolve_install(package_names)

            if not result.success:
                problems = "; ".join(result.problems) if result.problems else "Resolution failed"
                self._emit_complete(op_id, False, problems)
                self._return_invocation(invocation, False, problems)
                return

            actions = result.actions
            if not actions:
                self._emit_complete(op_id, True, "Nothing to do")
                self._return_invocation(invocation, True, "Nothing to do")
                return

            # Build download items
            self._emit_progress(op_id, "downloading", "", 0, len(actions))
            download_items, local_paths = self._ops.build_download_items(
                actions, resolver
            )

            # Download
            rpm_paths = list(local_paths)
            if download_items:
                def dl_progress(name, pkg_num, pkg_total, dl_bytes, dl_total,
                               item_bytes=None, item_total=None, active_downloads=None):
                    self._emit_progress(
                        op_id, "downloading", name or "", pkg_num, pkg_total
                    )

                dl_results, downloaded, cached, _ = self._ops.download_packages(
                    download_items, progress_callback=dl_progress
                )
                for r in dl_results:
                    if r.path:
                        rpm_paths.append(str(r.path))

            if not rpm_paths:
                self._emit_complete(op_id, False, "No packages downloaded")
                self._return_invocation(invocation, False, "No packages downloaded")
                return

            # Transaction
            transaction_id = self._ops.begin_transaction(
                'install', f"dbus:InstallPackages {' '.join(package_names)}",
                actions
            )

            # Install
            self._emit_progress(op_id, "installing", "", 0, len(rpm_paths))

            def install_progress(op, name, current, total):
                self._emit_progress(op_id, "installing", name, current, total)

            options = InstallOptions()
            self._ops.execute_install(
                rpm_paths, options=options,
                progress_callback=install_progress,
                auth_context=context
            )

            self._ops.mark_dependencies(resolver, actions)
            self._ops.complete_transaction(transaction_id)
            self._ops.notify_urpmd_cache_invalidate()

            msg = f"Installed {len(rpm_paths)} package(s)"
            self._emit_complete(op_id, True, msg)
            self._return_invocation(invocation, True, msg)

        except Exception as e:
            logger.exception(f"Install failed: {e}")
            self._emit_complete(op_id, False, str(e))
            self._return_invocation(invocation, False, str(e))
        finally:
            with self._lock:
                self._active_operations.pop(op_id, None)

    def _run_remove(self, op_id, context, package_names, invocation):
        """Remove packages in a background thread."""
        from ..core.resolver import Resolver
        from ..core.operations import InstallOptions

        try:
            self._emit_progress(op_id, "resolving", "", 0, 0)

            resolver = Resolver(self._db, arch=platform.machine())
            result = resolver.resolve_remove(package_names)

            if not result.success:
                problems = "; ".join(result.problems) if result.problems else "Resolution failed"
                self._emit_complete(op_id, False, problems)
                self._return_invocation(invocation, False, problems)
                return

            actions = result.actions
            if not actions:
                self._emit_complete(op_id, True, "Nothing to do")
                self._return_invocation(invocation, True, "Nothing to do")
                return

            # Build list of packages to remove
            from ..core.resolver import TransactionType
            remove_names = [a.name for a in actions
                           if a.action == TransactionType.REMOVE]

            if not remove_names:
                self._emit_complete(op_id, True, "Nothing to remove")
                self._return_invocation(invocation, True, "Nothing to remove")
                return

            # Transaction
            transaction_id = self._ops.begin_transaction(
                'remove', f"dbus:RemovePackages {' '.join(package_names)}",
                actions
            )

            # Execute removal
            self._emit_progress(op_id, "removing", "", 0, len(remove_names))

            def erase_progress(op, name, current, total):
                self._emit_progress(op_id, "removing", name, current, total)

            options = InstallOptions()
            self._ops.execute_erase(
                remove_names, options=options,
                progress_callback=erase_progress,
                auth_context=context
            )

            self._ops.complete_transaction(transaction_id)

            msg = f"Removed {len(remove_names)} package(s)"
            self._emit_complete(op_id, True, msg)
            self._return_invocation(invocation, True, msg)

        except Exception as e:
            logger.exception(f"Remove failed: {e}")
            self._emit_complete(op_id, False, str(e))
            self._return_invocation(invocation, False, str(e))
        finally:
            with self._lock:
                self._active_operations.pop(op_id, None)

    def _run_upgrade(self, op_id, context, invocation):
        """Upgrade system packages in a background thread."""
        from ..core.resolver import Resolver, TransactionType
        from ..core.operations import InstallOptions

        try:
            self._emit_progress(op_id, "resolving", "", 0, 0)

            resolver = Resolver(self._db, arch=platform.machine())
            result = resolver.resolve_upgrade()

            if not result.success:
                problems = "; ".join(result.problems) if result.problems else "Resolution failed"
                self._emit_complete(op_id, False, problems)
                self._return_invocation(invocation, False, problems)
                return

            actions = result.actions
            if not actions:
                msg = "System is up to date"
                self._emit_complete(op_id, True, msg)
                self._return_invocation(invocation, True, msg)
                return

            # Separate upgrades and removals
            upgrade_actions = [a for a in actions if a.action != TransactionType.REMOVE]
            remove_names = [a.name for a in actions if a.action == TransactionType.REMOVE]

            # Build download items for upgrades
            self._emit_progress(op_id, "downloading", "", 0, len(upgrade_actions))
            download_items, local_paths = self._ops.build_download_items(
                actions, resolver
            )

            # Download
            rpm_paths = list(local_paths)
            if download_items:
                def dl_progress(name, pkg_num, pkg_total, dl_bytes, dl_total,
                               item_bytes=None, item_total=None, active_downloads=None):
                    self._emit_progress(
                        op_id, "downloading", name or "", pkg_num, pkg_total
                    )

                dl_results, downloaded, cached, _ = self._ops.download_packages(
                    download_items, progress_callback=dl_progress
                )
                for r in dl_results:
                    if r.path:
                        rpm_paths.append(str(r.path))

            if not rpm_paths and not remove_names:
                msg = "Nothing to upgrade"
                self._emit_complete(op_id, True, msg)
                self._return_invocation(invocation, True, msg)
                return

            # Transaction
            transaction_id = self._ops.begin_transaction(
                'upgrade', "dbus:UpgradePackages", actions
            )

            # Execute upgrade
            total = len(rpm_paths) + len(remove_names)
            self._emit_progress(op_id, "upgrading", "", 0, total)

            def upgrade_progress(op, name, current, total_q):
                self._emit_progress(op_id, "upgrading", name, current, total_q)

            options = InstallOptions()
            self._ops.execute_upgrade(
                rpm_paths, erase_names=remove_names,
                options=options,
                progress_callback=upgrade_progress,
                auth_context=context
            )

            self._ops.mark_dependencies(resolver, actions)
            self._ops.complete_transaction(transaction_id)
            self._ops.notify_urpmd_cache_invalidate()

            msg = f"Upgraded {len(rpm_paths)} package(s)"
            if remove_names:
                msg += f", removed {len(remove_names)}"
            self._emit_complete(op_id, True, msg)
            self._return_invocation(invocation, True, msg)

        except Exception as e:
            logger.exception(f"Upgrade failed: {e}")
            self._emit_complete(op_id, False, str(e))
            self._return_invocation(invocation, False, str(e))
        finally:
            with self._lock:
                self._active_operations.pop(op_id, None)

    def _run_refresh(self, op_id, context, invocation):
        """Refresh metadata in a background thread."""
        try:
            from ..core.sync import sync_all_media

            self._emit_progress(op_id, "refreshing", "", 0, 0)

            def refresh_progress(media_name, stage, current, total):
                self._emit_progress(
                    op_id, "refreshing", media_name, current, total, stage
                )

            results = sync_all_media(self._db, refresh_progress, force=True)

            success_count = sum(1 for r in results if r.success)
            fail_count = sum(1 for r in results if not r.success)

            if fail_count == 0:
                msg = f"Refreshed {success_count} media"
                self._emit_complete(op_id, True, msg)
                self._return_invocation(invocation, True, msg)
            else:
                errors = [f"{r.media_name}: {r.error}" for r in results if not r.success]
                msg = f"Refreshed {success_count}, failed {fail_count}: {'; '.join(errors)}"
                self._emit_complete(op_id, fail_count == len(results), msg)
                self._return_invocation(
                    invocation, success_count > 0, msg
                )

        except Exception as e:
            logger.exception(f"Refresh failed: {e}")
            self._emit_complete(op_id, False, str(e))
            self._return_invocation(invocation, False, str(e))
        finally:
            with self._lock:
                self._active_operations.pop(op_id, None)

    # =====================================================================
    # Write method dispatchers
    # =====================================================================

    def handle_install_packages(self, bus, sender, package_names, options,
                                invocation):
        """InstallPackages - async via thread."""
        from ..auth.context import Permission

        self._init_core()

        context = self._authorize(bus, sender, Permission.INSTALL)
        if context is None:
            return False, "Authorization denied"

        op_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._active_operations[op_id] = "install"

        thread = threading.Thread(
            target=self._run_install,
            args=(op_id, context, list(package_names), invocation),
            daemon=True,
        )
        thread.start()
        return None  # Signal: invocation will be returned later

    def handle_remove_packages(self, bus, sender, package_names, options,
                               invocation):
        """RemovePackages - async via thread."""
        from ..auth.context import Permission

        self._init_core()

        context = self._authorize(bus, sender, Permission.REMOVE)
        if context is None:
            return False, "Authorization denied"

        op_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._active_operations[op_id] = "remove"

        thread = threading.Thread(
            target=self._run_remove,
            args=(op_id, context, list(package_names), invocation),
            daemon=True,
        )
        thread.start()
        return None

    def handle_upgrade_packages(self, bus, sender, options, invocation):
        """UpgradePackages - async via thread."""
        from ..auth.context import Permission

        self._init_core()

        context = self._authorize(bus, sender, Permission.UPGRADE)
        if context is None:
            return False, "Authorization denied"

        op_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._active_operations[op_id] = "upgrade"

        thread = threading.Thread(
            target=self._run_upgrade,
            args=(op_id, context, invocation),
            daemon=True,
        )
        thread.start()
        return None

    def handle_refresh_metadata(self, bus, sender, invocation):
        """RefreshMetadata - async via thread."""
        from ..auth.context import Permission

        self._init_core()

        context = self._authorize(bus, sender, Permission.REFRESH)
        if context is None:
            return False, "Authorization denied"

        op_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._active_operations[op_id] = "refresh"

        thread = threading.Thread(
            target=self._run_refresh,
            args=(op_id, context, invocation),
            daemon=True,
        )
        thread.start()
        return None

    # =====================================================================
    # D-Bus registration (GLib/Gio)
    # =====================================================================

    def _build_introspection_xml(self):
        """Build D-Bus introspection XML for the interface."""
        return f"""
<node>
  <interface name="{INTERFACE_NAME}">
    <method name="SearchPackages">
      <arg name="pattern" type="s" direction="in"/>
      <arg name="search_provides" type="b" direction="in"/>
      <arg name="results" type="s" direction="out"/>
    </method>
    <method name="GetPackageInfo">
      <arg name="identifier" type="s" direction="in"/>
      <arg name="info" type="s" direction="out"/>
    </method>
    <method name="GetUpdates">
      <arg name="result" type="s" direction="out"/>
    </method>
    <method name="InstallPackages">
      <arg name="packages" type="as" direction="in"/>
      <arg name="options" type="a{{sv}}" direction="in"/>
      <arg name="success" type="b" direction="out"/>
      <arg name="error" type="s" direction="out"/>
    </method>
    <method name="RemovePackages">
      <arg name="packages" type="as" direction="in"/>
      <arg name="options" type="a{{sv}}" direction="in"/>
      <arg name="success" type="b" direction="out"/>
      <arg name="error" type="s" direction="out"/>
    </method>
    <method name="UpgradePackages">
      <arg name="options" type="a{{sv}}" direction="in"/>
      <arg name="success" type="b" direction="out"/>
      <arg name="error" type="s" direction="out"/>
    </method>
    <method name="RefreshMetadata">
      <arg name="success" type="b" direction="out"/>
      <arg name="error" type="s" direction="out"/>
    </method>
    <signal name="OperationProgress">
      <arg name="operation_id" type="s"/>
      <arg name="phase" type="s"/>
      <arg name="package" type="s"/>
      <arg name="current" type="u"/>
      <arg name="total" type="u"/>
      <arg name="message" type="s"/>
    </signal>
    <signal name="OperationComplete">
      <arg name="operation_id" type="s"/>
      <arg name="success" type="b"/>
      <arg name="message" type="s"/>
    </signal>
  </interface>
</node>
"""

    def _on_method_call(self, connection, sender, object_path, interface_name,
                        method_name, parameters, invocation):
        """Handle incoming D-Bus method calls."""
        try:
            from gi.repository import GLib

            if method_name == "SearchPackages":
                pattern, search_provides = parameters.unpack()
                results = self.handle_search_packages(
                    connection, sender, pattern, search_provides
                )
                invocation.return_value(
                    GLib.Variant('(s)', (json.dumps(results),))
                )

            elif method_name == "GetPackageInfo":
                identifier = parameters.unpack()[0]
                info = self.handle_get_package_info(
                    connection, sender, identifier
                )
                invocation.return_value(
                    GLib.Variant('(s)', (json.dumps(info),))
                )

            elif method_name == "GetUpdates":
                success, upgrades, problems = self.handle_get_updates(
                    connection, sender
                )
                result = {
                    'success': success,
                    'upgrades': upgrades,
                    'problems': problems,
                }
                invocation.return_value(
                    GLib.Variant('(s)', (json.dumps(result),))
                )

            elif method_name == "InstallPackages":
                packages, options = parameters.unpack()
                ret = self.handle_install_packages(
                    connection, sender, packages, options, invocation
                )
                if ret is not None:
                    # Auth denied - return synchronously
                    success, error = ret
                    invocation.return_value(
                        GLib.Variant('(bs)', (success, error))
                    )
                # else: invocation returned async from thread

            elif method_name == "RemovePackages":
                packages, options = parameters.unpack()
                ret = self.handle_remove_packages(
                    connection, sender, packages, options, invocation
                )
                if ret is not None:
                    success, error = ret
                    invocation.return_value(
                        GLib.Variant('(bs)', (success, error))
                    )

            elif method_name == "UpgradePackages":
                options = parameters.unpack()[0]
                ret = self.handle_upgrade_packages(
                    connection, sender, options, invocation
                )
                if ret is not None:
                    success, error = ret
                    invocation.return_value(
                        GLib.Variant('(bs)', (success, error))
                    )

            elif method_name == "RefreshMetadata":
                ret = self.handle_refresh_metadata(
                    connection, sender, invocation
                )
                if ret is not None:
                    success, error = ret
                    invocation.return_value(
                        GLib.Variant('(bs)', (success, error))
                    )

            else:
                invocation.return_dbus_error(
                    'org.freedesktop.DBus.Error.UnknownMethod',
                    f'Unknown method: {method_name}'
                )

        except Exception as e:
            logger.exception(f"Error handling {method_name}")
            invocation.return_dbus_error(
                'org.mageia.Urpm.v1.Error',
                str(e)
            )

    def run(self, debug: bool = False):
        """Run the D-Bus service (main loop)."""
        import gi
        gi.require_version('Gio', '2.0')
        from gi.repository import Gio, GLib

        if debug:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)

        logger.info(f"Starting urpm D-Bus service ({BUS_NAME})")

        node_info = Gio.DBusNodeInfo.new_for_xml(
            self._build_introspection_xml()
        )
        interface_info = node_info.interfaces[0]

        def on_bus_acquired(connection, name):
            logger.info(f"Bus acquired: {name}")
            self._connection = connection
            connection.register_object(
                OBJECT_PATH,
                interface_info,
                self._on_method_call,
                None,  # get_property
                None,  # set_property
            )

        def on_name_acquired(connection, name):
            logger.info(f"Name acquired: {name}")

        def on_name_lost(connection, name):
            logger.error(f"Name lost: {name}")
            self._loop.quit()

        Gio.bus_own_name(
            Gio.BusType.SYSTEM,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            on_bus_acquired,
            on_name_acquired,
            on_name_lost,
        )

        self._loop = GLib.MainLoop()

        # Handle SIGTERM/SIGINT gracefully
        def _quit(signum, frame):
            logger.info("Received signal, shutting down")
            self._loop.quit()

        signal.signal(signal.SIGTERM, _quit)
        signal.signal(signal.SIGINT, _quit)

        try:
            self._loop.run()
        finally:
            if self._audit:
                self._audit.close()
            if self._db:
                self._db.close()
            logger.info("Service stopped")


def main():
    """Entry point for urpm-dbus-service."""
    debug = '--debug' in sys.argv
    service = UrpmDBusService()
    service.run(debug=debug)


if __name__ == '__main__':
    main()
