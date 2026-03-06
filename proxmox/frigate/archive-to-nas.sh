#!/bin/bash
# Archive Frigate recordings older than 7 days to NAS
# Runs daily via cron

SRC=/media/frigate/recordings
DEST=/mnt/nfs/frigate/recordings
LOG=/var/log/frigate-archive.log

# Check NAS is mounted
if ! mountpoint -q /mnt/nfs/frigate; then
    echo "$(date) ERROR: NAS not mounted" >> $LOG
    mount /mnt/nfs/frigate 2>/dev/null || exit 1
fi

echo "$(date) Starting archive sync" >> $LOG
rsync -av --remove-source-files --include='*/' --include='*.mp4' --exclude='*'     --min-age=7d $SRC/ $DEST/ >> $LOG 2>&1

# Also archive clips/snapshots older than 14 days
rsync -av --remove-source-files --min-age=14d /media/frigate/clips/ /mnt/nfs/frigate/clips/ >> $LOG 2>&1

# Clean empty dirs
find $SRC -type d -empty -delete 2>/dev/null

echo "$(date) Archive sync complete" >> $LOG
