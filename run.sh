#!/bin/bash

# Check if the device argument is provided
if [ "$1" != "--help" ] && [ -z "$1" ]; then
  echo "Error: No device provided."
  echo "Usage: $0 <device> [--system-size <size>] [--image-path <path>] [--force] [--debug] [--help]"
  exit 1
fi

# Check if --help argument is provided
if [ "$1" == "--help" ]; then
  # Run the Docker container with the help command
  docker run --privileged -it --rm \
    --volume $(pwd):/app/node-bootstrapper \
    --entrypoint python \
    node-bootstrapper \
    node_bootstrapper/disk_manager.py --help
  exit 0
fi


# Get the device from the first argument
device=$1
shift

# Initialize variables for optional arguments
system_size=""
image_path=""
force=""
debug=""
help=""

# Parse the optional arguments
while [[ "$#" -gt 0 ]]; do
  case $1 in
    --system-size)
      system_size=$2
      shift
      ;;
    --image-path)
      image_path=$2
      shift
      ;;
    --force)
      force="--force"
      ;;
    --debug)
      debug="--debug"
      ;;
    --help)
      help="--help"
      ;;
     *)
      echo "Unknown parameter passed: $1"
      exit 1
      ;;
  esac
  shift
done

# Run the Docker container with the selected device
docker_command=" docker run --privileged -it --rm --device ${device}:${device} --volume $(pwd):/app/node-bootstrapper --entrypoint python node-bootstrapper node_bootstrapper/disk_manager.py ${device}"

# Special case for `--help`
# If not `--help`, parse all other arguments
if [ -n "$system_size" ]; then
  docker_command="${docker_command} --system-size ${system_size}"
fi
if [ -n "$image_path" ]; then
  docker_command="${docker_command} --image-path ${image_path}"
fi
if [ -n "$force" ]; then
  docker_command="${docker_command} ${force}"
fi
if [ -n "$debug" ]; then
  docker_command="${docker_command} ${debug}"
fi

# Run the Docker container with the constructed command
eval $docker_command
