#!/bin/bash
# Copy .claude.json from host-mounted source into the container filesystem.
# A filesystem copy is immune to OrbStack inode-break on the bind mount.
if [ -f /run/host-claude.json ]; then
    cp /run/host-claude.json /home/agent/.claude.json
    chmod 600 /home/agent/.claude.json
fi
exec "$@"
