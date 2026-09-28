#pragma once

#include <array>
#include <stdint.h>

namespace controller_config {

struct AxisConfig {
  uint8_t step_pin;
  uint8_t direction_pin;
  uint8_t enable_pin;
  bool step_output_active_high;
  bool direction_output_high_is_forward;
  bool enable_output_active_high;
  int32_t default_steps_per_second;
  int32_t maximum_steps_per_second;
  int32_t acceleration_steps_per_second_squared;
};

// These output polarities assume the documented common-anode interface:
// - STEP and DIR each use one non-inverting low-side sink channel.
// - ENABLE uses two cascaded sink channels so LOW or a floating Teensy output
//   disables the driver, while HIGH enables it.
constexpr AxisConfig kMotorA = {
    2, 3, 4, true, true, true, 450, 650, 1200,
};
constexpr AxisConfig kMotorB = {
    6, 7, 8, true, true, true, 180, 500, 1500,
};

// The physical switch labels remain 11 through 14, but Teensy pins 14 through
// 17 are used. Teensy pin 13 is deliberately avoided because it drives the
// onboard LED and is a poor choice for an INPUT_PULLUP switch.
constexpr uint8_t kStopGoPin = 14;          // switch labeled 11
constexpr uint8_t kManualIndexPin = 15;     // switch labeled 12
constexpr uint8_t kNegativeEndstopPin = 16; // switch labeled 13
constexpr uint8_t kPositiveEndstopPin = 17; // switch labeled 14

constexpr bool kStopGoActiveLow = true;
constexpr bool kManualIndexActiveLow = true;
constexpr bool kNegativeEndstopActiveLow = true;
constexpr bool kPositiveEndstopActiveLow = true;

constexpr int32_t kCarriageRunStepsPerSecond = 450;
constexpr int kCarriageStartDirection = 1;
constexpr int32_t kChuckIndexSteps = 120;
constexpr int32_t kChuckIndexRate = 220;
constexpr int kChuckIndexDirection = 1;

constexpr uint32_t kStepPulseUs = 20;
constexpr uint32_t kSwitchDebounceMs = 25;
constexpr uint32_t kMainLoopIdleUs = 100;
constexpr uint32_t kMaximumControlDtUs = 50000;
constexpr size_t kMaximumCommandLength = 120;
constexpr int64_t kMaximumCommandedMoveSteps = 1000000000LL;
constexpr unsigned long kSerialBaud = 115200;

constexpr std::array<uint8_t, 10> kUsedPins = {
    kMotorA.step_pin,
    kMotorA.direction_pin,
    kMotorA.enable_pin,
    kMotorB.step_pin,
    kMotorB.direction_pin,
    kMotorB.enable_pin,
    kStopGoPin,
    kManualIndexPin,
    kNegativeEndstopPin,
    kPositiveEndstopPin,
};

constexpr bool pinsAreUnique() {
  for (size_t first = 0; first < kUsedPins.size(); ++first) {
    for (size_t second = first + 1; second < kUsedPins.size(); ++second) {
      if (kUsedPins[first] == kUsedPins[second]) {
        return false;
      }
    }
  }
  return true;
}

static_assert(pinsAreUnique(), "each controller signal must use a unique pin");
static_assert(kMotorA.default_steps_per_second > 0 &&
                  kMotorA.default_steps_per_second <= kMotorA.maximum_steps_per_second,
              "motor A default rate must be within its configured limit");
static_assert(kMotorB.default_steps_per_second > 0 &&
                  kMotorB.default_steps_per_second <= kMotorB.maximum_steps_per_second,
              "motor B default rate must be within its configured limit");
static_assert(kCarriageRunStepsPerSecond > 0 &&
                  kCarriageRunStepsPerSecond <= kMotorA.maximum_steps_per_second,
              "carriage rate must be within the motor A limit");
static_assert(kCarriageStartDirection == 1 || kCarriageStartDirection == -1,
              "carriage start direction must be +1 or -1");
static_assert(kChuckIndexRate > 0 && kChuckIndexRate <= kMotorB.maximum_steps_per_second,
              "chuck index rate must be within the motor B limit");
static_assert(kMotorA.acceleration_steps_per_second_squared > 0 &&
                  kMotorB.acceleration_steps_per_second_squared > 0,
              "axis acceleration must be positive");
static_assert(kStepPulseUs >= 2, "step pulses must be at least 2 microseconds");
static_assert(kStepPulseUs + 2 <=
                  1000000UL / static_cast<uint32_t>(kMotorA.maximum_steps_per_second),
              "step pulse is too long for the motor A maximum rate");
static_assert(kStepPulseUs + 2 <=
                  1000000UL / static_cast<uint32_t>(kMotorB.maximum_steps_per_second),
              "step pulse is too long for the motor B maximum rate");
static_assert(kMaximumControlDtUs > 0, "control time cap must be positive");
static_assert(kMaximumCommandLength >= 16, "command buffer is unexpectedly small");
static_assert(kMaximumCommandedMoveSteps > 0, "move-command limit must be positive");

}  // namespace controller_config
