# KlikFix

Make old Clickteam games start the way you want: in a window instead of full
screen, with or without the title bar or menu bar.

Works with games made in:

- Multimedia Fusion 1.0 and 1.5
- The Games Factory, Click & Create and MMF Express (new, less tested)

## Use it

1. Drop a game's `.exe` on the window, or click the box / **Browse…**, or pick
   from **Recent games**. You can also drop a game onto `KlikFix.exe`.
2. Choose how it should start.
3. Press:
   - **Play**: runs the game with your choices. The game's files are not
     changed. A temporary copy runs from the game's folder and is deleted when
     the game closes.
   - **Patch**: saves your choices into the game so it always starts that
     way. The original is kept beside it as `<file>.original`, and
     **Restore the original** puts it back.

For Multimedia Fusion games, Patch changes the `.exe`. For Games Factory and
Click & Create games it changes the `.gam` / `.cca` beside it.

## Good to know

- Some games switch to full screen from their own events. KlikFix changes how
  a game *starts*, so those may still go full screen later.
- Games in Program Files can't be patched in place; KlikFix offers to save a
  patched copy elsewhere.
- Multimedia Fusion 2 and Klik & Play games aren't supported yet.
- Settings (the recent list) live in `%APPDATA%\KlikFix`.

## Antivirus warnings

`KlikFix.exe` is an unsigned PyInstaller build, so Windows SmartScreen and
some antivirus programs may warn about it. That's common for PyInstaller apps.
KlikFix makes no network connections, needs no admin rights, and only writes
the files described above. You can run it from source instead (below).

## Run or build from source

Needs Python 3.10+ on Windows. No other packages are needed to run it.

```bat
py -3 klikfix.pyw
```

To build `dist\KlikFix.exe`:

```bat
py -3 -m pip install pyinstaller
build.bat
```

`make_icon.py` redraws `icon.ico` (needs `pip install pillow`).

## Credits

The 1996 file layout follows Valley Bell's CExtract format notes.

## Licence

KlikFix is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the Licence, or (at your option)
any later version. It comes with **no warranty**. The full text is in
[LICENSE](LICENSE).
