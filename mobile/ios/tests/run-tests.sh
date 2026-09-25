#!/bin/sh
set -eu
IOS_ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
xcrun swiftc "$IOS_ROOT/AgentStudioMobile/DownloadHistory.swift" \
  "$IOS_ROOT/tests/DownloadHistoryTests.swift" -o "$TEST_DIR/history-tests"
"$TEST_DIR/history-tests"

# Type-check the actual WebKit download delegate against the iOS SDK without Pods.
xcrun --sdk iphonesimulator swiftc -typecheck -swift-version 5 \
  -sdk "$(xcrun --sdk iphonesimulator --show-sdk-path)" \
  -target "$(uname -m)-apple-ios15.1-simulator" \
  "$IOS_ROOT/AgentStudioMobile/DownloadHistory.swift" \
  "$IOS_ROOT/AgentStudioMobile/WebDownloadManager.swift"

# Verify build defaults and the Metro opt-in without invoking a full Xcode build.
mkdir -p "$TEST_DIR/react-native/scripts"
cat > "$TEST_DIR/react-native/scripts/react-native-xcode.sh" <<'SCRIPT'
test "${SKIP_BUNDLING:-}" = "$EXPECTED_SKIP"
test "${FORCE_BUNDLING:-}" = "$EXPECTED_FORCE"
SCRIPT
for configuration in Debug Release; do
  for metro in NO YES; do
    if [ "$configuration/$metro" = "Debug/YES" ]; then
      skip=1; force=
    else
      skip=; force=1
    fi
    CONFIGURATION="$configuration" AGENT_STUDIO_USE_METRO="$metro" \
      EXPECTED_SKIP="$skip" EXPECTED_FORCE="$force" \
      SKIP_BUNDLING=stale FORCE_BUNDLING=stale REACT_NATIVE_PATH="$TEST_DIR/react-native" \
      /bin/sh "$IOS_ROOT/bundle-javascript.sh"
  done
done
echo 'iOS delegate type-check and Debug/Release bundling modes passed.'
