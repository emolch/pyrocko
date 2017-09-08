#!/bin/bash


set -e

[ ! -z "$DRONE" ] || exit 1


keypath="/tmp/rsync-key-$$"

umask 0077
echo "$RSYNC_KEY" > "$keypath"
umask 0022

temppath="/tmp/rsync-temp-$$"

target="${@: -1}"
mkdir -p "$temppath/$target"

rsync -av "${@:1:$#-1}" "$temppath/$target"
rsync -rv -e "ssh -o StrictHostKeyChecking=no -i $keypath" "$temppath/" "${RSYNC_USER}@${RSYNC_HOST}:"

rm "$keypath"
