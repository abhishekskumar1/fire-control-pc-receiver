# Build Instructions

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- pip
- PyInstaller
- Inno Setup

## Setup

Create virtual environment:

```powershell
python -m venv venv
```

Activate virtual environment:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\venv\Scripts\Activate.ps1
```

Install packages:

```powershell
pip install -r requirements.txt
```

## Build EXE

```powershell
pyinstaller --onedir --noconsole --name "Fire Control" --icon "fire_control.ico" --add-data "fire_control.ico;." app.py
```

Output:

```text
dist\Fire Control\Fire Control.exe
```

## Build Installer

Open Inno Setup and compile:

```text
FireControlSetup.iss
```

Output:

```text
FireControlSetup_x64.exe
```