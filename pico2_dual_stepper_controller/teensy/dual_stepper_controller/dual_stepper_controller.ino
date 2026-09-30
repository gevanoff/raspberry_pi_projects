#include <Arduino.h>

#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>

#include "controller_config.h"
#include <DualStepperCore.h>

using controller_config::AxisConfig;
using dual_stepper::AxisController;
using dual_stepper::DebouncedSwitch;
using dual_stepper::ShuttleController;
using dual_stepper::StepDirStepper;
using dual_stepper::StepperHardware;
using dual_stepper::SwitchMode;

namespace {

class ArduinoStepperHardware final : public StepperHardware {
 public:
  explicit ArduinoStepperHardware(const AxisConfig& config) : config_(config) {}

  void begin() {
    // Preload each output latch before changing the pin mode. ENABLE is made
    // inactive first; the external two-stage sink also defaults to disabled.
    digitalWrite(config_.step_pin, physicalLevel(false, config_.step_output_active_high));
    pinMode(config_.step_pin, OUTPUT);
    digitalWrite(config_.direction_pin,
                 physicalLevel(false, config_.direction_output_high_is_forward));
    pinMode(config_.direction_pin, OUTPUT);
    digitalWrite(config_.enable_pin,
                 physicalLevel(false, config_.enable_output_active_high));
    pinMode(config_.enable_pin, OUTPUT);
  }

  uint32_t nowMicros() const override { return micros(); }
  void delayMicros(uint32_t duration_us) override { delayMicroseconds(duration_us); }

  void writeStep(bool active) override {
    digitalWrite(config_.step_pin, physicalLevel(active, config_.step_output_active_high));
  }

  void writeDirection(bool forward) override {
    digitalWrite(config_.direction_pin,
                 physicalLevel(forward, config_.direction_output_high_is_forward));
  }

  void writeEnabled(bool enabled) override {
    digitalWrite(config_.enable_pin,
                 physicalLevel(enabled, config_.enable_output_active_high));
  }

 private:
  static uint8_t physicalLevel(bool active, bool active_high) {
    return active == active_high ? HIGH : LOW;
  }

  const AxisConfig& config_;
};

class HardwareSwitch {
 public:
  HardwareSwitch(uint8_t pin, bool active_low, uint32_t debounce_ms, SwitchMode mode)
      : pin_(pin),
        active_low_(active_low),
        debounced_(debounce_ms, mode) {}

  void begin() {
    pinMode(pin_, INPUT_PULLUP);
    debounced_.reset(readPressed(), millis());
  }

  void update(uint32_t now_ms) { debounced_.update(readPressed(), now_ms); }
  DebouncedSwitch& state() { return debounced_; }

 private:
  bool readPressed() const {
    const bool pin_high = digitalRead(pin_) != LOW;
    return active_low_ ? !pin_high : pin_high;
  }

  uint8_t pin_;
  bool active_low_;
  DebouncedSwitch debounced_;
};

ArduinoStepperHardware motor_a_hardware(controller_config::kMotorA);
ArduinoStepperHardware motor_b_hardware(controller_config::kMotorB);
StepDirStepper motor_a_stepper(motor_a_hardware, controller_config::kStepPulseUs);
StepDirStepper motor_b_stepper(motor_b_hardware, controller_config::kStepPulseUs);
AxisController motor_a(
    "motor_a", motor_a_stepper, controller_config::kMotorA.default_steps_per_second,
    controller_config::kMotorA.maximum_steps_per_second,
    controller_config::kMotorA.acceleration_steps_per_second_squared,
    controller_config::kMaximumControlDtUs);
AxisController motor_b(
    "motor_b", motor_b_stepper, controller_config::kMotorB.default_steps_per_second,
    controller_config::kMotorB.maximum_steps_per_second,
    controller_config::kMotorB.acceleration_steps_per_second_squared,
    controller_config::kMaximumControlDtUs);

HardwareSwitch stop_go(controller_config::kStopGoPin,
                       controller_config::kStopGoActiveLow,
                       controller_config::kSwitchDebounceMs,
                       SwitchMode::kRunEnable);
HardwareSwitch manual_index(controller_config::kManualIndexPin,
                            controller_config::kManualIndexActiveLow,
                            controller_config::kSwitchDebounceMs,
                            SwitchMode::kManualIndex);
HardwareSwitch negative_endstop(controller_config::kNegativeEndstopPin,
                                controller_config::kNegativeEndstopActiveLow,
                                controller_config::kSwitchDebounceMs,
                                SwitchMode::kEndstop);
HardwareSwitch positive_endstop(controller_config::kPositiveEndstopPin,
                                controller_config::kPositiveEndstopActiveLow,
                                controller_config::kSwitchDebounceMs,
                                SwitchMode::kEndstop);

ShuttleController shuttle(
    motor_a, motor_b, negative_endstop.state(), positive_endstop.state(),
    stop_go.state(), manual_index.state(),
    controller_config::kCarriageRunStepsPerSecond,
    controller_config::kCarriageStartDirection, controller_config::kChuckIndexSteps,
    controller_config::kChuckIndexRate,
    controller_config::kChuckIndexDirection);

char command_buffer[controller_config::kMaximumCommandLength + 1] = {};
size_t command_length = 0;
bool discard_command_line = false;
uint32_t previous_loop_us = 0;

const char* boolText(bool value) { return value ? "true" : "false"; }

bool parseInt32(const char* text, int32_t& result) {
  if (text == nullptr || *text == '\0') {
    return false;
  }
  errno = 0;
  char* end = nullptr;
  const long value = strtol(text, &end, 10);
  if (errno == ERANGE || end == text || *end != '\0' || value < INT32_MIN ||
      value > INT32_MAX) {
    return false;
  }
  result = static_cast<int32_t>(value);
  return true;
}

bool parseInt64(const char* text, int64_t& result) {
  if (text == nullptr || *text == '\0') {
    return false;
  }
  errno = 0;
  char* end = nullptr;
  const long long value = strtoll(text, &end, 10);
  if (errno == ERANGE || end == text || *end != '\0') {
    return false;
  }
  result = static_cast<int64_t>(value);
  return true;
}

AxisController* findAxis(const char* name) {
  if (strcmp(name, "a") == 0 || strcmp(name, "motor_a") == 0) {
    return &motor_a;
  }
  if (strcmp(name, "b") == 0 || strcmp(name, "motor_b") == 0) {
    return &motor_b;
  }
  return nullptr;
}

bool parseDirection(const char* token, int& direction) {
  if (strcmp(token, "forward") == 0 || strcmp(token, "fwd") == 0 ||
      strcmp(token, "+") == 0 || strcmp(token, "positive") == 0 ||
      strcmp(token, "pos") == 0) {
    direction = 1;
    return true;
  }
  if (strcmp(token, "reverse") == 0 || strcmp(token, "rev") == 0 ||
      strcmp(token, "-") == 0 || strcmp(token, "negative") == 0 ||
      strcmp(token, "neg") == 0) {
    direction = -1;
    return true;
  }
  if (strcmp(token, "stop") == 0 || strcmp(token, "0") == 0) {
    direction = 0;
    return true;
  }
  return false;
}

const char* requireRunEnable() {
  if (!stop_go.state().pressed()) {
    return "run-enable switch is in Stop";
  }
  if (shuttle.runFaultLatched()) {
    return "cycle the run-enable switch through Stop to clear the fault";
  }
  return nullptr;
}

const char* requireManualAxisControl(AxisController& axis) {
  const char* error = requireRunEnable();
  if (error != nullptr) {
    return error;
  }
  if (&axis == &shuttle.carriageAxis() && shuttle.autoEnabled()) {
    return "pause the shuttle before controlling the carriage axis";
  }
  return nullptr;
}

const char* axisMode(const AxisController& axis) {
  if (axis.hasMoveTarget()) {
    return "move";
  }
  if (axis.hasExternalRate() && axis.externalRate() != 0) {
    return "auto";
  }
  if (axis.serialRate() != 0) {
    return "serial";
  }
  return "idle";
}

void printAxisStatus(const AxisController& axis, bool negative_limit,
                     bool positive_limit) {
  Serial.printf("%s mode=%s pos=%lld rate=%ld target=", axis.name(),
                axisMode(axis), static_cast<long long>(axis.positionSteps()),
                static_cast<long>(axis.currentRate()));
  if (axis.hasMoveTarget()) {
    Serial.printf("%lld", static_cast<long long>(axis.moveTargetPosition()));
  } else {
    Serial.print('-');
  }
  Serial.printf(" min_limit=%s max_limit=%s\r\n", boolText(negative_limit),
                boolText(positive_limit));
}

void printStatus() {
  Serial.printf(
      "shuttle enabled=%s direction=%s run_enable=%s run_armed=%s "
      "run_fault=%s carriage_rate=%ld index_steps=%ld index_rate=%ld "
      "last_reversal=%s\r\n",
      boolText(shuttle.autoEnabled()),
      dual_stepper::describeDirection(shuttle.currentDirection()),
      boolText(stop_go.state().pressed()), boolText(shuttle.runSwitchArmed()),
      boolText(shuttle.runFaultLatched()),
      static_cast<long>(shuttle.carriageRate()),
      static_cast<long>(shuttle.indexSteps()),
      static_cast<long>(shuttle.indexRate()), shuttle.lastReversalSource());

  bool any_switch = false;
  Serial.print("switches active=");
  const struct {
    const char* name;
    DebouncedSwitch* state;
  } switches[] = {
      {"switch_11_stop_go", &stop_go.state()},
      {"switch_12_manual_index", &manual_index.state()},
      {"switch_13_negative_endstop", &negative_endstop.state()},
      {"switch_14_positive_endstop", &positive_endstop.state()},
  };
  for (const auto& item : switches) {
    if (!item.state->pressed()) {
      continue;
    }
    if (any_switch) {
      Serial.print(',');
    }
    Serial.print(item.name);
    any_switch = true;
  }
  if (!any_switch) {
    Serial.print("none");
  }
  Serial.print("\r\n");

  printAxisStatus(motor_a, negative_endstop.state().pressed(),
                  positive_endstop.state().pressed());
  printAxisStatus(motor_b, false, false);
}

void printHelp() {
  Serial.print("help: start | pause | reverse | index [steps] [rate]\r\n");
  Serial.print("help: status | stop | rate <axis> <steps_per_second>\r\n");
  Serial.print("help: jog <axis> <forward|reverse|stop> [rate]\r\n");
  Serial.print("help: move <axis> <delta_steps> [rate] | zero <axis>\r\n");
}

void printError(const char* message) {
  Serial.print("error ");
  Serial.print(message);
  Serial.print("\r\n");
}

void handleCommand(char* command_line) {
  char* tokens[5] = {};
  size_t token_count = 0;
  char* context = nullptr;
  for (char* token = strtok_r(command_line, " \t", &context); token != nullptr;
       token = strtok_r(nullptr, " \t", &context)) {
    if (token_count == 5) {
      printError("too many command arguments");
      return;
    }
    for (char* character = token; *character != '\0'; ++character) {
      if (*character >= 'A' && *character <= 'Z') {
        *character = static_cast<char>(*character - 'A' + 'a');
      }
    }
    tokens[token_count++] = token;
  }
  if (token_count == 0) {
    return;
  }

  const char* command = tokens[0];
  if ((strcmp(command, "help") == 0 || strcmp(command, "?") == 0) &&
      token_count == 1) {
    printHelp();
    return;
  }
  if (strcmp(command, "status") == 0 && token_count == 1) {
    printStatus();
    return;
  }
  if (strcmp(command, "start") == 0 && token_count == 1) {
    const char* error = shuttle.start();
    if (error != nullptr) {
      printError(error);
    } else {
      Serial.print("ok start\r\n");
    }
    return;
  }
  if (strcmp(command, "pause") == 0 && token_count == 1) {
    shuttle.pause();
    Serial.print("ok pause\r\n");
    return;
  }
  if (strcmp(command, "reverse") == 0 && token_count == 1) {
    const char* error = shuttle.reverse();
    if (error != nullptr) {
      printError(error);
    } else {
      Serial.printf("ok reverse %s\r\n",
                    dual_stepper::describeDirection(shuttle.currentDirection()));
    }
    return;
  }
  if (strcmp(command, "stop") == 0 && token_count == 1) {
    shuttle.stopAll();
    Serial.print("ok stop\r\n");
    return;
  }
  if (strcmp(command, "index") == 0 && token_count >= 1 && token_count <= 3) {
    const char* error = requireRunEnable();
    if (error != nullptr) {
      printError(error);
      return;
    }
    int64_t steps = controller_config::kChuckIndexSteps *
                    controller_config::kChuckIndexDirection;
    int32_t rate = controller_config::kChuckIndexRate;
    if ((token_count >= 2 && !parseInt64(tokens[1], steps)) ||
        (token_count == 3 && !parseInt32(tokens[2], rate))) {
      printError("invalid numeric argument");
      return;
    }
    if (steps < -controller_config::kMaximumCommandedMoveSteps ||
        steps > controller_config::kMaximumCommandedMoveSteps) {
      printError("move distance is out of range");
      return;
    }
    shuttle.indexChuck(steps, rate);
    Serial.print("ok index\r\n");
    return;
  }

  if ((strcmp(command, "rate") == 0 && token_count == 3) ||
      (strcmp(command, "jog") == 0 && (token_count == 3 || token_count == 4)) ||
      (strcmp(command, "move") == 0 && (token_count == 3 || token_count == 4)) ||
      (strcmp(command, "zero") == 0 && token_count == 2)) {
    AxisController* axis = findAxis(tokens[1]);
    if (axis == nullptr) {
      printError("unknown axis");
      return;
    }
    const char* error = requireManualAxisControl(*axis);
    if (error != nullptr) {
      printError(error);
      return;
    }

    if (strcmp(command, "rate") == 0) {
      int32_t rate = 0;
      if (!parseInt32(tokens[2], rate)) {
        printError("invalid numeric argument");
        return;
      }
      axis->setSerialRate(rate);
      Serial.printf("ok rate %s %ld\r\n", axis->name(),
                    static_cast<long>(axis->serialRate()));
      return;
    }
    if (strcmp(command, "jog") == 0) {
      int direction = 0;
      if (!parseDirection(tokens[2], direction)) {
        printError("unknown direction");
        return;
      }
      int32_t rate = axis->defaultRate();
      if (token_count == 4 && !parseInt32(tokens[3], rate)) {
        printError("invalid numeric argument");
        return;
      }
      int64_t absolute_rate = rate;
      if (absolute_rate < 0) {
        absolute_rate = -absolute_rate;
      }
      if (absolute_rate > INT32_MAX) {
        printError("rate is out of range");
        return;
      }
      axis->setSerialRate(direction * static_cast<int32_t>(absolute_rate));
      Serial.printf("ok jog %s %s %ld\r\n", axis->name(),
                    dual_stepper::describeDirection(direction),
                    static_cast<long>(axis->serialRate() < 0 ? -axis->serialRate()
                                                             : axis->serialRate()));
      return;
    }
    if (strcmp(command, "move") == 0) {
      int64_t delta_steps = 0;
      int32_t rate = 0;
      if (!parseInt64(tokens[2], delta_steps) ||
          (token_count == 4 && !parseInt32(tokens[3], rate))) {
        printError("invalid numeric argument");
        return;
      }
      if (delta_steps < -controller_config::kMaximumCommandedMoveSteps ||
          delta_steps > controller_config::kMaximumCommandedMoveSteps) {
        printError("move distance is out of range");
        return;
      }
      axis->moveRelative(delta_steps, rate);
      Serial.printf("ok move %s delta=%lld target=", axis->name(),
                    static_cast<long long>(delta_steps));
      if (axis->hasMoveTarget()) {
        Serial.printf("%lld", static_cast<long long>(axis->moveTargetPosition()));
      } else {
        Serial.print('-');
      }
      Serial.printf(" rate=%ld\r\n", static_cast<long>(axis->moveRate()));
      return;
    }

    axis->zeroPosition();
    Serial.printf("ok zero %s\r\n", axis->name());
    return;
  }

  printError("unknown command");
}

void serviceSerial() {
  for (size_t count = 0; count < 32 && Serial.available() > 0; ++count) {
    const int value = Serial.read();
    if (value < 0) {
      return;
    }
    const char character = static_cast<char>(value);
    if (character == '\r' || character == '\n') {
      if (discard_command_line) {
        printError("command is too long");
      } else if (command_length > 0) {
        command_buffer[command_length] = '\0';
        handleCommand(command_buffer);
      }
      command_length = 0;
      discard_command_line = false;
      continue;
    }
    if (character == 3) {
      shuttle.stopAll();
      command_length = 0;
      discard_command_line = false;
      Serial.print("ok stop\r\n");
      continue;
    }
    if (character < 32 || character > 126 || discard_command_line) {
      continue;
    }
    if (command_length < controller_config::kMaximumCommandLength) {
      command_buffer[command_length++] = character;
    } else {
      command_length = 0;
      discard_command_line = true;
    }
  }
}

}  // namespace

void setup() {
  motor_a_hardware.begin();
  motor_b_hardware.begin();
  motor_a_stepper.begin();
  motor_b_stepper.begin();

  stop_go.begin();
  manual_index.begin();
  negative_endstop.begin();
  positive_endstop.begin();
  shuttle.resetFromInputs();

  Serial.begin(controller_config::kSerialBaud);
  previous_loop_us = micros();
  Serial.print("ready teensy40-dual-stepper: type 'help' for commands\r\n");
}

void loop() {
  const uint32_t now_ms = millis();
  stop_go.update(now_ms);
  manual_index.update(now_ms);
  negative_endstop.update(now_ms);
  positive_endstop.update(now_ms);

  shuttle.service();

  const uint32_t now_us = micros();
  const uint32_t dt_us = now_us - previous_loop_us;
  previous_loop_us = now_us;
  motor_a.update(now_us, dt_us, 0, negative_endstop.state().pressed(),
                 positive_endstop.state().pressed());
  motor_b.update(micros(), dt_us);

  serviceSerial();
  delayMicroseconds(controller_config::kMainLoopIdleUs);
}
