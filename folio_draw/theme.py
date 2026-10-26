"""Maroon Folio theme."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

MAROON = "#800000"
MAROON_DARK = "#5c0000"

CSS = b"""
/* Folio suite chrome (see the Folio Suite Ribbon Spec): neutral greys, maroon accent. */
@define-color fd_maroon #800000;
@define-color fd_maroon_dark #5c0000;
@define-color fd_tint #f7ebeb;
@define-color fd_tint2 #ecd3d3;
@define-color fd_check_border #cf9f9f;
@define-color fd_panel #f3f3f3;
@define-color fd_line #d6d6d6;
@define-color fd_text #262626;
@define-color fd_caption #666666;
@define-color fd_hover #e1e1e1;
@define-color fd_press #c8c8c8;

/* chrome typeface: the same stack as the rest of the suite */
.fd-header, .fd-tabs, .fd-ribbon, .fd-status, .fd-backstage, .fd-layers, popover, menu, .fd-dialog {
  font-family: "Segoe UI", "Noto Sans", "Open Sans", "Ubuntu", sans-serif;
  font-size: 9pt;
}

/* no frame around the window: the title bar is the top edge */
decoration, window.csd decoration, .solid-csd decoration, window.solid-csd decoration {
  border: none; box-shadow: none; border-radius: 0; margin: 0; padding: 0; }
window.csd, window.solid-csd, window.background.csd { border-radius: 0; padding: 0; margin: 0; }

/* ---------- title bar: 40 px ---------- */
headerbar.fd-header, .fd-header {
  background: @fd_maroon; background-image: none; color: #ffffff;
  border: none; box-shadow: none; min-height: 40px; padding: 0 0 0 4px; border-radius: 0;
}
.fd-header .title, .fd-header label { color: #ffffff; font-size: 9pt; }
.fd-header button { color: #ffffff; background: transparent; background-image: none;
  border: none; box-shadow: none; border-radius: 0; padding: 0 4px; min-height: 28px; min-width: 30px; }
.fd-header button:hover { background: rgba(255,255,255,0.15); }
.fd-header button:active { background: rgba(255,255,255,0.25); }
.fd-header button:disabled { opacity: 0.45; }
.fd-header button.titlebutton { min-width: 46px; min-height: 40px; padding: 0; }
.fd-header button.titlebutton.close:hover { background: #e81123; }
.fd-header button.titlebutton image { color: #ffffff; }
.fd-header entry.fd-search {
  background: rgba(255,255,255,0.18); color: #ffffff; border: 1px solid rgba(255,255,255,0.25);
  border-radius: 4px; min-height: 24px; padding: 0 8px; box-shadow: none; caret-color: #ffffff;
}
.fd-header entry.fd-search image { color: #ffffff; }
.fd-header entry.fd-search:focus { background: #ffffff; color: #222222; caret-color: #222222; }
.fd-header entry.fd-search:focus image { color: #444444; }

/* ---------- ribbon tabs: 34 px ---------- */
.fd-tabs { background: @fd_panel; padding: 0 6px; min-height: 34px; }
.fd-tab { color: @fd_text; background: transparent; background-image: none; border: none;
  border-radius: 0; box-shadow: none; padding: 6px 10px 4px 10px; min-height: 0;
  border-bottom: 3px solid transparent; font-size: 9.5pt; }
.fd-tab label { color: @fd_text; font-size: 9.5pt; }
.fd-tab:hover { background: @fd_hover; }
.fd-tab:checked { background: transparent; border-bottom: 3px solid @fd_maroon; }
.fd-tab:checked label { color: @fd_maroon; font-weight: bold; }
.fd-tab.fd-context label { color: #8a4a00; }
.fd-tab.fd-context:checked label { color: #8a4a00; }

/* ---------- ribbon body: 96 px + 1 px line ---------- */
.fd-ribbon { background: @fd_panel; border-bottom: 1px solid @fd_line; padding: 2px 4px 0 4px; min-height: 93px; }
.fd-group-label { color: @fd_caption; font-size: 0.85em; }
.fd-sep { background: @fd_line; min-width: 1px; margin: 6px 2px; }

.fd-rbtn, .fd-rbtn.toggle, menubutton.fd-rbtn > button {
  background: transparent; background-image: none; border: 1px solid transparent; box-shadow: none;
  border-radius: 3px; padding: 1px 3px; color: @fd_text; min-height: 0; min-width: 0; }
.fd-rbtn:hover { background: @fd_hover; border-color: @fd_hover; }
.fd-rbtn:active { background: @fd_press; }
.fd-rbtn:checked, .fd-rbtn.fd-on { background: @fd_tint2; border-color: @fd_check_border; }
.fd-rbtn:disabled label { color: #a8a8a8; }
.fd-rbtn label { color: @fd_text; font-size: 0.92em; }

.fd-swatch { padding: 0; min-width: 0; min-height: 0; border-radius: 0; border: 1px solid transparent;
  background: transparent; background-image: none; box-shadow: none; }
.fd-swatch:hover { border-color: @fd_maroon; }

.fd-workspace { background: #e6e6e6; }
.fd-ruler { background: #f6f6f6; }

/* ---------- status bar: 24 px + 1 px line ---------- */
.fd-status { background: @fd_panel; border-top: 1px solid @fd_line; padding: 0 8px; min-height: 24px; }
.fd-status label { color: #444444; font-size: 0.88em; }
.fd-status button { padding: 0 4px; min-height: 0; min-width: 0; background: transparent;
  background-image: none; border: none; box-shadow: none; border-radius: 2px; color: #444444; }
.fd-status button:hover { background: @fd_hover; }

.fd-layers { background: #ffffff; border-left: 1px solid @fd_line; }
.fd-layers-title { font-weight: bold; color: @fd_maroon; padding: 6px 8px 4px 8px; }
.fd-layers list { background: #ffffff; }
.fd-layers row { padding: 2px 4px; border-bottom: 1px solid #ececec; }
.fd-layers row:selected { background: @fd_tint2; }
.fd-layers row:selected label { color: #1c1818; }
.fd-layers scale highlight { background: @fd_maroon; }

scale.fd-accent highlight, .fd-accent progressbar progress { background: @fd_maroon; }
checkbutton.fd-check check:checked, radiobutton.fd-check radio:checked { background: @fd_maroon; color: #ffffff; border-color: @fd_maroon; }

/* ---------- KeyTips ---------- */
.fd-keytip { background: #3a3a3a; color: #ffffff; font-weight: bold; font-size: 0.8em;
  padding: 0 4px; border-radius: 2px; border: 1px solid #222222; }
popover.fd-keytip-pop { padding: 0; background: transparent; border: none; box-shadow: none; }

/* ---------- File view ---------- */
.fd-backstage { background: #ffffff; }
.fd-bs-nav { background: @fd_maroon; padding-top: 6px; padding-bottom: 8px; }
.fd-bs-navbtn { background: transparent; background-image: none; color: #ffffff; border: none; box-shadow: none;
  border-radius: 0; padding: 9px 22px; min-height: 22px; font-size: 1.04em; }
.fd-bs-navbtn label, .fd-bs-navbtn image { color: #ffffff; }
.fd-bs-navbtn:hover { background: rgba(255,255,255,0.14); }
.fd-bs-navbtn.active { background: rgba(0,0,0,0.25); }
.fd-bs-navbtn.back { padding: 12px 18px; }
.fd-bs-sep { background: rgba(255,255,255,0.30); min-height: 1px; margin: 4px 20px; }
.fd-bs-title { font-size: 22pt; font-weight: 300; color: #262626; }
.fd-bs-sub { font-size: 15pt; font-weight: 300; color: #262626; }
.fd-bs-tile, .fd-bs-place, .fd-bs-button { background: transparent; background-image: none; border: 1px solid transparent;
  box-shadow: none; border-radius: 0; padding: 6px; color: #262626; }
.fd-bs-tile:hover, .fd-bs-place:hover { background: @fd_tint; border-color: @fd_check_border; }
.fd-bs-button { border: 1px solid #c8c8c8; border-radius: 2px; padding: 8px 14px; background: #ffffff; }
.fd-bs-button:hover { background: @fd_tint; border-color: @fd_check_border; }
.fd-bs-recent row { padding: 2px; }
.fd-bs-recent row:hover { background: @fd_tint; }

/* ---------- dialogs ---------- */
.fd-primary { background: @fd_maroon; background-image: none; color: #ffffff; border-color: @fd_maroon_dark; }
.fd-primary label { color: #ffffff; }
.fd-primary:hover { background: #930d0d; }

menu menuitem:hover { background: @fd_tint2; color: #1c1818; }
menu menuitem:hover label { color: #1c1818; }
"""


# Dark mode (the desktop is set to dark): the chrome goes dark like Paint's; the picture keeps its colours.
DARK_CSS = b"""
@define-color fd_tint #3a2a2a;
@define-color fd_tint2 #5a2e2e;
@define-color fd_check_border #8f4f4f;
@define-color fd_panel #2b2b2b;
@define-color fd_line #404040;
@define-color fd_text #f0f0f0;
@define-color fd_caption #b0b0b0;
@define-color fd_hover #3d3d3d;
@define-color fd_press #4a4a4a;

.fd-tab:checked { border-bottom-color: #d06060; }
.fd-tab:checked label { color: #f0a8a8; }
.fd-tab.fd-context label, .fd-tab.fd-context:checked label { color: #f0b060; }
.fd-rbtn:disabled label { color: #707070; }
.fd-workspace { background: #1f1f1f; }
.fd-ruler { background: #2b2b2b; }
.fd-status label, .fd-status button { color: #d0d0d0; }
.fd-layers, .fd-layers list { background: #242424; }
.fd-layers row { border-bottom-color: #333333; }
.fd-layers row label, .fd-layers label { color: #f0f0f0; }
.fd-layers label:disabled { color: #777777; }
.fd-layers label.fd-layers-title { color: #f0a8a8; }
.fd-layers row:selected label { color: #ffffff; }

.fd-keytip { background: #f0f0f0; color: #1f1f1f; border-color: #ffffff; }
.fd-backstage { background: #1f1f1f; }
.fd-bs-title, .fd-bs-sub, .fd-bs-tile, .fd-bs-place, .fd-bs-button { color: #f0f0f0; }
.fd-bs-tile label, .fd-bs-place label, .fd-bs-button label { color: #f0f0f0; }
.fd-bs-button { background: #2b2b2b; border-color: #555555; }
menu menuitem:hover, menu menuitem:hover label { color: #ffffff; }
popover, popover.background { background-color: #2b2b2b; color: #f0f0f0; }
popover label { color: #f0f0f0; }
"""

_dark_provider = None


def install():
    global _dark_provider
    from . import appearance
    if _dark_provider is not None:
        return   # once per process
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    _dark_provider = Gtk.CssProvider()
    _dark_provider.load_from_data(DARK_CSS)
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    Gtk.StyleContext.add_provider_for_screen(screen, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    appearance.apply_initial()
    _apply(appearance.is_dark())
    appearance.on_change(_apply)


def _apply(dark):
    screen = Gdk.Screen.get_default()
    if screen is None or _dark_provider is None:
        return
    if dark:
        Gtk.StyleContext.add_provider_for_screen(screen, _dark_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    else:
        Gtk.StyleContext.remove_provider_for_screen(screen, _dark_provider)
    # cairo-drawn chrome (icons, rulers, the workspace) repaints in the new colours
    for w in Gtk.Window.list_toplevels():
        w.queue_draw()


def chrome(name):
    """Colours of chrome painted with cairo, for the current mode."""
    from . import appearance
    dark = appearance.is_dark()
    return {
        "workspace": (0.122, 0.122, 0.122) if dark else (0.902, 0.902, 0.902),
        "ruler": (0.169, 0.169, 0.169) if dark else (0.965, 0.965, 0.965),
        "ruler_line": (0.33, 0.30, 0.30) if dark else (0.78, 0.72, 0.72),
        "ruler_text": (0.80, 0.78, 0.78) if dark else (0.35, 0.3, 0.3),
        "accent_text": "#f0a8a8" if dark else "#800000",
    }[name]
