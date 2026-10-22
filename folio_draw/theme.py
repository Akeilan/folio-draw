"""Maroon Folio theme."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

MAROON = "#800000"
MAROON_DARK = "#5c0000"

CSS = b"""
@define-color fd_maroon #800000;
@define-color fd_maroon_dark #5c0000;
@define-color fd_tint #f7ebeb;
@define-color fd_tint2 #ecd3d3;
@define-color fd_panel #fbf8f8;
@define-color fd_line #dccfcf;

headerbar.fd-header, .fd-header {
  background: @fd_maroon; background-image: none; color: #ffffff;
  border: none; box-shadow: none; min-height: 32px; padding: 0 4px;
}
.fd-header .title, .fd-header label { color: #ffffff; }
.fd-header button { color: #ffffff; background: transparent; background-image: none;
  border: none; box-shadow: none; border-radius: 3px; padding: 2px 6px; min-height: 22px; }
.fd-header button:hover { background: rgba(255,255,255,0.16); }
.fd-header button:disabled { opacity: 0.45; }

.fd-tabs { background: @fd_maroon; padding: 0 6px; }
.fd-tab { color: #ffffff; background: transparent; background-image: none; border: none;
  border-radius: 0; box-shadow: none; padding: 4px 16px; min-height: 0; }
.fd-tab label { color: #ffffff; }
.fd-tab:hover { background: rgba(255,255,255,0.16); }
.fd-tab:checked { background: @fd_panel; }
.fd-tab:checked label { color: @fd_maroon; }
.fd-tab.fd-context label { color: #ffe4a8; }
.fd-tab.fd-context:checked label { color: #9a5b00; }
.fd-file { background: @fd_maroon_dark; }
.fd-file:hover { background: #4a0000; }

.fd-ribbon { background: @fd_panel; border-bottom: 1px solid @fd_line; padding: 3px 4px 1px 4px; }
.fd-group-label { color: #6f6262; font-size: 8.5pt; }
.fd-sep { background: @fd_line; min-width: 1px; margin: 3px 3px; }

.fd-rbtn, .fd-rbtn.toggle, menubutton.fd-rbtn > button {
  background: transparent; background-image: none; border: 1px solid transparent; box-shadow: none;
  border-radius: 3px; padding: 1px 4px; color: #262222; min-height: 0; min-width: 0; }
.fd-rbtn:hover { background: @fd_tint; border-color: @fd_tint2; }
.fd-rbtn:checked, .fd-rbtn.fd-on { background: @fd_tint2; border-color: #cf9f9f; }
.fd-rbtn:disabled label { color: #a8a0a0; }
.fd-rbtn label { color: #262222; }

.fd-swatch { padding: 0; min-width: 0; min-height: 0; border-radius: 0; border: 1px solid transparent;
  background: transparent; background-image: none; box-shadow: none; }
.fd-swatch:hover { border-color: @fd_maroon; }

.fd-workspace { background: #e7e0e0; }
.fd-ruler { background: #f6f2f2; }

.fd-status { background: #f3eded; border-top: 1px solid @fd_line; padding: 0 8px; min-height: 24px; }
.fd-status label { color: #3a3333; font-size: 9pt; }
.fd-status button { padding: 0 4px; min-height: 0; min-width: 0; background: transparent;
  background-image: none; border: none; box-shadow: none; }

.fd-layers { background: @fd_panel; border-left: 1px solid @fd_line; }
.fd-layers-title { font-weight: bold; color: @fd_maroon; padding: 6px 8px 4px 8px; }
.fd-layers list { background: @fd_panel; }
.fd-layers row { padding: 2px 4px; border-bottom: 1px solid #eee5e5; }
.fd-layers row:selected { background: @fd_tint2; }
.fd-layers row:selected label { color: #1c1818; }
.fd-layers scale highlight { background: @fd_maroon; }

scale.fd-accent highlight, .fd-accent progressbar progress { background: @fd_maroon; }
checkbutton.fd-check check:checked, radiobutton.fd-check radio:checked { background: @fd_maroon; color: #ffffff; border-color: @fd_maroon; }

.fd-backstage { background: @fd_maroon; }
.fd-primary { background: @fd_maroon; background-image: none; color: #ffffff; border-color: @fd_maroon_dark; }
.fd-primary label { color: #ffffff; }
.fd-primary:hover { background: #930d0d; }

menu menuitem:hover { background: @fd_tint2; color: #1c1818; }
menu menuitem:hover label { color: #1c1818; }
"""


def install():
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(screen, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
