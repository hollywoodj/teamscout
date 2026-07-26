' ============================================================
'  LD2L Mock Draft launcher
' ------------------------------------------------------------
'  Double-click to start the local practice auction. A console
'  window shows the board URL + status, and the draft board
'  opens in your browser automatically. The finalized captain
'  roster and budgets come directly from the LD2L teams page;
'  roles and removals still come from captains.json. Draft as
'  Hollywood against the AI captains; press Ctrl+C in the
'  console (or close the window) to stop. Targets save on exit.
'
'  For preseason testing with a hand-curated roster, run:
'  python ld2l_scout.py --mock --roster curated
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
           "Keep MockDraft.vbs in the LD2L Scout project folder.", _
           vbCritical, "LD2L Mock Draft"
    WScript.Quit 1
End If

' Set a friendly window title, launch the mock server in a visible
' console, and only keep the window open (pause) if Python exits with
' an error -- a clean Ctrl+C stop (exit 0) closes the window.
cmd = "cmd /c title LD2L Mock Draft & python ld2l_scout.py --mock --official-roster || pause"

' 1 = normal visible window, False = don't block this script.
shell.Run cmd, 1, False
