; AGPL-3.0-only. Generated into the build workspace by tools/windows/build-windows.py.
#define Version "@VERSION@"

[Setup]
AppId={{6C1D4F7E-3B52-4E0A-9A47-ED6E100A1A10}
AppName=EdgeLoop AI
AppVersion={#Version}
AppVerName=EdgeLoop AI {#Version}
AppPublisher=EdgeLoop AI fork (Prunebrother)
AppPublisherURL=https://github.com/Prunebrother/edgeloop-ai
AppSupportURL=https://github.com/Prunebrother/edgeloop-ai/issues
VersionInfoVersion=@NUMERIC_VERSION@
DefaultDirName={localappdata}\Programs\EdgeLoop AI
DefaultGroupName=EdgeLoop AI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputBaseFilename=EdgeLoop-AI-Setup-{#Version}
SetupIconFile=edgeloop-ai.ico
UninstallDisplayIcon={app}\edgeloop-ai.ico
UninstallDisplayName=EdgeLoop AI
LicenseFile=LICENSE.txt
InfoBeforeFile=setup-notes.txt
ExtraDiskSpaceRequired=@EXTRA_SPACE@
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "setup-python\*"; DestDir: "{tmp}\setup-python"; Flags: dontcopy recursesubdirs createallsubdirs
Source: "install_windows.py"; DestDir: "{tmp}"; Flags: dontcopy
Source: "parts.json"; DestDir: "{tmp}"; Flags: dontcopy
Source: "parts.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "edgeloop-ai.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup-notes.txt"; DestDir: "{app}"; DestName: "README.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\EdgeLoop AI"; Filename: "{app}\{#Version}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\{#Version}\tools\windows\edgeloop_ai_windows.py"" start"; WorkingDir: "{app}\{#Version}"; IconFilename: "{app}\edgeloop-ai.ico"; Comment: "Start local EdgeLoop AI and open it in the browser"
Name: "{autoprograms}\Stop EdgeLoop AI"; Filename: "{app}\{#Version}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\{#Version}\tools\windows\edgeloop_ai_windows.py"" stop"; WorkingDir: "{app}\{#Version}"; IconFilename: "{app}\edgeloop-ai.ico"; Comment: "Stop the web server, AI observer and Ollama. End hardware sessions first."
Name: "{autodesktop}\EdgeLoop AI"; Filename: "{app}\{#Version}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\{#Version}\tools\windows\edgeloop_ai_windows.py"" start"; WorkingDir: "{app}\{#Version}"; IconFilename: "{app}\edgeloop-ai.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Version}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\{#Version}\tools\windows\edgeloop_ai_windows.py"" start"; WorkingDir: "{app}\{#Version}"; Description: "Start EdgeLoop AI now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\{#Version}\.venv\Scripts\python.exe"; Parameters: """{app}\{#Version}\tools\windows\edgeloop_ai_windows.py"" stop --quiet"; WorkingDir: "{app}\{#Version}"; Flags: runhidden waituntilterminated; RunOnceId: "StopEdgeLoopAI"

[UninstallDelete]
; The bundle is extracted by setup, not copied by it, so remove it explicitly. User data is kept.
Type: filesandordirs; Name: "{app}\{#Version}"
Type: filesandordirs; Name: "{app}\{#Version}.previous"
Type: filesandordirs; Name: "{app}\{#Version}.incoming"
Type: filesandordirs; Name: "{app}\{#Version}.retired"
Type: filesandordirs; Name: "{localappdata}\EdgeLoop AI\downloads"
Type: filesandordirs; Name: "{localappdata}\EdgeLoop AI\runtime"
Type: dirifempty; Name: "{app}"

[Code]
function Quote(S: String): String;
begin
  Result := '"' + S + '"';
end;

function InstallerParams: String;
begin
  Result := '-I -X utf8 ' + Quote(ExpandConstant('{tmp}\install_windows.py')) +
    ' --manifest ' + Quote(ExpandConstant('{tmp}\parts.json')) +
    ' --dest ' + Quote(ExpandConstant('{app}\{#Version}')) +
    ' --cache ' + Quote(ExpandConstant('{localappdata}\EdgeLoop AI\downloads')) +
    ' --offline ' + Quote(ExpandConstant('{src}')) +
    ' --data ' + Quote(ExpandConstant('{localappdata}\EdgeLoop AI\data')) +
    ' --log ' + Quote(ExpandConstant('{localappdata}\EdgeLoop AI\logs\setup.log'));
end;

// Backups and downloads are retained until setup has installed its integration files.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
  Python, Params: String;
begin
  Result := '';
  ExtractTemporaryFiles('{tmp}\setup-python\*');
  ExtractTemporaryFile('install_windows.py');
  ExtractTemporaryFile('parts.json');
  Python := ExpandConstant('{tmp}\setup-python\python.exe');
  Params := InstallerParams;
  if not Exec(Python, Params, ExpandConstant('{tmp}'), SW_SHOW, ewWaitUntilTerminated, Code) then
    Result := 'Setup could not start its installer: ' + SysErrorMessage(Code)
  else if Code <> 0 then
    Result := 'EdgeLoop AI could not be installed. The reason is in ' +
      ExpandConstant('{localappdata}\EdgeLoop AI\logs\setup.log') +
      '. Finished downloads are kept; run setup again to resume.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Python, Params: String;
begin
  if CurStep = ssDone then begin
    Python := ExpandConstant('{tmp}\setup-python\python.exe');
    Params := InstallerParams + ' --finalize';
    if not Exec(Python, Params, ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, Code) then
      Log('Could not start cleanup; previous installation files and downloads were kept.')
    else if Code <> 0 then
      Log('Cleanup incomplete; see setup.log. Installation succeeded; leftover files can be cleaned up by the next setup.');
  end;
end;
