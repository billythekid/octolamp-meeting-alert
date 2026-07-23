# octolamp-meeting-alert

A tiny Python script that watches your Outlook calendar and flashes your [Octolamp](https://github.com/martinwoodward/octolamp) (or any other [WLED](https://kno.wled.ge/) device) before a meeting starts.

- Amber pulse at T-5 minutes.
- Red solid at T-1 minute.
- Restores whatever the lamp was doing before, once the meeting starts.

Runs on your Mac in a terminal window (or as a background LaunchAgent if you want it to survive reboots).

## What you need

- macOS. Uses `security` for the Keychain, `pbpaste` for pasting, and `launchctl` for the optional auto-start. Nothing else is Mac-specific in the script itself, but the setup steps assume macOS.
- Python 3.9 or later.
- A WLED device on the same LAN as your Mac. The [Octolamp](https://github.com/martinwoodward/octolamp) is the obvious choice, but any WLED build works.
- An Outlook mailbox that lets you publish your calendar as an `.ics` URL.

## What it does not need

- No Azure app registration, no Microsoft Graph, no OAuth. Just a published `.ics` feed.
- No Home Assistant, no MQTT broker, no cloud middleman. The Mac talks directly to the WLED device on your LAN.
- No credentials on disk. The published-calendar URL sits in your Keychain.

## Setup

### 1. Publish your Outlook calendar

In Outlook on the web: Settings → Calendar → Shared calendars → Publish a calendar. Pick your main calendar, set permissions to "Can view all details", and publish. You get an `.ics` URL. Copy it.

The URL contains a token in the path. Anyone with the URL can read your full calendar. Treat it like a password: do not paste it into chats, screenshots, or anywhere it might be logged. If it leaks, unpublish and republish to rotate the token.

### 2. Store the URL in Keychain

Copy the URL to your clipboard first, then run:

```bash
security delete-generic-password -a "$USER" -s "octolamp-ics-url" 2>/dev/null
security add-generic-password -a "$USER" -s "octolamp-ics-url" -w "$(pbpaste | tr -d '\n\r\t ')"
```

The `pbpaste | tr` bit strips any whitespace or newlines that sometimes tag along with a copy. This matters. If you use the interactive form (`security add-generic-password ... -w` with no value), the terminal prompt can silently truncate long URLs on paste, and you will get 400s from Microsoft with no obvious cause.

Sanity check the length:

```bash
security find-generic-password -a "$USER" -s "octolamp-ics-url" -w | wc -c
```

A typical Outlook published-calendar URL is around 150 characters. If yours came out much shorter, the paste got clipped. Re-copy from Outlook and rerun the store step.

### 3. Find your WLED device

Easiest way is to open the WLED phone app, or look at your router's DHCP client list. The device advertises itself over mDNS as something like `wled-abc123.local`. You can verify from your Mac:

```bash
curl -s http://wled-abc123.local/json/info | head -c 200
```

If that returns JSON, you have the right hostname. If it hangs or fails, try the raw IP address instead. Note that Tailscale in some configurations hijacks `.local` resolution, so if you are on Tailscale and mDNS fails, use the IP.

### 4. Configure the script

Open `octolamp_meeting_alert.py` and edit the constants at the top:

- `WLED_HOST` — your device hostname or IP, e.g. `wled-abc123.local` or `192.168.1.70`.
- `SELF_EMAIL_HINTS` — substrings of your work email, used only to skip meetings you have declined. Set to something that will match your name or handle inside an ATTENDEE line, e.g. `("jane.smith", "jsmith")`.
- Timing constants (`WARN_MINUTES`, `IMMINENT_MINUTES`, `POLL_SECONDS`) are fine at their defaults but tweak if you want.
- `AMBER` and `RED` are RGB triples if you fancy different colours.

### 5. Install Python dependencies

```bash
pip3 install --user icalendar recurring-ical-events tzdata
```

The `recurring-ical-events` library does the tedious RRULE expansion so recurring meetings (which is most of them) are handled properly, including exceptions and per-occurrence overrides.

### 6. Run it

```bash
python3 octolamp_meeting_alert.py
```

The script prints one line when it starts, then stays silent until something happens. A state change looks like:

```
[16:55:03] idle -> warn (next 17:00)
[16:59:03] warn -> imminent (next 17:00)
[17:00:03] imminent -> idle (next -)
```

Ctrl-C stops it and restores the lamp's prior state.

If you want a heartbeat print while you eyeball it, add one to the loop. Otherwise silence is correct.

## Run it at login (optional)

Once you trust it, create `~/Library/LaunchAgents/com.yourname.octolamp.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yourname.octolamp</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/YOU/github/octolamp-meeting-alert/octolamp_meeting_alert.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/octolamp.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/octolamp.err</string>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.yourname.octolamp.plist
```

To unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.yourname.octolamp.plist
```

Logs go to `/tmp/octolamp.log` and `/tmp/octolamp.err`.

## Rotating the calendar URL

If the URL ever leaks: in Outlook Web, unpublish the calendar, then publish it again. That mints a fresh token and invalidates the old one. Then update the Keychain entry with the new URL following step 2.

## How it works

- Polls the `.ics` URL every 60 seconds (cached, to be gentle on Microsoft's server).
- Expands the next 60 minutes of events using `recurring-ical-events`, which handles RRULE + EXDATE + per-occurrence overrides.
- Skips CANCELLED and TENTATIVE events, and events where an ATTENDEE line matching your `SELF_EMAIL_HINTS` has `PARTSTAT=DECLINED`.
- On the first transition into an alert window, snapshots the current WLED state via `GET /json/state`.
- On the transition out, POSTs that saved state back so the lamp returns to whatever it was doing before.
- If the lamp was off before the alert, it goes off after.

## Known quirks

- Microsoft's published-calendar feed refreshes server-side roughly every hour. Meetings added within the last hour may not appear in the feed yet, so last-minute additions can be missed. Everything else is fine.
- Python's `urllib.request` gets HTTP 400 from the Microsoft endpoint even with a curl-ish User-Agent, for reasons I did not care enough to reverse-engineer. The script shells out to `curl` instead. It just works.
- WLED effect numbers vary slightly between firmware versions. If your amber "pulse" looks wrong, try other values in the `EFFECT_BREATHE` constant. WLED docs list them all.

## Licence

MIT. See `LICENSE`.
