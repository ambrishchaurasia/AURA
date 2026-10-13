"""Training examples for the spoken reply: an agent's terse result -> one natural sentence.

Each shape below returns (what the user said, the call, the result text as the agent writes it,
the sentence to say). The result formats are the agents' real ones; when an agent changes what it
returns, update the matching shape and retrain.
"""
import json

from automation.mcp import slm_client

APPS = ["chrome", "brave", "spotify", "firefox", "vlc", "discord", "steam", "teams", "zoom"]
PLANS = ["Balanced", "Power saver", "High performance", "Best performance", "Ultimate Performance"]
OUTPUTS = ["Speakers (Realtek(R) Audio)", "Headphones (WH-1000XM4)", "LG ULTRAGEAR (NVIDIA High Definition Audio)",
           "Razer Kraken X (7.1 Surround Sound)", "Internal AUX Jack"]
# Results that are already plain sentences are said as they are.
PLAIN = ["Closed File Explorer window", "Selected all items in File Explorer", "Pasted items in File Explorer",
         "Copied selected items in File Explorer", "Searched for 'budget' in File Explorer", "Created folder 'C:\\Users\\me\\Documents\\reports'",
         "Opened File Explorer at 'Downloads'", "Opened https://youtube.com", "Settings window found", "Connected to JioFiber",
         "DNS cache cleared", "Windows Update is checking for updates", "Typed 11 characters (Tier 1)", "Saved the file", "Notepad is open"]


def _volume(rng):
    level, kind = rng.choice(range(0, 101, 5)), rng.choice(["get", "set", "up", "down", "mute", "unmute"])
    muted = kind == "mute" or (kind == "get" and rng.random() < 0.2)
    said, call, reply = {
        "get": ("what's the volume", "settings.get_volume {}", f"The volume is at {level} percent" + (", and it's muted." if muted else ".")),
        "set": (f"set the volume to {level}", f'settings.set_volume {{"level": {level}}}', f"Volume is now at {level} percent."),
        "up": ("can you turn up my volume", 'settings.change_volume {"direction": "up"}', f"I turned it up. Volume is now at {level} percent."),
        "down": ("turn it down", 'settings.change_volume {"direction": "down"}', f"I turned it down. Volume is now at {level} percent."),
        "mute": ("mute", 'settings.set_mute {"state": "on"}', "Sound is muted."),
        "unmute": ("unmute", 'settings.set_mute {"state": "off"}', f"Sound is back on at {level} percent."),
    }[kind]
    return said, call, f"volume: {level}, muted: {muted}", reply


def _app_volume(rng):
    app, level, kind = rng.choice(APPS), rng.choice(range(0, 101, 5)), rng.choice(["set", "up", "down", "mute", "unmute"])
    muted = kind == "mute"
    said, call, reply = {
        "set": (f"set {app} volume to {level}", f'settings.set_app_volume {{"app": "{app}", "level": {level}}}', f"{app.title()} is now at {level} percent."),
        "up": (f"turn {app} up", f'settings.change_app_volume {{"app": "{app}", "direction": "up"}}', f"I turned {app.title()} up to {level} percent."),
        "down": (f"{app} is too loud", f'settings.change_app_volume {{"app": "{app}", "direction": "down"}}', f"I turned {app.title()} down to {level} percent."),
        "mute": (f"mute {app}", f'settings.set_app_mute {{"app": "{app}", "state": "on"}}', f"{app.title()} is muted."),
        "unmute": (f"unmute {app}", f'settings.set_app_mute {{"app": "{app}", "state": "off"}}', f"{app.title()} is unmuted, at {level} percent."),
    }[kind]
    return said, call, f"app: {app}, volume: {level}, muted: {muted}, playing: {rng.choice([True, False])}", reply


def _radio(rng):
    radio, state, asked = rng.choice(["bluetooth", "wifi"]), rng.choice(["on", "off"]), rng.random() < 0.4
    name = {"bluetooth": "Bluetooth", "wifi": "Wi-Fi"}[radio]
    if asked:
        return f"is {radio} on", f"settings.get_{radio} {{}}", f"radio: {radio}, radio_state: {state}", f"{name} is {state}."
    return (f"turn {radio} {state}", f'settings.set_{radio} {{"state": "{state}"}}', f"radio: {radio}, radio_state: {state}",
            f"{name} is now {state}.")


def _theme(rng):
    theme = rng.choice(["dark", "light"])
    if rng.random() < 0.4:
        return "am i in dark mode", "settings.get_theme {}", f"theme: {theme}", f"You're in {theme} mode."
    return f"{theme} mode", f'settings.set_theme {{"mode": "{theme}"}}', f"theme: {theme}", f"Switched to {theme} mode."


def _brightness(rng):
    level, kind = rng.choice(range(0, 101, 5)), rng.choice(["get", "set", "up", "down"])
    said, call, reply = {
        "get": ("how bright is the screen", "settings.get_brightness {}", f"Brightness is at {level} percent."),
        "set": (f"set brightness to {level}", f'settings.set_brightness {{"level": {level}}}', f"Brightness is now at {level} percent."),
        "up": ("make the screen brighter", 'settings.change_brightness {"direction": "up"}', f"Brighter now, at {level} percent."),
        "down": ("dim the screen", 'settings.change_brightness {"direction": "down"}', f"Dimmed to {level} percent."),
    }[kind]
    return said, call, f"brightness: {level}", reply


def _battery(rng):
    percent, plugged = rng.randint(3, 100), rng.random() < 0.5
    charging = plugged and percent < 100 and rng.random() < 0.8
    saver = not plugged and percent < 25 and rng.random() < 0.5
    minutes = None if plugged or rng.random() < 0.4 else rng.randint(20, 400)
    reply = f"Battery is at {percent} percent"
    reply += " and charging." if charging else ", plugged in." if plugged else ", running on battery."
    if minutes:
        reply += f" About {minutes} minutes left."
    if saver:
        reply += " Battery saver is on."
    return ("how much battery is left", "settings.get_battery {}",
            f"battery: True, percent: {percent}, plugged_in: {plugged}, charging: {charging}, battery_saver: {saver}, minutes_left: {minutes}", reply)


def _storage(rng):
    drives = [{"drive": letter, "total_gb": total, "free_gb": round(total * rng.uniform(0.03, 0.9), 1), "used_percent": 0}
              for letter, total in zip(["C:", "D:", "E:"][:rng.randint(1, 3)], rng.sample([118.6, 237.9, 465.1, 931.5, 50.0, 1862.9], 3))]
    for drive in drives:
        drive["used_percent"] = round(100 * (1 - drive["free_gb"] / drive["total_gb"]))
    parts = [f"{d['free_gb']} gigabytes free on {d['drive'][0]}" for d in drives]
    return ("how much disk space is left", "settings.storage_status {}", json.dumps({"drives": drives}),
            "You have " + (", and ".join(parts) if len(parts) < 3 else f"{parts[0]}, {parts[1]}, and {parts[2]}") + ".")


def _power_plans(rng):
    names = rng.sample(PLANS, rng.randint(2, 4))
    active = rng.choice(names)
    plans = [{"guid": "%08x-0000-0000-0000-000000000000" % rng.getrandbits(32), "name": name, "active": name == active} for name in names]
    return "which power plan is active", "settings.list_power_plans {}", json.dumps({"plans": plans}), f"You're on the {active} power plan."


def _audio_devices(rng):
    names = rng.sample(OUTPUTS, rng.randint(2, 4))
    default = rng.choice(names)
    devices = [{"name": name, "default": name == default} for name in names]
    return ("where is the sound playing from", "settings.list_audio_devices {}", json.dumps({"devices": devices}),
            f"Sound is playing through {default.split(' (')[0]}.")


def _timeouts(rng):
    values = [rng.choice([0, 1, 2, 5, 10, 15, 30, 60]) for _ in range(4)]

    def spoken(minutes):
        return "never" if minutes == 0 else f"after {minutes} minute" + ("s" if minutes != 1 else "")

    return ("when does my screen turn off", "settings.get_power_timeouts {}",
            "display_plugged_in: {}, display_battery: {}, sleep_plugged_in: {}, sleep_battery: {}".format(*values),
            f"Plugged in, the screen turns off {spoken(values[0])} and the PC sleeps {spoken(values[2])}. "
            f"On battery, the screen turns off {spoken(values[1])} and the PC sleeps {spoken(values[3])}.")


def _system(rng):
    name, hours = rng.choice(["Somansh", "DESKTOP-4F2K9Q", "LAPTOP-HOME", "Office-PC"]), round(rng.uniform(0.2, 90), 1)
    build = rng.choice(["10.0.26100", "10.0.22631", "10.0.26300"])
    return ("tell me about this computer", "settings.system_info {}",
            f"computer: {name}, os: Windows 11 ({build}), processor: Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, "
            f"uptime_hours: {hours}, local_time: 2026-10-13 17:37",
            f"This PC is called {name}. It runs Windows 11 and has been on for {hours} hours.")


def _plain(rng):
    details = rng.choice(PLAIN)
    reply = {"Opened https://youtube.com": "I opened youtube.com.", "Typed 11 characters (Tier 1)": "I typed that for you.",
             "Settings window found": "Settings is open."}.get(details, details.replace("'", "") + ".")
    return "do that please", "explorer.open {}" if "Explorer" in details else "notepad.type {}", details, reply


SHAPES = [_volume, _volume, _app_volume, _radio, _radio, _theme, _brightness, _battery, _battery, _storage,
          _power_plans, _audio_devices, _timeouts, _system, _plain]


def examples(rng, count):
    for i in range(count):
        said, call, details, reply = SHAPES[i % len(SHAPES)](rng)
        yield slm_client.reply_prompt(said, call, details), {"reply": reply}
