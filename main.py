# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Entry point for the standalone Sugar Activity Studio."""

import logging
import os
import signal
import sys


def _check_dependencies():
    """Fail with a friendly message when the GTK/Sugar stack is missing."""
    missing = []
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk  # noqa: F401
    except (ImportError, ValueError):
        missing.append('GTK 3 with PyGObject (python3-gi, gir1.2-gtk-3.0)')
    try:
        import sugar3.graphics.style  # noqa: F401
    except ImportError:
        missing.append('the Sugar toolkit (python3-sugar3 / '
                       'sugar-toolkit-gtk3)')
    if missing:
        sys.stderr.write(
            'sugar-aod-studio needs system packages that are not '
            'installed:\n')
        for item in missing:
            sys.stderr.write('  - %s\n' % item)
        sys.stderr.write('See README.md for install instructions.\n')
        return False
    return True


def _setup_theme():
    """Prefer Sugar's GTK and icon themes when they are installed.

    Mirrors the Sugar shell's setup_theme(); every step degrades
    silently on desktops without the sugar-artwork themes.
    """
    from gi.repository import Gtk

    settings = Gtk.Settings.get_default()
    if settings is None:
        return
    sugar_theme = 'sugar-72'
    if 'SUGAR_SCALING' in os.environ:
        if os.environ['SUGAR_SCALING'] == '100':
            sugar_theme = 'sugar-100'
    try:
        if _icon_theme_exists('sugar'):
            settings.set_property('gtk-icon-theme-name', 'sugar')
    except Exception:
        logging.debug('Sugar icon theme unavailable', exc_info=True)
    try:
        screen = settings.get_property('gtk-theme-name')
        if _gtk_theme_exists(sugar_theme):
            settings.set_property('gtk-theme-name', sugar_theme)
        else:
            logging.debug('Sugar GTK theme not installed; keeping %s',
                          screen)
    except Exception:
        logging.debug('Could not apply Sugar GTK theme', exc_info=True)
    settings.set_property('gtk-button-images', True)


def _gtk_theme_exists(name):
    candidates = [
        os.path.join(os.path.expanduser('~/.themes'), name),
        os.path.join('/usr/share/themes', name),
    ]
    return any(os.path.isdir(path) for path in candidates)


def _icon_theme_exists(name):
    # Icon themes live under any XDG data dir (so a bundled/AppImage copy in
    # XDG_DATA_DIRS is found too), plus the user's ~/.icons.
    data_dirs = os.environ.get(
        'XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':')
    roots = [os.path.expanduser('~/.icons')]
    roots += [os.path.join(d, 'icons') for d in data_dirs if d]
    return any(os.path.isdir(os.path.join(root, name)) for root in roots)


def run():
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get('AOD_STUDIO_DEBUG')
        else logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    if not _check_dependencies():
        return 1

    _setup_theme()

    from gi.repository import Gtk

    from ui.window import AODStudioWindow

    window = AODStudioWindow()
    window.connect('destroy', lambda w: Gtk.main_quit())
    window.show()

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    Gtk.main()
    return 0


if __name__ == '__main__':
    sys.exit(run())
