# Demo outreach folder

The home page links **See an example outreach folder** to `/f/de000000000000000000000000000233`,
a House 22 folder with three sourced match cards, dated outreach notes and accepted
suggestions (#155). No sign-in: like every folder, the link is the access.

## What a refresh does

`python -m app.folders.demo --matches --commit` replaces the seed folder, and only it, in one
transaction ([demo.py](../app/folders/demo.py)). Without `--commit` it previews and writes nothing.
The seed itself never changes from the web: a visitor's first edit makes a private copy with
its own link, and later refreshes leave that copy alone. The home page shows the link only
while the folders flag is on and the seed exists, so the store must be seeded before the
link can appear.

## Install the nightly refresh

The units assume the checkout at `/srv/know-your-district` (with `uv sync` run there), a
`kyd` user, and the app service reading `/etc/know-your-district/kyd.env`. That file is the
one place the store is configured; the app's own unit uses the same line:

```
EnvironmentFile=/etc/know-your-district/kyd.env
```

and the file holds, outside the checkout, mode 0600:

```
KYD_FOLDERS_DB=/var/lib/know-your-district/folders.db
```

As root:

```
install -m 0644 deploy/systemd/kyd-demo-reset.service /etc/systemd/system/
install -m 0644 deploy/systemd/kyd-demo-reset.timer /etc/systemd/system/
systemctl daemon-reload
systemctl start kyd-demo-reset.service    # seed once now, before the link is shown
journalctl -u kyd-demo-reset.service -n 5 # expect "Refresh /f/de00…"
systemctl enable --now kyd-demo-reset.timer
systemctl list-timers kyd-demo-reset.timer
```

The timer runs at 03:00 Hawaiʻi time each night; `Persistent=true` runs a missed night at the
next boot. Each run also renews the seed's last write, so the 180-day cleanup never removes it.
The run makes no network calls (`PrivateNetwork=yes`).

To stop publishing: `systemctl disable --now kyd-demo-reset.timer`. The seed then expires
with the 180-day cleanup and the home link disappears with it.

Units: [service](../deploy/systemd/kyd-demo-reset.service),
[timer](../deploy/systemd/kyd-demo-reset.timer).
