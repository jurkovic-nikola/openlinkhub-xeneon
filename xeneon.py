#!/usr/bin/python3
"""OpenLinkHub Xeneon — a small GTK window for the Xeneon kiosk."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = 'http://127.0.0.1:27003/xeneon'
CONFIG = (
    Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    / 'openlinkhub-xeneon'
)
DATA = (
    Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    / 'openlinkhub-xeneon/browser'
)
CACHE = (
    Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
    / 'openlinkhub-xeneon'
)
AUTOSTART = (
    Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    / 'autostart/openlinkhub-xeneon.desktop'
)


def validate_url(value):
    value = value.strip()
    try:
        url = urllib.parse.urlsplit(value)
        port = url.port
    except ValueError as error:
        raise ValueError('Enter a valid HTTP or HTTPS URL.') from error
    if (
        url.scheme not in ('http', 'https')
        or not url.hostname
        or url.username
        or url.password
        or any(c.isspace() for c in value)
    ):
        raise ValueError('Enter an HTTP or HTTPS URL without embedded credentials.')
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('Invalid port.')
    return value


def origin(value):
    url = urllib.parse.urlsplit(value)
    return url.scheme, url.hostname, url.port or (443 if url.scheme == 'https' else 80)


def read_config():
    defaults = {
        'url': DEFAULT_URL,
        'width': 1280,
        'height': 400,
        'x': None,
        'y': None,
        'fullscreen': False,
        'monitor': -1,
    }
    try:
        value = json.loads((CONFIG / 'settings.json').read_text())
        defaults['url'] = validate_url(value.get('url', DEFAULT_URL))
        for key, low, high in [
            ('width', 320, 16384),
            ('height', 200, 16384),
            ('monitor', -1, 64),
        ]:
            number = value.get(key)
            if type(number) is int and low <= number <= high:
                defaults[key] = number
        for key in ('x', 'y'):
            if type(value.get(key)) is int:
                defaults[key] = value[key]
        defaults['fullscreen'] = value.get('fullscreen') is True
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return defaults


def save_config(settings):
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = CONFIG / 'settings.tmp'
    temporary.write_text(json.dumps(settings, indent=4) + '\n')
    temporary.chmod(0o600)
    temporary.replace(CONFIG / 'settings.json')


def desktop_entry(script):
    # Desktop Entry Exec escaping differs from shell escaping.
    path = (
        str(Path(script).resolve())
        .replace('\\', '\\\\')
        .replace('"', '\\"')
        .replace('`', '\\`')
        .replace('$', '\\$')
        .replace('%', '%%')
    )
    return (
        '[Desktop Entry]\nType=Application\nName=OpenLinkHub Xeneon\n'
        'Comment=Xeneon kiosk window\nExec=/usr/bin/python3 "' + path + '"\n'
        'Icon=video-display\nTerminal=false\nCategories=Utility;\nStartupNotify=true\n'
    )


def set_autostart(enabled):
    if enabled:
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART.write_text(desktop_entry(__file__))
    else:
        AUTOSTART.unlink(missing_ok=True)


def reachable(url):
    try:
        request = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status < 500
    except urllib.error.HTTPError as error:
        return error.code < 500  # Authentication and HEAD-not-supported are reachable.
    except urllib.error.URLError as error:
        # WebKit performs certificate validation and asks the user before trusting.
        return isinstance(error.reason, ssl.SSLCertVerificationError)
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--url', type=validate_url, help='Kiosk URL (saved after launch)'
    )
    parser.add_argument('--fullscreen', action='store_true', help='Start fullscreen')
    parser.add_argument('--windowed', action='store_true', help='Start windowed')
    parser.add_argument(
        '--monitor', type=int, help='Zero-based monitor index; see Settings'
    )
    args = parser.parse_args()
    try:
        import gi

        gi.require_version('Gtk', '3.0')
        gi.require_version('WebKit2', '4.1')
        from gi.repository import Gtk, Gdk, Gio, GLib, WebKit2
    except (ImportError, ValueError) as error:
        print(
            'GTK3 / WebKitGTK 4.1 Python bindings are required. See README.md.\n'
            + str(error),
            file=sys.stderr,
        )
        return 1

    class Xeneon(Gtk.Application):
        def __init__(self):
            super().__init__(
                application_id='io.github.openlinkhub.Xeneon',
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self.settings = read_config()
            if args.url:
                self.settings['url'] = args.url
            if args.monitor is not None:
                self.settings['monitor'] = args.monitor
            if args.fullscreen or args.windowed:
                self.settings['fullscreen'] = args.fullscreen and not args.windowed
            self.closed = False
            self.probing = False
            self.waiting = True
            self.tls_blocked = False
            self.loading = False
            self.generation = 0

        def do_activate(self):
            self.window = Gtk.ApplicationWindow(
                application=self, title='OpenLinkHub Xeneon'
            )
            self.window.set_default_size(
                self.settings['width'], self.settings['height']
            )
            self.window.set_icon_name('video-display')
            self.header = Gtk.HeaderBar(
                title='OpenLinkHub Xeneon', show_close_button=True
            )
            self.window.set_titlebar(self.header)
            for icon, tooltip, callback in [
                ('view-refresh-symbolic', 'Reload (Ctrl+R)', self.reload),
                (
                    'view-fullscreen-symbolic',
                    'Fullscreen (F11; Escape to leave)',
                    self.toggle_fullscreen,
                ),
                ('emblem-system-symbolic', 'Settings (Ctrl+,)', self.configure),
            ]:
                button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
                button.set_tooltip_text(tooltip)
                button.connect('clicked', callback)
                self.header.pack_end(button)
            self.stack = Gtk.Stack()
            self.window.add(self.stack)
            box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=16,
                halign=Gtk.Align.CENTER,
                valign=Gtk.Align.CENTER,
            )
            self.message = Gtk.Label(label='Waiting for OpenLinkHub…')
            box.pack_start(self.message, False, False, 0)
            self.address = Gtk.Label(label=self.settings['url'])
            box.pack_start(self.address, False, False, 0)
            retry = Gtk.Button(label='Retry')
            retry.connect('clicked', self.reload)
            box.pack_start(retry, False, False, 0)
            settings_button = Gtk.Button(label='Settings')
            settings_button.connect('clicked', self.configure)
            box.pack_start(settings_button, False, False, 0)
            self.stack.add_named(box, 'waiting')
            for path in (DATA, CACHE):
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
            manager = WebKit2.WebsiteDataManager(
                base_data_directory=str(DATA), base_cache_directory=str(CACHE)
            )
            self.context = WebKit2.WebContext.new_with_website_data_manager(manager)
            self.context.get_cookie_manager().set_persistent_storage(
                str(DATA / 'cookies.sqlite'), WebKit2.CookiePersistentStorage.SQLITE
            )
            self.web = WebKit2.WebView.new_with_context(self.context)
            self.web.get_settings().set_hardware_acceleration_policy(
                WebKit2.HardwareAccelerationPolicy.NEVER
            )
            self.web.get_settings().set_enable_developer_extras(False)
            self.web.connect('load-changed', self.load_changed)
            self.web.connect('load-failed', self.load_failed)
            self.web.connect('load-failed-with-tls-errors', self.tls_failed)
            self.web.connect('decide-policy', self.navigation)
            self.web.connect('permission-request', self.permission)
            self.web.connect('web-process-terminated', self.process_terminated)
            self.stack.add_named(self.web, 'web')
            self.window.connect('key-press-event', self.key_pressed)
            self.window.connect('window-state-event', self.window_state)
            self.window.connect('delete-event', self.close)
            self.window.connect('configure-event', self.geometry)
            self.window.show_all()
            self.stack.set_visible_child_name('waiting')
            self.place_window()
            if self.settings['fullscreen']:
                self.enter_fullscreen()
            self.reload()
            GLib.timeout_add_seconds(3, self.probe)

        def persist(self):
            try:
                save_config(self.settings)
            except OSError as error:
                print('Unable to save settings: ' + str(error), file=sys.stderr)

        def place_window(self):
            display = self.window.get_display()
            monitor = self.settings['monitor']
            if 0 <= monitor < display.get_n_monitors():
                rect = display.get_monitor(monitor).get_geometry()
                self.window.move(rect.x, rect.y)
            elif self.settings['x'] is not None and 'X11' in type(display).__name__:
                x = self.settings['x']
                y = self.settings['y'] or 0
                for index in range(display.get_n_monitors()):
                    rect = display.get_monitor(index).get_geometry()
                    if (
                        rect.x <= x < rect.x + rect.width
                        and rect.y <= y < rect.y + rect.height
                    ):
                        self.window.move(x, y)
                        break

        def enter_fullscreen(self):
            monitor = self.settings['monitor']
            if 0 <= monitor < self.window.get_display().get_n_monitors():
                self.window.fullscreen_on_monitor(self.window.get_screen(), monitor)
            else:
                self.window.fullscreen()

        def toggle_fullscreen(self, *_):
            if self.settings['fullscreen']:
                self.window.unfullscreen()
            else:
                self.enter_fullscreen()

        def window_state(self, _, event):
            self.settings['fullscreen'] = bool(
                event.new_window_state & Gdk.WindowState.FULLSCREEN
            )
            self.header.set_visible(not self.settings['fullscreen'])
            self.persist()
            return False

        def geometry(self, *_):
            native = self.window.get_window()
            if native and not native.get_state() & (
                Gdk.WindowState.FULLSCREEN | Gdk.WindowState.MAXIMIZED
            ):
                size = self.window.get_size()
                self.settings['width'] = size[0]
                self.settings['height'] = size[1]
                if 'X11' in type(self.window.get_display()).__name__:
                    position = self.window.get_position()
                    self.settings['x'] = position[0]
                    self.settings['y'] = position[1]
            return False

        def key_pressed(self, _, event):
            ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
            if event.keyval == Gdk.KEY_F11:
                self.toggle_fullscreen()
            elif event.keyval == Gdk.KEY_Escape and self.settings['fullscreen']:
                self.window.unfullscreen()
            elif ctrl and event.keyval in (Gdk.KEY_r, Gdk.KEY_R):
                self.reload()
            elif ctrl and event.keyval == Gdk.KEY_comma:
                self.configure()
            elif ctrl and event.keyval in (Gdk.KEY_q, Gdk.KEY_Q):
                self.window.close()
            else:
                return False
            return True

        def reload(self, *_):
            self.tls_blocked = False
            self.loading = True
            self.load_started = time.monotonic()
            self.waiting = False
            self.message.set_text('Connecting to OpenLinkHub…')
            self.web.load_uri(self.settings['url'])

        def load_changed(self, _, event):
            if event == WebKit2.LoadEvent.STARTED:
                self.loading = True
                self.load_started = time.monotonic()
            elif event == WebKit2.LoadEvent.COMMITTED:
                self.stack.set_visible_child_name('web')
            elif event == WebKit2.LoadEvent.FINISHED:
                self.loading = False

        def load_failed(self, _, event, uri, error):
            if error.matches(
                WebKit2.network_error_quark(), WebKit2.NetworkError.CANCELLED
            ):
                return True
            self.loading = False
            self.waiting = True
            self.stack.set_visible_child_name('waiting')
            if self.tls_blocked:
                self.message.set_text('Certificate not trusted. Press Retry to review.')
            else:
                self.message.set_text('Waiting for OpenLinkHub…')
            return True

        def process_terminated(self, *_):
            self.loading = False
            self.waiting = True
            self.stack.set_visible_child_name('waiting')
            self.message.set_text('Display process stopped. Reconnecting…')

        def probe(self):
            if self.closed:
                return False
            if self.loading and time.monotonic() - self.load_started > 20:
                self.web.stop_loading()
                self.loading = False
                self.waiting = True
                self.stack.set_visible_child_name('waiting')
                self.message.set_text('Connection timed out. Reconnecting…')
            if self.probing or self.loading or self.tls_blocked:
                return True
            self.probing = True
            generation = self.generation
            url = self.settings['url']

            def worker():
                online = reachable(url)
                GLib.idle_add(self.probed, online, generation)

            threading.Thread(target=worker, daemon=True).start()
            return True

        def probed(self, online, generation):
            self.probing = False
            if (
                self.closed
                or generation != self.generation
                or self.tls_blocked
                or self.loading
            ):
                return False
            if online and self.waiting:
                self.reload()
            elif not online:
                self.waiting = True
                self.message.set_text('Waiting for OpenLinkHub…')
                self.stack.set_visible_child_name('waiting')
            return False

        def tls_failed(self, _, uri, certificate, errors):
            self.loading = False
            self.tls_blocked = True
            if origin(uri) != origin(self.settings['url']):
                return False
            pem = certificate.props.certificate_pem
            fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
            dialog = Gtk.MessageDialog(
                transient_for=self.window,
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                text='Trust this OpenLinkHub certificate for this session?',
            )
            dialog.format_secondary_text(
                uri
                + '\n\nSHA-256:\n'
                + fingerprint
                + '\n\nOnly accept a certificate from your OpenLinkHub installation.'
            )
            dialog.add_buttons(
                'Cancel',
                Gtk.ResponseType.CANCEL,
                'Trust for this session',
                Gtk.ResponseType.ACCEPT,
            )
            answer = dialog.run()
            dialog.destroy()
            if answer == Gtk.ResponseType.ACCEPT:
                self.context.allow_tls_certificate_for_host(
                    certificate, urllib.parse.urlsplit(uri).hostname
                )
                GLib.idle_add(self.reload)
            else:
                self.waiting = True
                self.message.set_text('Certificate not trusted. Press Retry to review.')
                self.stack.set_visible_child_name('waiting')
            return True

        def navigation(self, _, decision, kind):
            if kind not in (
                WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
                WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION,
            ):
                return False
            action = decision.get_navigation_action()
            uri = action.get_request().get_uri()
            if origin(uri) == origin(self.settings['url']):
                if kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                    decision.ignore()
                    self.web.load_uri(uri)
                    return True
                return False
            decision.ignore()
            if action.is_user_gesture() and urllib.parse.urlsplit(uri).scheme in (
                'http',
                'https',
            ):
                Gio.AppInfo.launch_default_for_uri(uri, None)
            return True

        def permission(self, _, request):
            if isinstance(request, WebKit2.GeolocationPermissionRequest):
                dialog = Gtk.MessageDialog(
                    transient_for=self.window,
                    modal=True,
                    message_type=Gtk.MessageType.QUESTION,
                    buttons=Gtk.ButtonsType.YES_NO,
                    text='Allow location access for the weather widget?',
                )
                allow = dialog.run() == Gtk.ResponseType.YES
                dialog.destroy()
                if allow:
                    request.allow()
                else:
                    request.deny()
            else:
                request.deny()
            return True

        def configure(self, *_):
            dialog = Gtk.Dialog(
                title='Display settings', transient_for=self.window, modal=True
            )
            dialog.add_buttons(
                'Cancel', Gtk.ResponseType.CANCEL, 'Save', Gtk.ResponseType.OK
            )
            grid = Gtk.Grid(column_spacing=12, row_spacing=12, margin=18)
            dialog.get_content_area().add(grid)
            entry = Gtk.Entry(text=self.settings['url'], width_chars=48)
            grid.attach(Gtk.Label(label='Kiosk URL', xalign=0), 0, 0, 1, 1)
            grid.attach(entry, 1, 0, 1, 1)
            monitors = Gtk.ComboBoxText()
            monitors.append('-1', 'Desktop default / saved position')
            display = self.window.get_display()
            for index in range(display.get_n_monitors()):
                monitor = display.get_monitor(index)
                rect = monitor.get_geometry()
                monitors.append(
                    str(index),
                    f'{index}: {monitor.get_model() or "Monitor"} ({rect.width} × {rect.height})',
                )
            monitors.set_active_id(str(self.settings['monitor']))
            if monitors.get_active_id() is None:
                monitors.set_active_id('-1')
            grid.attach(Gtk.Label(label='Monitor', xalign=0), 0, 1, 1, 1)
            grid.attach(monitors, 1, 1, 1, 1)
            fullscreen = Gtk.CheckButton(
                label='Fullscreen', active=self.settings['fullscreen']
            )
            autostart = Gtk.CheckButton(
                label='Start when I log in', active=AUTOSTART.exists()
            )
            grid.attach(fullscreen, 1, 2, 1, 1)
            grid.attach(autostart, 1, 3, 1, 1)
            error = Gtk.Label(xalign=0, wrap=True)
            grid.attach(error, 0, 4, 2, 1)
            dialog.show_all()
            while dialog.run() == Gtk.ResponseType.OK:
                try:
                    url = validate_url(entry.get_text())
                    set_autostart(autostart.get_active())
                except (ValueError, OSError) as failure:
                    error.set_text(str(failure))
                    continue
                self.settings['url'] = url
                self.settings['monitor'] = int(monitors.get_active_id())
                self.settings['fullscreen'] = fullscreen.get_active()
                self.address.set_text(url)
                self.generation += 1
                self.persist()
                self.place_window()
                if fullscreen.get_active():
                    self.enter_fullscreen()
                else:
                    self.window.unfullscreen()
                self.reload()
                break
            dialog.destroy()

        def close(self, *_):
            self.closed = True
            self.persist()
            self.quit()
            return False

    return Xeneon().run([sys.argv[0]])


if __name__ == '__main__':
    sys.exit(main())
