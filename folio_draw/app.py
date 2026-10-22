"""Application entry point."""

import os
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import theme  # noqa: E402
from .window import Window  # noqa: E402


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.folio.Draw", flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE)
        GLib.set_application_name("Folio Draw")
        GLib.set_prgname("folio-draw")

    def do_startup(self):
        Gtk.Application.do_startup(self)
        theme.install()
        here = os.path.dirname(os.path.abspath(__file__))
        icons = os.path.join(here, "..", "data", "icons")
        if os.path.isdir(icons):
            Gtk.IconTheme.get_default().append_search_path(os.path.abspath(icons))

    def do_activate(self):
        Window(self).present()

    def do_open(self, files, n, hint):
        for f in files:
            Window(self, f.get_path()).present()


def main(argv=None):
    return App().run(argv if argv is not None else sys.argv)
