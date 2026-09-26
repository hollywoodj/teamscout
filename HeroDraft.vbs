' ============================================================
'  LD2L Hero Draft launcher
' ------------------------------------------------------------
'  Double-click to start Captains Mode pick/ban practice. A
'  console window shows the board URL + status, and the war-room
'  board opens in your browser automatically. Build both rosters,
'  flip for first pick, and draft against the bot (current
'  Captains Mode order; the patch meta comes from
'  scout\meta_heroes.json). Press Ctrl+C in the console (or
'  close the window) to stop. Rosters are saved to
'  herodraft_teams.json between runs.
'
'  The board runs on http://localhost:8323/ so it can run at the
'  same time as the mock auction (port 8322).
' ============================================================

Option Explicit

Dim fso, shell, here, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' Run from this script's own folder so ld2l_scout.py is found
' regardless of where the launcher is invoked from.
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here

If Not fso.FileExists(fso.BuildPath(here, "ld2l_scout.py")) Then
    MsgBox "Could not find ld2l_scout.py next to this launcher." & vbCrLf & _
           "Keep HeroDraft.vbs in the LD2L Scout project folder.", _
           vbCritical, "LD2L Hero Draft"
    WScript.Quit 1
End If

' Set a friendly window title, launch the draft server in a visible
' console, and only keep the window open (pause) if Python exits with
' an error -- a clean Ctrl+C stop (exit 0) closes the window.
cmd = "cmd /c title LD2L Hero Draft & python ld2l_scout.py --herodraft || pause"

' 1 = normal visible window, False = don't block this script.
shell.Run cmd, 1, False
