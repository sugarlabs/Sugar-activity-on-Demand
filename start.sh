#!/bin/bash
# Launches the app outside the snap library environment (VS Code snap workaround)
exec env -i \
  HOME="$HOME" \
  PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  DISPLAY="$DISPLAY" \
  XAUTHORITY="$XAUTHORITY" \
  WAYLAND_DISPLAY="$WAYLAND_DISPLAY" \
  XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
  DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
  /usr/bin/python3 "$(dirname "$0")/main.py" "$@"
