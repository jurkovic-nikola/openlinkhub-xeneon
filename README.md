# OpenLinkHub Xeneon

A standalone Linux desktop window for `http://127.0.0.1:27003/xeneon`.
Uses Python 3, GTK 3 and WebKitGTK 4.1.

## Install

Install the runtime once:

Fedora:
```sh
sudo dnf install python3-gobject gtk3 webkit2gtk4.1
```

Ubuntu / Debian (with WebKitGTK 4.1 available):
```sh
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

From this extracted folder, run **as your desktop user, without sudo**:
```sh
python3 install.py
```

Then open **OpenLinkHub Xeneon** from your application menu. Alternatively run:
```sh
/usr/bin/python3 xeneon.py
```

## Controls
The title bar provides reload, fullscreen and settings buttons.
- **F11**: toggle fullscreen.
- **Escape**: leave fullscreen to reveal the title bar.
- **Ctrl+R**: reload the configured kiosk URL.
- **Ctrl+,**: open settings.
- **Ctrl+Q** or the window close button: exit.

Settings lets you choose the URL and monitor, enable fullscreen, and enable desktop-login startup. Save applies immediately. Size, position (X11), fullscreen and monitor selection are retained on normal exit. The monitor index follows the desktop's enumeration and may change after rearranging displays.

Command-line overrides:
```sh
/usr/bin/python3 xeneon.py --url http://127.0.0.1:27003/xeneon
/usr/bin/python3 xeneon.py --fullscreen --monitor 1
/usr/bin/python3 xeneon.py --windowed
```

## Files and uninstall
- App: `~/.local/share/openlinkhub-xeneon/app/`
- Settings: `~/.config/openlinkhub-xeneon/settings.json`
- Browser profile: `~/.local/share/openlinkhub-xeneon/browser/`
- Cache: `~/.cache/openlinkhub-xeneon/`
- Optional autostart: `~/.config/autostart/openlinkhub-xeneon.desktop`

The corresponding XDG environment variables are respected. No root service is installed.

```sh
python3 install.py --uninstall
```

Uninstall removes the launcher, autostart entry and app files, retaining settings and browser data. Delete those directories separately if you also want to remove saved login state.