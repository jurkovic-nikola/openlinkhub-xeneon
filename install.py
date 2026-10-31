#!/usr/bin/python3
"""Install or uninstall OpenLinkHub Xeneon for the current user."""
import argparse
import os
from pathlib import Path
import shutil
from xeneon import desktop_entry, AUTOSTART

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--uninstall', action='store_true')
args = parser.parse_args()
data = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
target = data / 'openlinkhub-xeneon/app'
launcher = data / 'applications/openlinkhub-xeneon.desktop'
if args.uninstall:
    launcher.unlink(missing_ok=True)
    AUTOSTART.unlink(missing_ok=True)
    if target.exists():
        shutil.rmtree(target)
    print('Application removed. Browser data and settings were kept.')
else:
    target.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent
    for name in ('xeneon.py', 'README.md', 'LICENSE'):
        shutil.copy2(source / name, target / name)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(desktop_entry(target / 'xeneon.py'))
    print('Installed. Open “OpenLinkHub Xeneon” from your application menu.')
