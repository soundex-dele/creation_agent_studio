#!/bin/sh
set -e

# This runs inside with-environment.sh, after .xcode.env.local is loaded.
# Both simulator and device Debug builds embed JS unless explicitly using Metro.
if [ "$CONFIGURATION" = "Debug" ] && [ "${AGENT_STUDIO_USE_METRO:-NO}" = "YES" ]; then
  export SKIP_BUNDLING=1
  unset FORCE_BUNDLING
else
  export FORCE_BUNDLING=1
  unset SKIP_BUNDLING
fi
/bin/bash "$REACT_NATIVE_PATH/scripts/react-native-xcode.sh"
