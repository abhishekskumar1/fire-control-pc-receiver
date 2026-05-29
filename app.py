import os
import sys
import time
import json
import serial
import serial.tools.list_ports
import threading
import socket
import queue
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

from pynput.keyboard import Controller as KController, Key
from pynput.mouse import Controller as MController, Button

import pystray
from PIL import Image, ImageDraw

# ============================================================
# Constants
# ============================================================
APP_TITLE = "Fire Control"
APP_ICON_ICO = "fire_control.ico"
APP_FOLDER_NAME = "FireControl"
CONFIG_FILE_NAME = "fire_control_config.json"

# ============================================================
# Internet Access Guard
# ============================================================
# Fire Control PC Receiver is designed to work offline.
# It only needs Bluetooth Serial / COM port access.
# This guard blocks accidental outgoing internet/network connections
# from this Python process while still allowing localhost use for
# the single-instance lock.
NETWORK_ACCESS_DISABLED = True

_original_socket_connect = socket.socket.connect
_original_socket_create_connection = socket.create_connection


def _is_local_address(host) -> bool:
    """Allow only local machine addresses. Block normal internet/LAN targets."""
    if host is None:
        return True

    host = str(host).strip().lower()

    return (
        host == ""
        or host == "localhost"
        or host == "::1"
        or host.startswith("127.")
    )


def _guarded_socket_connect(sock, address):
    """
    Blocks outgoing network connections.
    Allows localhost only because the app uses localhost for single-instance checking.
    """
    if NETWORK_ACCESS_DISABLED:
        try:
            host = address[0] if isinstance(address, tuple) and len(address) > 0 else address
        except Exception:
            host = address

        if not _is_local_address(host):
            raise PermissionError(
                "Internet/network access is disabled for Fire Control PC Receiver."
            )

    return _original_socket_connect(sock, address)


def _guarded_create_connection(address, timeout=None, source_address=None):
    """
    Blocks socket.create_connection() to internet/LAN targets.
    This prevents accidental internet use from this app process.
    """
    if NETWORK_ACCESS_DISABLED:
        try:
            host = address[0] if isinstance(address, tuple) and len(address) > 0 else address
        except Exception:
            host = address

        if not _is_local_address(host):
            raise PermissionError(
                "Internet/network access is disabled for Fire Control PC Receiver."
            )

    return _original_socket_create_connection(address, timeout, source_address)


# Apply network guard early before the app starts.
if NETWORK_ACCESS_DISABLED:
    socket.socket.connect = _guarded_socket_connect
    socket.create_connection = _guarded_create_connection


# Auto reconnect settings
AUTO_RECONNECT_DELAY_MS = 3000
SHOW_RECONNECT_POPUPS = False

# ============================================================
# Controllers
# ============================================================
keyboard = KController()
mouse = MController()

# ============================================================
# Key maps
# ============================================================
SPECIAL_KEYS = {
    "ENTER": Key.enter,
    "RETURN": Key.enter,
    "SPACE": Key.space,
    "BACK": Key.backspace,
    "BACKSPACE": Key.backspace,
    "ESC": Key.esc,
    "ESCAPE": Key.esc,
    "TAB": Key.tab,
    "CAPS": Key.caps_lock,
    "CAPSLOCK": Key.caps_lock,

    "SHIFT": Key.shift_l,
    "CTRL": Key.ctrl_l,
    "CONTROL": Key.ctrl_l,
    "ALT": Key.alt_l,
    "WIN": Key.cmd_l,
    "WINDOWS": Key.cmd_l,
    "CMD": Key.cmd_l,
    "COMMAND": Key.cmd_l,

    "DEL": Key.delete,
    "DELETE": Key.delete,
    "HOME": Key.home,
    "END": Key.end,
    "PGUP": Key.page_up,
    "PAGEUP": Key.page_up,
    "PGDN": Key.page_down,
    "PAGEDOWN": Key.page_down,
    "INS": Key.insert,
    "INSERT": Key.insert,
    "PRTSC": Key.print_screen,
    "PRINTSCREEN": Key.print_screen,
    "PAUSE": Key.pause,
    "MENU": Key.menu,

    "↑": Key.up,
    "↓": Key.down,
    "←": Key.left,
    "→": Key.right,
    "UP": Key.up,
    "DOWN": Key.down,
    "LEFT": Key.left,
    "RIGHT": Key.right,

    "F1": Key.f1, "F2": Key.f2, "F3": Key.f3, "F4": Key.f4,
    "F5": Key.f5, "F6": Key.f6, "F7": Key.f7, "F8": Key.f8,
    "F9": Key.f9, "F10": Key.f10, "F11": Key.f11, "F12": Key.f12
}

SHIFT_SYMBOLS = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
    "_": "-", "+": "=",
    "{": "[", "}": "]",
    "|": "\\",
    ":": ";", "\"": "'",
    "<": ",", ">": ".", "?": "/",
    "~": "`"
}


def resource_path(relative_path: str) -> str:
    """Works in normal Python and PyInstaller builds."""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_app_data_folder() -> str:
    """Safe writable folder for config after installer build."""
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_FOLDER_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def get_config_path() -> str:
    return os.path.join(get_app_data_folder(), CONFIG_FILE_NAME)


class FireKeyboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("560x470")
        self.root.configure(bg="#0B0B0D")
        self.root.resizable(False, False)

        self.set_window_icon()

        self.is_running = False
        self.is_connecting = False
        self.server_thread = None
        self.serial_conn = None
        self.tray_icon = None
        self.last_error_message = ""
        self.reconnect_timer_id = None
        self.auto_reconnect_enabled = True

        self.log_queue = queue.Queue()

        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.setup_ui()

        self.root.after(50, self.flush_log_queue)

        self.setup_tray()

        # Start hidden. GUI only appears when user opens it or when an error needs attention.
        self.root.withdraw()

        # Auto-start without requiring phone connection check.
        self.root.after(300, self.auto_connect)

    # ------------------------------------------------------------
    # Window / UI
    # ------------------------------------------------------------
    def set_window_icon(self):
        try:
            ico_path = resource_path(APP_ICON_ICO)
            if os.path.exists(ico_path):
                self.root.iconbitmap(ico_path)
        except Exception:
            pass

    def setup_ui(self):
        self.bg = "#0B0B0D"
        self.card = "#161618"
        self.card_2 = "#101012"
        self.border = "#2A2A2E"
        self.text = "#F5F5F5"
        self.muted = "#A7A7A7"
        self.orange = "#FF8C1A"
        self.orange_dark = "#FF5A1F"
        self.green = "#22C55E"
        self.red = "#FF3B30"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground=self.card_2,
            background=self.card_2,
            foreground=self.text,
            bordercolor=self.border,
            arrowcolor=self.orange,
            padding=5
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.card_2)],
            foreground=[("readonly", self.text)]
        )

        container = tk.Frame(self.root, bg=self.bg)
        container.pack(fill=tk.BOTH, expand=True, padx=22, pady=20)

        header = tk.Frame(container, bg=self.bg)
        header.pack(fill=tk.X)

        tk.Label(
            header,
            text="🔥 Fire Control",
            font=("Segoe UI", 20, "bold"),
            bg=self.bg,
            fg=self.text
        ).pack(anchor="center")

        tk.Label(
            header,
            text="Control your PC from your phone",
            font=("Segoe UI", 10),
            bg=self.bg,
            fg=self.muted
        ).pack(anchor="center", pady=(4, 0))

        settings_card = tk.Frame(
            container,
            bg=self.card,
            highlightbackground=self.border,
            highlightthickness=1
        )
        settings_card.pack(fill=tk.X, pady=(18, 0), ipady=12)

        port_row = tk.Frame(settings_card, bg=self.card)
        port_row.pack(fill=tk.X, padx=18, pady=(12, 6))

        tk.Label(
            port_row,
            text="Bluetooth COM Port",
            font=("Segoe UI", 10, "bold"),
            bg=self.card,
            fg=self.text
        ).pack(side=tk.LEFT)

        self.port_var = tk.StringVar()
        self.port_dropdown = ttk.Combobox(
            port_row,
            textvariable=self.port_var,
            state="readonly",
            width=12
        )
        self.port_dropdown.pack(side=tk.RIGHT, padx=(8, 0))

        tk.Button(
            port_row,
            text="↻",
            command=self.refresh_ports,
            bg=self.card_2,
            fg=self.orange,
            activebackground=self.border,
            activeforeground=self.text,
            bd=0,
            padx=10,
            pady=4,
            font=("Segoe UI", 11, "bold"),
            cursor="hand2"
        ).pack(side=tk.RIGHT, padx=(8, 0))

        self.baud_var = tk.StringVar(value="115200")
        self.refresh_ports()

        tk.Button(
            settings_card,
            text="Open Windows Bluetooth COM Setup",
            font=("Segoe UI", 9, "bold"),
            bg=self.card_2,
            fg=self.text,
            activebackground=self.border,
            activeforeground=self.text,
            bd=0,
            padx=14,
            pady=7,
            cursor="hand2",
            command=self.open_windows_settings
        ).pack(pady=(6, 12))

        control_card = tk.Frame(
            container,
            bg=self.card,
            highlightbackground=self.border,
            highlightthickness=1
        )
        control_card.pack(fill=tk.X, pady=(14, 0), ipady=14)

        self.status_title_var = tk.StringVar(value="Starting Fire Control...")
        self.status_detail_var = tk.StringVar(value="Checking Bluetooth COM ports.")

        self.status_panel = tk.Frame(
            control_card,
            bg=self.card_2,
            highlightbackground=self.orange,
            highlightthickness=1
        )
        self.status_panel.pack(fill=tk.X, padx=18, pady=(14, 12), ipady=10)

        self.status_title_label = tk.Label(
            self.status_panel,
            textvariable=self.status_title_var,
            font=("Segoe UI", 13, "bold"),
            bg=self.card_2,
            fg=self.orange,
            wraplength=470,
            justify="left"
        )
        self.status_title_label.pack(anchor="w", padx=16, pady=(10, 2))

        self.status_detail_label = tk.Label(
            self.status_panel,
            textvariable=self.status_detail_var,
            font=("Segoe UI", 9),
            bg=self.card_2,
            fg=self.muted,
            wraplength=470,
            justify="left"
        )
        self.status_detail_label.pack(anchor="w", padx=16, pady=(0, 10))

        self.btn_start = tk.Button(
            control_card,
            text="START",
            font=("Segoe UI", 11, "bold"),
            bg=self.orange,
            fg="white",
            activebackground=self.orange_dark,
            activeforeground="white",
            bd=0,
            width=26,
            pady=9,
            cursor="hand2",
            command=self.toggle_server
        )
        self.btn_start.pack(pady=(6, 12))

        tk.Label(
            container,
            text="Runs quietly in the background after connection.",
            font=("Segoe UI", 9),
            bg=self.bg,
            fg=self.muted
        ).pack(pady=(14, 0))

        self.set_status(
            "Ready",
            "Fire Control is ready. Select a COM port or let auto-connect find it.",
            "orange"
        )

    def log(self, msg: str):
        # Technical messages are kept in console only.
        # The app window shows only useful status messages for users.
        print(msg)

    def set_status(self, title: str, detail: str = "", level: str = "orange"):
        def apply():
            color = {
                "green": self.green,
                "red": self.red,
                "orange": self.orange,
                "white": self.text
            }.get(level, self.orange)

            try:
                self.status_title_var.set(title)
                self.status_detail_var.set(detail)
                self.status_title_label.configure(fg=color)
                self.status_panel.configure(highlightbackground=color)
            except Exception:
                pass

        try:
            self.root.after(0, apply)
        except Exception:
            apply()

    def flush_log_queue(self):
        # Kept for compatibility with older flow. No raw logs are shown in the app window.
        self.root.after(250, self.flush_log_queue)

    def show_window(self):
        self.root.after(0, self.root.deiconify)

    def hide_window(self):
        self.root.withdraw()

    def show_user_problem(self, title: str, message: str, popup: bool = True):
        """Show one clear user-facing status when action is needed."""
        self.last_error_message = message
        short_message = message.split("\n")[0].strip() if message else title
        self.log(f"[!] {message}")
        self.set_status(title, short_message, "red")
        self.root.after(0, self.show_window)

        if popup and SHOW_RECONNECT_POPUPS:
            self.root.after(100, lambda: messagebox.showwarning(title, message))

    def open_windows_settings(self):
        self.set_status("Opening Bluetooth settings", "Use Windows Bluetooth COM setup if the port is missing.", "orange")
        self.log("[*] Opening Bluetooth settings...")
        try:
            os.system("control bthprops.cpl")
        except Exception as e:
            self.log(f"[!] Could not open Bluetooth settings: {e}")

    # ------------------------------------------------------------
    # Config
    # ------------------------------------------------------------
    def load_config(self):
        try:
            with open(get_config_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_com_port", "")
        except (FileNotFoundError, json.JSONDecodeError):
            return ""
        except Exception as e:
            self.log(f"[!] Could not load config: {e}")
            return ""

    def save_config(self, port):
        try:
            with open(get_config_path(), "w", encoding="utf-8") as f:
                json.dump({"last_com_port": port}, f, indent=2)
        except Exception as e:
            self.log(f"[!] Failed to save config: {e}")

    # ------------------------------------------------------------
    # Bluetooth / COM helpers
    # ------------------------------------------------------------
    def is_bluetooth_service_running(self) -> bool | None:
        """
        Windows-only soft check.
        True  = Bluetooth service seems running.
        False = Bluetooth service seems stopped/disabled.
        None  = could not check, so don't trust it.
        """
        if os.name != "nt":
            return None

        try:
            result = subprocess.run(
                ["sc", "query", "bthserv"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            output = (result.stdout + result.stderr).upper()
            if "RUNNING" in output:
                return True
            if "STOPPED" in output:
                return False
            return None
        except Exception:
            return None

    def refresh_ports(self):
        try:
            ports = serial.tools.list_ports.comports()
            vals = [p.device for p in ports]
        except Exception as e:
            vals = []
            self.log(f"[!] Could not scan COM ports: {e}")

        self.port_dropdown["values"] = vals

        if vals:
            self.set_status("COM port found", "Choose the Bluetooth COM port or click START.", "orange")
        elif hasattr(self, "status_title_var"):
            self.set_status("Bluetooth COM port not found", "Turn on Bluetooth, then click refresh.", "red")

        if vals and not self.port_var.get():
            self.port_dropdown.current(0)

        return vals

    def explain_serial_error(self, port: str, error: Exception) -> str:
        err = str(error).lower()

        if "access is denied" in err or "permission" in err:
            return (
                f"{port} is busy or blocked.\n"
                "Reason: Another app may already be using this COM port.\n"
                "Fix: Close other Bluetooth/serial apps, then click Reconnect."
            )

        if "could not open port" in err or "cannot find" in err or "file not found" in err:
            return (
                f"{port} could not be opened.\n"
                "Reason: The COM port may have disappeared or Bluetooth may have changed ports.\n"
                "Fix: Refresh COM ports or turn Bluetooth off/on once."
            )

        if "semaphore timeout" in err or "timeout" in err:
            return (
                f"{port} did not respond in time.\n"
                "Reason: Bluetooth serial port exists, but Windows did not respond properly.\n"
                "Fix: Try Reconnect. If it repeats, remove and recreate the COM port."
            )

        if "device attached to the system is not functioning" in err:
            return (
                f"{port} exists but is not functioning correctly.\n"
                "Reason: Windows Bluetooth COM port is stuck.\n"
                "Fix: Turn Bluetooth off/on, then click Reconnect."
            )

        return (
            f"Could not open {port}.\n"
            f"Technical detail: {error}\n"
            "Fix: Try another COM port or click Reconnect."
        )

    def schedule_auto_reconnect(self, reason: str):
        """
        Keep trying again after Bluetooth/COM failure.
        This does not check phone connection. It only waits for Windows COM ports to come back.
        """
        if not self.auto_reconnect_enabled:
            return

        if self.is_running or self.is_connecting:
            return

        if self.reconnect_timer_id is not None:
            return

        self.log(f"[*] Auto reconnect scheduled in {AUTO_RECONNECT_DELAY_MS // 1000} seconds. Reason: {reason}")

        try:
            self.btn_start.configure(text="WAITING...", bg=self.orange)
            self.set_status("Waiting for Bluetooth COM port", "Fire Control will reconnect automatically when the COM port returns.", "orange")
        except Exception:
            pass

        self.reconnect_timer_id = self.root.after(AUTO_RECONNECT_DELAY_MS, self._auto_reconnect_tick)

    def _auto_reconnect_tick(self):
        self.reconnect_timer_id = None

        if self.is_running or self.is_connecting:
            return

        self.log("[*] Auto reconnect trying again...")
        self.set_status("Searching again...", "Checking Bluetooth COM ports.", "orange")
        self.auto_connect(show_popup=False)

    # ------------------------------------------------------------
    # Auto-connect / server lifecycle
    # ------------------------------------------------------------
    def auto_connect(self, show_popup: bool = True):
        if self.is_running or self.is_connecting:
            return

        ports = self.refresh_ports()

        if not ports:
            bt_state = self.is_bluetooth_service_running()

            if bt_state is False:
                self.show_user_problem(
                    "Bluetooth is off",
                    "Bluetooth service seems OFF on this PC.\n\n"
                    "Fix: Turn ON Bluetooth in Windows. The app will auto-reconnect when COM ports return.",
                    popup=show_popup
                )
                self.schedule_auto_reconnect("Bluetooth service is off")
            else:
                self.show_user_problem(
                    "No COM port found",
                    "No COM port was found.\n\n"
                    "This app does not need to check whether the phone is connected.\n"
                    "But Windows must have at least one Bluetooth COM port available.\n\n"
                    "Possible reason: Bluetooth may be OFF, or Windows removed the Bluetooth COM port.\n"
                    "Fix: Turn ON Bluetooth. The app will auto-reconnect when COM ports return.",
                    popup=show_popup
                )
                self.schedule_auto_reconnect("No COM ports found")
            return

        saved_port = self.load_config()

        # Keep your auto-search idea: saved port first, then all other COM ports.
        if saved_port in ports:
            ports.remove(saved_port)
            ports.insert(0, saved_port)

        try:
            baud = int(self.baud_var.get().strip())
        except ValueError:
            self.show_user_problem("Invalid baud", "Invalid baud value selected.")
            return

        self.is_connecting = True
        self.btn_start.configure(text="CONNECTING...", bg=self.orange)
        self.set_status("Searching for COM port...", "Trying to find a working Bluetooth COM port.", "orange")

        self.server_thread = threading.Thread(
            target=self._connection_hunter,
            args=(ports, baud),
            daemon=True
        )
        self.server_thread.start()

    def _connection_hunter(self, ports, baud):
        self.log("[*] Auto-searching working COM port...")

        failures = []

        for port in ports:
            if not self.is_connecting:
                break

            self.log(f"[*] Trying {port}...")

            try:
                conn = serial.Serial(
                    port=port,
                    baudrate=baud,
                    timeout=0.05,
                    write_timeout=0.05
                )

                self.serial_conn = conn
                self.is_running = True
                self.is_connecting = False
                self.reconnect_timer_id = None
                self.save_config(port)
                self.port_var.set(port)

                self.root.after(
                    0,
                    lambda: self.btn_start.configure(text="STOP", bg=self.red)
                )

                self.set_status(f"Connected to {port}", "Fire Control is ready. Keep this app running in the background.", "green")
                self.log(f"[+] Connected on {port} @ {baud}")
                self.listen_loop()
                return

            except serial.SerialException as e:
                explanation = self.explain_serial_error(port, e)
                failures.append(f"{port}: {explanation.splitlines()[0]}")
                self.log(f"[-] {explanation.replace(chr(10), ' ')}")
                time.sleep(0.3)

            except Exception as e:
                failures.append(f"{port}: Unexpected error: {e}")
                self.log(f"[-] Unexpected error on {port}: {e}")
                time.sleep(0.3)

        self.is_connecting = False
        self.is_running = False
        self.root.after(
            0,
            lambda: self.btn_start.configure(text="START", bg=self.orange)
        )

        if ports:
            short_failures = "\n".join(failures[:6])
            self.show_user_problem(
                "No working COM port",
                "COM ports were found, but none could be opened.\n\n"
                "Most common reasons:\n"
                "1. The COM port is busy in another app.\n"
                "2. Bluetooth may be OFF or Windows Bluetooth COM port is stuck.\n"
                "3. Wrong/outgoing COM port was selected by Windows.\n\n"
                f"Checked:\n{short_failures}\n\n"
                "Fix: Turn Bluetooth ON or close other serial apps. The app will keep trying automatically.",
                popup=True
            )
            self.schedule_auto_reconnect("COM ports exist but none opened")

    def toggle_server(self):
        if self.is_connecting:
            self.is_connecting = False
            self.stop_server("[*] Connection attempt cancelled.")
            return

        if not self.is_running:
            port = self.port_var.get().strip()

            if not port:
                self.show_user_problem(
                    "No COM port selected",
                    "No COM port is selected.\n\n"
                    "Fix: Click refresh. If no port appears, turn ON Bluetooth and check Windows COM setup."
                )
                return

            try:
                baud = int(self.baud_var.get().strip())
            except ValueError:
                self.show_user_problem("Invalid baud", "Invalid baud value selected.")
                return

            self.is_running = True
            self.btn_start.configure(text="STOP", bg=self.red)
            self.set_status(f"Connected to {port}", "Fire Control is ready. Keep this app running in the background.", "green")

            self.server_thread = threading.Thread(
                target=self.run_server_manual,
                args=(port, baud),
                daemon=True
            )
            self.server_thread.start()
        else:
            self.stop_server("[*] Stopped by user.")

    def run_server_manual(self, port_name: str, baud: int):
        try:
            self.serial_conn = serial.Serial(
                port=port_name,
                baudrate=baud,
                timeout=0.05,
                write_timeout=0.05
            )
            self.set_status(f"Connected to {port_name}", "Fire Control is ready. Keep this app running in the background.", "green")
            self.log(f"[+] Connected on {port_name} @ {baud}")
            self.save_config(port_name)
            self.listen_loop()

        except serial.SerialException as e:
            explanation = self.explain_serial_error(port_name, e)
            self.root.after(0, lambda: self.stop_server("[*] Stopped due to COM error."))
            self.show_user_problem("COM port error", explanation)
            self.schedule_auto_reconnect("Manual COM open failed")

        except Exception as e:
            self.root.after(0, lambda: self.stop_server("[*] Stopped due to unexpected error."))
            self.show_user_problem(
                "Unexpected error",
                f"Unexpected server error.\n\nTechnical detail: {e}"
            )

    def listen_loop(self):
        while self.is_running and self.serial_conn and self.serial_conn.is_open:
            try:
                raw = self.serial_conn.readline()

                if not raw:
                    continue

                try:
                    line = raw.decode("utf-8", errors="ignore").strip()
                except Exception:
                    self.log("[!] Received unreadable Bluetooth data. Ignored.")
                    continue

                if not line:
                    continue

                if not (line.startswith("M:") or line.startswith("S:") or line.startswith("SH:")):
                    self.log(f"[RX] {line}")

                try:
                    self.handle_packet(line)
                except Exception as e:
                    # One bad command should not kill the whole app.
                    self.log(f"[Packet ignored] {line} | Reason: {e}")

            except serial.SerialException as e:
                current_port = self.port_var.get() or "COM port"
                ports_now = self.refresh_ports()

                if not ports_now or current_port not in ports_now:
                    explanation = (
                        f"{current_port} disappeared from Windows.\n\n"
                        "Most likely reason: Bluetooth was turned OFF, Bluetooth restarted, "
                        "or Windows removed the Bluetooth COM port.\n\n"
                        "Fix: Turn Bluetooth ON again. The app will auto-reconnect when the COM port returns."
                    )
                    reason = "Bluetooth/COM port disappeared"
                else:
                    explanation = self.explain_serial_error(current_port, e)
                    reason = "Serial connection lost"

                self.root.after(0, lambda: self.stop_server("[*] Bluetooth/COM connection was lost."))
                self.show_user_problem("Bluetooth / COM connection lost", explanation, popup=True)
                self.root.after(500, lambda: self.schedule_auto_reconnect(reason))
                return

            except Exception as e:
                self.log(f"[Listen error] {e}")
                time.sleep(0.05)

        if self.is_running:
            self.root.after(0, lambda: self.stop_server("[*] Connection closed."))

    def stop_server(self, message="[*] Stopped."):
        self.is_running = False
        self.is_connecting = False

        try:
            if self.reconnect_timer_id is not None:
                self.root.after_cancel(self.reconnect_timer_id)
        except Exception:
            pass

        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
        except Exception:
            pass

        self.serial_conn = None
        self.btn_start.configure(text="START", bg=self.orange)
        self.log(message)
        if "lost" in message.lower():
            self.set_status("Connection lost", "Bluetooth or COM port disconnected. Fire Control will try to reconnect.", "red")
        elif "stopped" in message.lower() or "stopped" in message.lower() or "Stopped" in message:
            self.set_status("Stopped", "Click START to reconnect.", "orange")

    def reconnect(self, icon=None, item=None):
        self.log("[*] Reconnect requested.")

        if self.reconnect_timer_id is not None:
            try:
                self.root.after_cancel(self.reconnect_timer_id)
            except Exception:
                pass
            self.reconnect_timer_id = None

        self.stop_server("[*] Restarting...")
        self.root.after(300, lambda: self.auto_connect(show_popup=True))

    # ------------------------------------------------------------
    # Keyboard & Mouse Logic
    # ------------------------------------------------------------
    def normalize_token(self, token: str):
        t = token.strip()
        if not t:
            return None
        u = t.upper()
        if u in SPECIAL_KEYS:
            return SPECIAL_KEYS[u]
        if t in SPECIAL_KEYS:
            return SPECIAL_KEYS[t]
        if len(t) == 1:
            return t
        return t.lower()

    def resolve_payload(self, payload: str):
        if not payload:
            return []

        pu = payload.upper()
        if pu in ("CAPS", "CAPSLOCK"):
            return [Key.caps_lock]

        tokens = [t.strip() for t in payload.split("+") if t.strip()]
        resolved = []

        if len(tokens) == 1 and len(tokens[0]) == 1:
            ch = tokens[0]
            if "A" <= ch <= "Z":
                resolved.extend([Key.shift_l, ch.lower()])
            elif ch in SHIFT_SYMBOLS:
                resolved.extend([Key.shift_l, SHIFT_SYMBOLS[ch]])
            else:
                resolved.append(ch)
            return resolved

        for tok in tokens:
            u = tok.upper()

            if u in ("CAPS", "CAPSLOCK"):
                resolved.append(Key.caps_lock)
                continue

            r = self.normalize_token(tok)

            if r is None:
                continue

            if isinstance(r, str) and len(r) == 1 and r.isalpha():
                r = r.lower()

            resolved.append(r)

        return resolved

    def press_payload(self, payload: str):
        keys = self.resolve_payload(payload)
        for k in keys:
            try:
                keyboard.press(k)
            except Exception as e:
                self.log(f"[Key press ignored] {payload}: {e}")

    def release_payload(self, payload: str):
        keys = self.resolve_payload(payload)
        for k in reversed(keys):
            try:
                keyboard.release(k)
            except Exception as e:
                self.log(f"[Key release ignored] {payload}: {e}")

    def execute_legacy_key(self, payload: str):
        self.press_payload(payload)
        self.release_payload(payload)

    def handle_packet(self, line: str):
        if ":" not in line:
            return

        action, payload = line.split(":", 1)
        action = action.strip().upper()
        payload = payload.strip()

        if action == "KD":
            self.press_payload(payload)

        elif action == "KU":
            self.release_payload(payload)

        elif action == "K":
            self.execute_legacy_key(payload)

        elif action == "M":
            p = payload.split(":")
            if len(p) == 2:
                try:
                    mouse.move(int(float(p[0])), int(float(p[1])))
                except ValueError:
                    self.log(f"[Bad mouse move ignored] {payload}")

        elif action == "S":
            try:
                steps = int(-int(float(payload)) / 8)
                if steps != 0:
                    mouse.scroll(0, steps)
            except ValueError:
                self.log(f"[Bad vertical scroll ignored] {payload}")

        elif action == "SH":
            try:
                steps = int(-int(float(payload)) / 8)
                if steps != 0:
                    mouse.scroll(steps, 0)
            except ValueError:
                self.log(f"[Bad horizontal scroll ignored] {payload}")

        elif action == "Z":
            try:
                steps = int(int(float(payload)) / 12)
                if steps != 0:
                    keyboard.press(Key.ctrl)
                    mouse.scroll(0, steps)
                    keyboard.release(Key.ctrl)
            except ValueError:
                self.log(f"[Bad zoom ignored] {payload}")
            finally:
                try:
                    keyboard.release(Key.ctrl)
                except Exception:
                    pass

        elif action == "MD":
            mouse.press(Button.left)

        elif action == "MU":
            mouse.release(Button.left)

        elif action == "C":
            b = payload.strip()
            if b == "1":
                mouse.click(Button.left)
            elif b == "2":
                mouse.click(Button.right)
            else:
                mouse.click(Button.middle)

        else:
            self.log(f"[Unknown command ignored] {line}")

    # ------------------------------------------------------------
    # Tray & app quit
    # ------------------------------------------------------------
    def create_tray_icon_image(self):
        try:
            ico_path = resource_path(APP_ICON_ICO)
            if os.path.exists(ico_path):
                return Image.open(ico_path)
        except Exception:
            pass

        img = Image.new("RGB", (64, 64), "black")
        draw = ImageDraw.Draw(img)
        draw.rectangle((16, 16, 48, 48), fill="red")
        return img

    def setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Show GUI", self.show_window_from_tray, default=True),
            pystray.MenuItem("Reconnect", self.reconnect),
            pystray.MenuItem("Quit", self.quit_app)
        )
        self.tray_icon = pystray.Icon(
            APP_TITLE,
            self.create_tray_icon_image(),
            APP_TITLE,
            menu
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window_from_tray(self, icon=None, item=None):
        self.show_window()

    def quit_app(self, icon=None, item=None):
        self.is_running = False
        self.is_connecting = False

        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
        except Exception:
            pass

        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except Exception:
            pass

        try:
            self.root.destroy()
        except Exception:
            pass

        os._exit(0)


if __name__ == "__main__":
    # Single instance lock
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.bind(("127.0.0.1", 49133))
    except socket.error:
        print("Fire Control is already running.")
        sys.exit(0)

root = tk.Tk()
root.withdraw()
app = FireKeyboardApp(root)
root.mainloop()