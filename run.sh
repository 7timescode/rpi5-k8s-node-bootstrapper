#!/bin/bash

# Function to display usage message
show_usage() {
  echo "Usage: $0 {config_generator|partition_manager} <device>/--help"
  echo "Example: $0 config_generator /dev/sda"
  echo "Script help: $0 config_generator --help"
  exit 1
}

# Check if the correct number of arguments is provided
if [ "$#" -lt 2 ]; then
  echo "Error: Incorrect arguments."
  show_usage
fi

# Check if the first argument is either config_generator or partition_manager
if [ "$1" != "config_generator" ] && [ "$1" != "partition_manager" ]; then
  echo "Error: Invalid script name provided."
  show_usage
fi

script_to_run="$1"
shift

run_segment="docker run --privileged -it --rm --volume $(pwd):/app/node-bootstrapper"
entrypoint_segment="--entrypoint python node-bootstrapper node_bootstrapper/$script_to_run.py"

# If a device is provided, it needs to be added as a `--device` argument.
# But if the second (first after shift) argument is "--help", it can't be passed to `--device`.
if [ "$1" != "--help" ]; then
  device_argument="--device $1:$1"
else
  device_argument=""
fi

# Combine all parts of the command
run_command="$run_segment $device_argument $entrypoint_segment $@"
echo $run_command

# Run the Docker container with the constructed command
eval $run_command
