# WB-Streamer Manager
WB-Streamer Manager is a centralized supervisor and multi-instance orchestrator designed for [WestBroadcast Streamer](https://github.com/LucasGallone/WestBroadcast-Streamer). It allows you to manage, control, and monitor multiple WestBroadcast Streamer instances running on the same host machine from a single, unified, and secure web interface.
<br>
<br>
Built for radio stations, broadcast engineers, or multi-stream environments operating several audio decoders on one computer, WB-Streamer Manager eliminates the need to manually open and track each instance individually.
<br>
<br>
Entirely open source, this tool is based on a Python backend (Flask + Tkinter) and connects directly to active instances via Socket.IO for real-time telemetry without overloading the supervisor.
<br>
<br>
WB-Streamer Manager runs as a portable installation via a dedicated launcher script. Running instances remain completely autonomous: closing the Manager will not interrupt ongoing audio broadcasts.
- - -
<b>⚠️ For now, WB-Streamer Manager is designed and tested primarily for Windows (10 and 11).</b>
<br>
<br>
Although process management includes cross-platform compatibility logic, the host control window relies on a graphical desktop environment (Tkinter) and further testing is required on Linux.
<br>
Any feedback regarding other operating systems is welcome!

## ⚡ What this tool offers
• **Centralized Multi-Instance Control**: Add, edit, remove, start, or stop individual WestBroadcast Streamer instances, or control all of them at once using the **Start All** and **Stop All** actions.
<br>
<br>
• **Automatic Startup & Process Tracking**: Configure per-instance **Autostart** so your decoders launch automatically when the Manager starts. The supervisor also automatically detects and re-attaches to already-running instances (by listening port or process path) and cleanly terminates full process trees (including `ffmpeg` and `ffprobe` child processes) when stopping an instance.
<br>
<br>
• **Real-Time Broadcast Monitoring**:
  - Global alert banner whenever any running instance switches to a backup audio source.
  - Live status of all 3 sources (**Main**, **Backup 1**, **Backup 2**) with active playback indicator and audio codec display.
  - Real-time Left/Right audio VU meters (`-60 dB` to `0+ dB`), configured output device, and output gain.
  - Live **Now Playing** metadata and per-instance uptime.
  - Real-time **UECP (RDS)** link status, frame counters, and CRC error monitoring (when enabled on an instance).


• **Thresholds, Alerts & System Telemetry**: View configured silence/connection-loss/recovery thresholds, per-source SMTP email alert status, forced selection mode badges (`FORCED`), and optional per-instance **CPU** and **RAM** usage monitoring.
<br>
<br>
• **Easy Instance Access**: One-click **Access the interface** button for every active instance.
<br>
<br>
• **Security & Administration**: Login-protected web interface with brute-force protection (90-second lockout after 3 failed attempts), HTTPOnly session cookies, CSRF protection, customizable Manager instance name (with optional hiding on the login page), event/authentication logs (filtering, pagination, text export), and JSON configuration backup/restore (`manager_config.json`).

## 💬 Available languages
WB-Streamer Manager is available in **English** and **French**.
<br>
There are currently no plans to add other languages, in order to ensure the quality of the translation.
<br>
<br>
If you would like to contribute a translation for a language **you are a native speaker of**, please feel free to do so.
<br>
Any contribution is appreciated and welcome.

## ⚙️ 1. Installation instructions for Windows
-> Download the repository files (or clone the repository) and extract them into a folder of your choice.
<br>
<br>
-> Install **Python 3.10 or newer** on your computer from the official website [by clicking here.](https://www.python.org/downloads/)
<br>
<b>IMPORTANT: When installing Python, make sure to check the "Add Python to PATH" box and keep the default "tcl/tk and IDLE" option enabled (required for Tkinter), otherwise the Manager will not work properly!</b>
<br>
<br>
-> Ideally, restart your computer after installing Python.
<br>
<br>
-> Open the folder containing the Manager files and run `Launcher.bat`.
<br>
When started for the first time, the script checks your Python version and automatically installs the required dependencies (with pinned major versions to prevent future breaking updates). This may take a few moments.
<br>
<br>
-> Once ready, a small desktop window (**WB-Streamer Manager**) will open, displaying the active port, the number of currently active instances, your machine's local IP address, and a quick-access button to open the web interface.
<br>
Be sure to keep this window and its terminal open on the host machine, otherwise the Manager web interface and supervision will stop (running WestBroadcast Streamer instances will continue operating independently).

## ⚙️ 2. Configuration
Configure the Manager and declare your instances via the web interface.
<br>
• Default port: **`8000`**
<br>
• Default credentials: **`admin` / `admin`**
<br>
*(Changing the default credentials on first use is STRONGLY recommended to prevent unauthorized access!)*
<br>
<br>
To add an instance, click **+ Add Instance**, specify the local folder path of an existing WestBroadcast Streamer installation, enter a display name (or click **Automatic naming** to fetch it from the instance's `config.json`), and optionally enable **Autostart**.
<br>
<b>Note:</b> WB-Streamer Manager can only control WestBroadcast Streamer instances located on the same host machine.

## 🚀 3. Starting the Manager after the initial setup
For subsequent startups, simply run `Launcher.bat`.
<br>
At each startup, the script verifies that Python 3.10+, Tkinter, and compatible versions of all required packages are present (without triggering unintended updates), then launches `manager.py`.

## 💡 Troubleshooting
If you encounter any issues with WB-Streamer Manager, please make sure:
<br>
• Python 3.10 or newer is installed and properly added to the Windows `PATH`.
<br>
• Each added instance folder contains a valid `app.py` (and `config.json` for port/name detection) from **WestBroadcast Streamer**.
<br>
• Firewall rules allow incoming TCP connections on the Manager port (`8000` by default) as well as on each instance port (required for remote access and live Socket.IO monitoring).
<br>
<br>
If the problem persists, feel free to open an **Issue** on GitHub with as much detail as possible.

## ⚖️ Legal Notices and Licenses

### WB-Streamer Manager
This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**.
<br>
Please refer to the `LICENSE` file included in this repository for full terms and conditions.
- - -
### Python Dependencies
This project relies on the following third-party Python packages, checked and installed by `Launcher.bat`:
<br>
<br>
• **Flask**: BSD-3-Clause License (Copyright Pallets).
<br>
• **Werkzeug**: BSD-3-Clause License (Copyright Pallets).
<br>
• **psutil**: BSD-3-Clause License (Copyright Giampaolo Rodola).
<br>
<br>
Transitive dependencies installed alongside Flask (such as Jinja2, Click, ItsDangerous, MarkupSafe, and Blinker) are licensed under the **BSD-3-Clause** or **MIT** licenses.
- - -
### Python & Tkinter (Tcl/Tk)
• **Python Standard Library**: Licensed under the **Python Software Foundation (PSF) License Agreement**.
<br>
• **Tkinter / Tcl/Tk**: Used for the host desktop status window, licensed under the **Tcl/Tk License** (BSD-style permissive license).
- - -
### Socket.IO (Real-Time Telemetry)
WB-Streamer Manager does not bundle `socket.io.js` directly in this repository; when monitoring active WestBroadcast Streamer instances, the web dashboard dynamically loads the Socket.IO client library from the running instance's `/static/` endpoint.
<br>
<br>
• **Socket.IO Client**: MIT License (Copyright (c) 2014-2025 Automattic).
