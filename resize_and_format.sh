#!/bin/bash

# Set device
DEVICE=/dev/mmcblk0

# Unmount all partitions
umount ${DEVICE}* || true

# Resize the filesystem on the first partition to the specified size
e2fsck -f ${DEVICE}p2
resize2fs ${DEVICE}p2 $SYSTEM_SIZE

# Resize the first partition to the specified size
parted $DEVICE --script resizepart 2 $SYSTEM_SIZE

# Create the third partition in the remaining space
parted $DEVICE --script mkpart primary $SYSTEM_SIZE 100%

# Update the partition table
partprobe $DEVICE

# Format the third partition
mkfs.ext4 ${DEVICE}p3

# Get the UUID of the new partition
UUID=$(blkid -s UUID -o value ${DEVICE}p3)

# Add the new partition to /etc/fstab
echo "UUID=$UUID /mnt/data ext4 defaults 0 2" >> /etc/fstab

# Mount the new partition
mount ${DEVICE}p3 /mnt/data
