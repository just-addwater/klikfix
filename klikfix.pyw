# KlikFix is free software: you may redistribute and/or modify it under
# the GNU General Public License, version 3 or later, as published by the
# Free Software Foundation. There is NO WARRANTY. See the LICENSE file.
"""KlikFix: change how old Clickteam games start (window, full screen,
title bar, menu bar).

Play runs the game with the chosen options from a temporary copy and leaves
its files alone. Patch writes them into the game after backing it up.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import klikfix_core as core

APP_NAME = "KlikFix"
BACKUP_SUFFIX = ".original"
PLAY_TAG = " [KlikFix]"
MAX_RECENT = 10
TEMP_PLAY_DIR = os.path.join(tempfile.gettempdir(), APP_NAME)


# -- Settings (%APPDATA%\KlikFix\settings.json) -----------------------------

def _settings_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME, "settings.json")


def load_settings() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    for key in ("recent", "leftovers"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def save_settings(data: dict) -> None:
    path = _settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
    except OSError:
        pass  # settings are a convenience


def _is_play_copy(path: str) -> bool:
    """Only files KlikFix made for Play may ever be deleted by it."""
    name = os.path.basename(path)
    in_temp = os.path.normcase(os.path.dirname(os.path.abspath(path))) == \
        os.path.normcase(TEMP_PLAY_DIR)
    return PLAY_TAG in name or in_temp


# -- Drag and drop from Explorer (WM_DROPFILES) -----------------------------

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


def enable_drop(root: tk.Tk, on_files) -> None:
    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    user32.GetParent.restype = wt.HWND
    user32.GetParent.argtypes = [wt.HWND]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.CallWindowProcW.restype = _LRESULT
    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    shell32.DragQueryFileW.argtypes = [wt.HANDLE, wt.UINT, wt.LPWSTR, wt.UINT]
    shell32.DragFinish.argtypes = [wt.HANDLE]
    shell32.DragAcceptFiles.argtypes = [wt.HWND, wt.BOOL]

    root.update_idletasks()
    hwnd = user32.GetParent(root.winfo_id())
    dropped: list[list[str]] = []
    old = None

    def poll():
        while dropped:
            on_files(dropped.pop(0))
        root.after(150, poll)

    def proc(window, message, wparam, lparam):
        if message == WM_DROPFILES:
            names = []
            for index in range(shell32.DragQueryFileW(wparam, 0xFFFFFFFF,
                                                      None, 0)):
                size = shell32.DragQueryFileW(wparam, index, None, 0) + 1
                buffer = ctypes.create_unicode_buffer(size)
                shell32.DragQueryFileW(wparam, index, buffer, size)
                names.append(buffer.value)
            shell32.DragFinish(wparam)
            # Queue only: calling tkinter from here re-enters Tcl and crashes.
            dropped.append(names)
            return 0
        return user32.CallWindowProcW(old, window, message, wparam, lparam)

    callback = _WNDPROC(proc)
    root._drop_callback = callback  # must outlive the window
    old = user32.SetWindowLongPtrW(
        hwnd, GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p).value)
    shell32.DragAcceptFiles(hwnd, True)
    poll()


def _short(text: str, limit: int = 52) -> str:
    """Shorten a long path in the middle."""
    if len(text) <= limit:
        return text
    keep = (limit - 1) // 2
    return text[:keep] + "…" + text[-keep:]


def _resource(name: str) -> str:
    """A file beside the script, or inside the one-file build."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


# -- The window -------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = load_settings()
        self.game: core.Game | None = None
        self.original: dict = {}
        self._clean_leftovers()

        root.title(APP_NAME)
        try:
            root.iconbitmap(default=_resource("icon.ico"))
        except tk.TclError:
            pass
        root.resizable(False, False)
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        base = ("Segoe UI", 10)
        style.configure(".", font=base)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 12))
        style.configure("Hint.TLabel", foreground="#5f6368")
        style.configure("Big.TButton", font=("Segoe UI Semibold", 11),
                        padding=(18, 6))

        outer = ttk.Frame(root, padding=16)
        outer.grid(sticky="nsew")

        # Drop zone
        self.zone = tk.Canvas(outer, width=440, height=96, highlightthickness=0,
                              background="#f3f6fb", cursor="hand2")
        self.zone.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.zone.create_rectangle(3, 3, 437, 93, dash=(6, 4),
                                   outline="#8aa4c8", width=2)
        self.zone_text = self.zone.create_text(
            220, 36, text="Drop a game here", font=("Segoe UI Semibold", 12),
            fill="#2b4a73")
        self.zone.create_text(
            220, 64, text="or click to choose one", font=base, fill="#5f6368")
        self.zone.bind("<Button-1>", lambda _e: self.choose())

        buttons = ttk.Frame(outer)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Browse…", command=self.choose).pack(
            side="left")
        self.recent_button = ttk.Menubutton(buttons, text="Recent games")
        self.recent_menu = tk.Menu(self.recent_button, tearoff=False,
                                   postcommand=self._fill_recent)
        self.recent_button["menu"] = self.recent_menu
        self.recent_button.pack(side="right")

        # Game
        self.name_label = ttk.Label(outer, text="No game chosen yet",
                                    style="Title.TLabel")
        self.name_label.grid(row=2, column=0, columnspan=2, sticky="w",
                             pady=(16, 0))
        self.info_label = ttk.Label(outer, text="", style="Hint.TLabel",
                                    wraplength=440)
        self.info_label.grid(row=3, column=0, columnspan=2, sticky="w")

        # Options
        box = ttk.LabelFrame(outer, text=" How the game starts ", padding=10)
        box.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.vars: dict[str, tk.BooleanVar] = {}
        self.widgets: list[ttk.Widget] = []

        self.mode = tk.StringVar(value="window")
        row = ttk.Frame(box)
        row.pack(anchor="w")
        for value, text in (("window", "In a window"),
                            ("fullscreen", "Full screen")):
            radio = ttk.Radiobutton(row, text=text, value=value,
                                    variable=self.mode, command=self._changed)
            radio.pack(side="left", padx=(0, 18))
            self.widgets.append(radio)

        self.resolution_check = self._check(
            box, "resolution", "Change the screen resolution in full screen",
            indent=True)
        ttk.Separator(box).pack(fill="x", pady=8)
        self._check(box, "titlebar", "Show the title bar")
        self._check(box, "menubar", "Show the menu bar")
        self._check(box, "switch",
                    "Let players switch between window and full screen")
        self._check(box, "stretch", "Stretch the game to fill the window")

        status_row = ttk.Frame(outer)
        status_row.grid(row=5, column=0, columnspan=2, sticky="ew",
                        pady=(10, 0))
        self.status = ttk.Label(status_row, text="", style="Hint.TLabel")
        self.status.pack(side="left")
        self.reset_button = ttk.Button(status_row, text="Undo my changes",
                                       command=self.reset)
        self.reset_button.pack(side="right")

        # Actions: Patch sits far from Play so it isn't hit by mistake.
        actions = ttk.Frame(outer)
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.play_button = ttk.Button(actions, text="▶  Play",
                                      style="Big.TButton", command=self.play)
        self.play_button.pack(side="left")
        self.patch_button = ttk.Button(actions, text="Patch…",
                                       command=self.patch)
        self.patch_button.pack(side="right")

        self.restore_button = ttk.Button(
            outer, text="Restore the original", command=self.restore)
        self.restore_button.grid(row=7, column=0, columnspan=2, sticky="w",
                                 pady=(10, 0))
        self.restore_button.grid_remove()

        ttk.Label(outer, style="Hint.TLabel", wraplength=440, justify="left",
                  text="Play runs the game with these options and leaves its "
                       "files alone.  Patch saves them into the game itself "
                       "and keeps a copy of the original.").grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(12, 0))

        self._set_enabled(False)
        try:
            enable_drop(root, self.dropped)
        except Exception:  # noqa: BLE001 -- drag and drop is optional
            self.zone.itemconfigure(self.zone_text, text="Choose a game")

    # -- widgets and state ------------------------------------------------

    def _check(self, parent, key: str, text: str, indent: bool = False):
        var = tk.BooleanVar(value=False)
        self.vars[key] = var
        check = ttk.Checkbutton(parent, text=text, variable=var,
                                command=self._changed)
        check.pack(anchor="w", padx=(24 if indent else 0, 0), pady=2)
        self.widgets.append(check)
        return check

    def _set_enabled(self, on: bool) -> None:
        state = "!disabled" if on else "disabled"
        for widget in self.widgets + [self.play_button, self.patch_button,
                                      self.reset_button]:
            widget.state([state])
        if on:
            self._changed()

    def _choices(self) -> dict:
        choices = {key: var.get() for key, var in self.vars.items()}
        choices["fullscreen"] = self.mode.get() == "fullscreen"
        return choices

    def _show(self, options: dict) -> None:
        self.mode.set("fullscreen" if options["fullscreen"] else "window")
        for key, var in self.vars.items():
            var.set(options[key])

    def _changes(self) -> dict:
        """Only the options the user changed."""
        return {key: value for key, value in self._choices().items()
                if value != self.original.get(key)}

    def _changed(self) -> None:
        if not self.game:
            return
        full = self.mode.get() == "fullscreen"
        self.resolution_check.state(["!disabled" if full else "disabled"])
        if not full:
            self.vars["resolution"].set(False)  # it would force full screen
        if self._changes():
            self._status("You've changed some options.")
            self.patch_button.state(["!disabled"])
            self.reset_button.state(["!disabled"])
        else:
            self._status("These are the game's own options.")
            self.patch_button.state(["disabled"])
            self.reset_button.state(["disabled"])

    def _status(self, text: str) -> None:
        self.status.configure(text=text)

    # -- choosing a game --------------------------------------------------

    def choose(self) -> None:
        initial = None
        if self.settings["recent"]:
            initial = os.path.dirname(self.settings["recent"][0])
        path = filedialog.askopenfilename(
            parent=self.root, title="Choose a game", initialdir=initial,
            filetypes=[("Games", "*.exe;*.gam;*.cca"), ("All files", "*.*")])
        if path:
            self.open(os.path.normpath(path))

    def dropped(self, names: list[str]) -> None:
        if names:
            self.open(names[0])

    def _fill_recent(self) -> None:
        menu = self.recent_menu
        menu.delete(0, "end")
        recent = [p for p in self.settings["recent"]
                  if isinstance(p, str) and os.path.isfile(p)]
        if not recent:
            menu.add_command(label="(nothing yet)", state="disabled")
            return
        for path in recent:
            menu.add_command(
                label=f"{os.path.basename(path)}   —   {os.path.dirname(path)}",
                command=lambda p=path: self.open(p))
        menu.add_separator()
        menu.add_command(label="Clear this list", command=self._clear_recent)

    def _clear_recent(self) -> None:
        self.settings["recent"] = []
        save_settings(self.settings)

    def _remember(self, path: str) -> None:
        recent = [p for p in self.settings["recent"]
                  if os.path.normcase(str(p)) != os.path.normcase(path)]
        self.settings["recent"] = [path] + recent[:MAX_RECENT - 1]
        save_settings(self.settings)

    def open(self, path: str) -> None:
        try:
            game = core.load(path)
        except core.NotAGame as error:
            messagebox.showwarning(APP_NAME, f"{os.path.basename(path)}\n\n"
                                   f"{error}", parent=self.root)
            return
        except OSError as error:
            messagebox.showerror(APP_NAME, "Couldn't open that file.\n\n"
                                 f"{error.strerror or error}", parent=self.root)
            return
        except Exception:  # noqa: BLE001 -- any malformed file
            messagebox.showwarning(APP_NAME, f"{os.path.basename(path)}\n\n"
                                   "Couldn't read this game.", parent=self.root)
            return
        self.game = game
        self.original = core.read_options(game.flags)
        self._show(self.original)
        self.name_label.configure(text=os.path.basename(path))
        self.info_label.configure(text=f"{game.product_name} game  ·  "
                                       f"{_short(os.path.dirname(path))}")
        kind = os.path.splitext(game.path)[1].lstrip(".").upper() or "file"
        self.patch_button.configure(text=f"Patch {kind}…")
        self.restore_button.configure(text=f"Restore the original {kind}")
        self.zone.itemconfigure(self.zone_text, text="Drop another game here")
        self._remember(path)
        self._set_enabled(True)
        self._refresh_restore()

    def _backup_path(self) -> str:
        return self.game.path + BACKUP_SUFFIX

    def _refresh_restore(self) -> None:
        if self.game and os.path.isfile(self._backup_path()):
            self.restore_button.grid()
        else:
            self.restore_button.grid_remove()

    def reset(self) -> None:
        if self.game:
            self._show(self.original)
            self._changed()

    def _patched_bytes(self) -> bytes | None:
        try:
            flags = core.apply_options(self.game.flags, self._changes())
            return core.with_flags(self.game, flags)
        except Exception as error:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Couldn't apply the options.\n\n"
                                 f"{error}", parent=self.root)
            return None

    # -- Play -------------------------------------------------------------

    def play(self) -> None:
        game = self.game
        if not game.exe:
            messagebox.showinfo(
                APP_NAME, "There's no game program (.exe) beside this file to "
                "run.  Choose the game's .exe instead, or use Patch.",
                parent=self.root)
            return
        folder = os.path.dirname(game.exe)
        if not self._changes():
            self._launch(game.exe, folder, [])
            return
        patched = self._patched_bytes()
        if patched is None:
            return
        # Copy the runtime, plus the data file for a 1996 game. A 1996
        # runtime finds its data by its own name, so both copies share it.
        sources = [(game.exe, patched if game.path == game.exe else None)]
        if game.path != game.exe:
            sources.append((game.path, patched))
        stem = os.path.splitext(os.path.basename(game.exe))[0]
        # Prefer the game's folder, so it finds its files and saves where it
        # always does; fall back to a temp folder if that is read-only.
        for place, name in ((folder, stem + PLAY_TAG), (TEMP_PLAY_DIR, stem)):
            copies = []
            try:
                os.makedirs(place, exist_ok=True)
                for source, data in sources:
                    copy = os.path.join(place, name
                                        + os.path.splitext(source)[1])
                    self._delete_copy(copy)
                    copies.append(copy)
                    self.settings["leftovers"].append(copy)
                    if data is None:
                        shutil.copyfile(source, copy)
                    else:
                        with open(copy, "wb") as handle:
                            handle.write(data)
            except OSError:
                for copy in copies:
                    self._delete_copy(copy)
                continue
            save_settings(self.settings)
            self._launch(copies[0], folder, copies)
            return
        messagebox.showerror(APP_NAME, "Couldn't prepare the game to play.",
                             parent=self.root)

    def _launch(self, exe: str, folder: str, cleanup: list[str]) -> None:
        try:
            process = subprocess.Popen([exe], cwd=folder)
        except OSError as error:
            messagebox.showerror(APP_NAME, "Couldn't start the game.\n\n"
                                 f"{error.strerror or error}", parent=self.root)
            for copy in cleanup:
                self._delete_copy(copy)
            return
        self._status("The game is running.")
        if cleanup:
            self._wait_and_delete(process, cleanup)

    def _wait_and_delete(self, process, copies: list[str]) -> None:
        # Polled from Tk's loop: tkinter isn't thread-safe.
        if process.poll() is None:
            self.root.after(1000, self._wait_and_delete, process, copies)
        else:
            for copy in copies:
                self.root.after(1500, self._delete_copy, copy)

    def _delete_copy(self, copy: str) -> None:
        if not isinstance(copy, str) or not _is_play_copy(copy):
            return
        try:
            os.remove(copy)
        except FileNotFoundError:
            pass
        except OSError:
            return  # still in use; retried next start
        if copy in self.settings["leftovers"]:
            self.settings["leftovers"].remove(copy)
            save_settings(self.settings)

    def _clean_leftovers(self) -> None:
        for copy in list(self.settings["leftovers"]):
            if isinstance(copy, str) and _is_play_copy(copy):
                self._delete_copy(copy)
            else:
                self.settings["leftovers"].remove(copy)

    # -- Patch ------------------------------------------------------------

    def patch(self) -> None:
        game = self.game
        name = os.path.basename(game.path)
        backup = self._backup_path()
        have_backup = os.path.isfile(backup)
        note = (f"The original is already saved as\n{os.path.basename(backup)}"
                if have_backup else "A copy of the original will be saved "
                f"beside it as\n{os.path.basename(backup)}")
        if not messagebox.askokcancel(
                APP_NAME, f"Save these options into {name}?\n\n{note}",
                parent=self.root):
            return
        data = self._patched_bytes()
        if data is None:
            return
        temp = game.path + ".klikfix-tmp"
        try:
            if not have_backup:
                shutil.copy2(game.path, backup)
            with open(temp, "wb") as handle:
                handle.write(data)
            os.replace(temp, game.path)
        except OSError as error:
            try:
                os.remove(temp)
            except OSError:
                pass
            if isinstance(error, PermissionError):
                self._offer_copy(data)
            else:
                messagebox.showerror(
                    APP_NAME, f"Couldn't change {name}.\n\n"
                    f"{error.strerror or error}\n\nIf the game is running, "
                    "close it and try again.", parent=self.root)
            return
        self.open(game.path)
        self._status(f"Saved into {name}.")

    def _offer_copy(self, data: bytes) -> None:
        name = os.path.basename(self.game.path)
        extension = os.path.splitext(name)[1] or ".exe"
        if not messagebox.askyesno(
                APP_NAME, f"Windows won't let KlikFix change {name} where it "
                "is (for example, inside Program Files).\n\nSave a patched "
                "copy somewhere else instead?", parent=self.root):
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save a patched copy", initialfile=name,
            defaultextension=extension,
            filetypes=[("Game files", f"*{extension}")])
        if not path:
            return
        try:
            with open(path, "wb") as handle:
                handle.write(data)
        except OSError as error:
            messagebox.showerror(APP_NAME, "Couldn't save the copy.\n\n"
                                 f"{error.strerror or error}", parent=self.root)
            return
        messagebox.showinfo(
            APP_NAME, "Saved. If the game needs files from its own folder, "
            "put the copy in that folder too.", parent=self.root)

    def restore(self) -> None:
        game = self.game
        name = os.path.basename(game.path)
        if not messagebox.askokcancel(
                APP_NAME, f"Put the original {name} back?\n\nAny options "
                "saved with Patch will be undone.", parent=self.root):
            return
        try:
            os.replace(self._backup_path(), game.path)
        except OSError as error:
            messagebox.showerror(
                APP_NAME, f"Couldn't restore {name}.\n\n"
                f"{error.strerror or error}\n\nIf the game is running, "
                "close it and try again.", parent=self.root)
            return
        self.open(game.path)
        self._status(f"The original {name} is back.")


def main() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    app = App(root)
    for arg in sys.argv[1:]:
        if os.path.isfile(arg):
            app.open(os.path.abspath(arg))
            break
    root.mainloop()


if __name__ == "__main__":
    main()
