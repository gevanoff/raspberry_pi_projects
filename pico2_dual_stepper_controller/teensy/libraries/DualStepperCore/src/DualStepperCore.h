#pragma once

#include <math.h>
#include <stdint.h>
#include <string.h>

namespace dual_stepper {

inline int32_t clampRate(int32_t rate, int32_t maximum_rate) {
  if (rate > maximum_rate) {
    return maximum_rate;
  }
  if (rate < -maximum_rate) {
    return -maximum_rate;
  }
  return rate;
}

inline const char* describeDirection(int direction) {
  if (direction > 0) {
    return "forward";
  }
  if (direction < 0) {
    return "reverse";
  }
  return "stop";
}

class StepperHardware {
 public:
  virtual ~StepperHardware() = default;
  virtual uint32_t nowMicros() const = 0;
  virtual void delayMicros(uint32_t duration_us) = 0;
  virtual void writeStep(bool active) = 0;
  virtual void writeDirection(bool forward) = 0;
  virtual void writeEnabled(bool enabled) = 0;
};

class StepDirStepper {
 public:
  StepDirStepper(StepperHardware& hardware, uint32_t pulse_width_us)
      : hardware_(hardware),
        pulse_width_us_(pulse_width_us < 2 ? 2 : pulse_width_us) {}

  void begin() {
    hardware_.writeStep(false);
    hardware_.writeEnabled(false);
    stopNow();
  }

  void setRate(int32_t steps_per_second) {
    const int32_t maximum_rate =
        static_cast<int32_t>(1000000UL / (pulse_width_us_ + 2UL));
    steps_per_second = clampRate(steps_per_second, maximum_rate > 0 ? maximum_rate : 1);
    if (steps_per_second == current_rate_) {
      return;
    }

    const int32_t previous_rate = current_rate_;
    const uint32_t previous_period_us = period_us_;
    const int previous_direction = direction_sign_;
    current_rate_ = steps_per_second;

    if (steps_per_second == 0) {
      stopNow();
      return;
    }

    const uint32_t now_us = hardware_.nowMicros();
    const bool forward = steps_per_second > 0;
    direction_sign_ = forward ? 1 : -1;
    const uint32_t absolute_rate = static_cast<uint32_t>(
        steps_per_second > 0 ? steps_per_second : -static_cast<int64_t>(steps_per_second));
    period_us_ = (1000000UL + absolute_rate - 1UL) / absolute_rate;
    if (period_us_ < pulse_width_us_ + 2UL) {
      period_us_ = pulse_width_us_ + 2UL;
    }

    if (previous_rate == 0 || previous_direction != direction_sign_ ||
        !step_scheduled_) {
      hardware_.writeStep(false);
      hardware_.writeDirection(forward);
      next_step_us_ = now_us + period_us_;
      step_scheduled_ = true;
    } else {
      const int32_t remaining_us = static_cast<int32_t>(next_step_us_ - now_us);
      if (remaining_us <= 0 || previous_period_us == 0) {
        next_step_us_ = now_us;
      } else {
        const uint32_t scaled_remaining_us = static_cast<uint32_t>(
            (static_cast<uint64_t>(remaining_us) * period_us_) / previous_period_us);
        next_step_us_ = now_us + scaled_remaining_us;
      }
    }

    hardware_.writeEnabled(true);
  }

  int update(uint32_t now_us) {
    if (current_rate_ == 0 || !step_scheduled_) {
      return 0;
    }
    if (static_cast<int32_t>(now_us - next_step_us_) < 0) {
      return 0;
    }

    const uint32_t scheduled_step_us = next_step_us_;
    hardware_.writeStep(true);
    hardware_.delayMicros(pulse_width_us_);
    hardware_.writeStep(false);
    position_steps_ += direction_sign_;

    uint32_t next_step_us = scheduled_step_us + period_us_;
    const uint32_t after_pulse_us = hardware_.nowMicros();
    if (static_cast<int32_t>(after_pulse_us - next_step_us) >= 0) {
      next_step_us = after_pulse_us + period_us_;
    }
    next_step_us_ = next_step_us;
    return direction_sign_;
  }

  int32_t currentRate() const { return current_rate_; }
  int64_t positionSteps() const { return position_steps_; }
  void setPosition(int64_t position_steps) { position_steps_ = position_steps; }

 private:
  void stopNow() {
    hardware_.writeStep(false);
    current_rate_ = 0;
    direction_sign_ = 0;
    period_us_ = 0;
    step_scheduled_ = false;
    hardware_.writeEnabled(false);
  }

  StepperHardware& hardware_;
  uint32_t pulse_width_us_;
  int32_t current_rate_ = 0;
  int direction_sign_ = 0;
  int64_t position_steps_ = 0;
  uint32_t period_us_ = 0;
  uint32_t next_step_us_ = 0;
  bool step_scheduled_ = false;
};

enum class SwitchMode {
  kEndstop,
  kJog,
  kRunEnable,
  kManualIndex,
};

class DebouncedSwitch {
 public:
  DebouncedSwitch(uint32_t debounce_ms, SwitchMode mode)
      : debounce_ms_(debounce_ms), mode_(mode) {}

  void reset(bool pressed, uint32_t now_ms) {
    stable_pressed_ = pressed;
    last_raw_pressed_ = pressed;
    last_change_ms_ = now_ms;
    pressed_edge_ = false;
  }

  void update(bool raw_pressed, uint32_t now_ms) {
    if (raw_pressed != last_raw_pressed_) {
      last_raw_pressed_ = raw_pressed;
      last_change_ms_ = now_ms;
    }
    if (stable_pressed_ == last_raw_pressed_) {
      return;
    }

    const bool change_is_immediate =
        (mode_ == SwitchMode::kEndstop && raw_pressed) ||
        ((mode_ == SwitchMode::kJog || mode_ == SwitchMode::kRunEnable ||
          mode_ == SwitchMode::kManualIndex) &&
         !raw_pressed);
    if (change_is_immediate ||
        static_cast<uint32_t>(now_ms - last_change_ms_) >= debounce_ms_) {
      if (raw_pressed) {
        pressed_edge_ = true;
      }
      stable_pressed_ = raw_pressed;
    }
  }

  bool pressed() const { return stable_pressed_; }

  bool consumePressedEdge() {
    const bool result = pressed_edge_;
    pressed_edge_ = false;
    return result;
  }

 private:
  uint32_t debounce_ms_;
  SwitchMode mode_;
  bool stable_pressed_ = false;
  bool last_raw_pressed_ = false;
  uint32_t last_change_ms_ = 0;
  bool pressed_edge_ = false;
};

class AxisController {
 public:
  AxisController(const char* name, StepDirStepper& stepper, int32_t default_rate,
                 int32_t maximum_rate, int32_t acceleration,
                 uint32_t maximum_control_dt_us)
      : name_(name),
        stepper_(stepper),
        default_rate_(default_rate),
        maximum_rate_(maximum_rate),
        acceleration_(acceleration),
        maximum_control_dt_us_(maximum_control_dt_us),
        move_rate_(default_rate) {}

  void stop() {
    has_external_rate_ = false;
    serial_rate_ = 0;
    has_move_target_ = false;
    move_rate_ = default_rate_;
    ramped_rate_ = 0.0;
    stepper_.setRate(0);
  }

  void setExternalRate(int32_t rate) {
    external_rate_ = clampRate(rate, maximum_rate_);
    has_external_rate_ = true;
  }

  void clearExternalRate() { has_external_rate_ = false; }

  void setSerialRate(int32_t rate) {
    has_move_target_ = false;
    move_rate_ = default_rate_;
    serial_rate_ = clampRate(rate, maximum_rate_);
  }

  void moveRelative(int64_t delta_steps, int32_t rate = 0) {
    moveRelativeInternal(delta_steps, rate, false);
  }

  void queueRelative(int64_t delta_steps, int32_t rate = 0) {
    moveRelativeInternal(delta_steps, rate, true);
  }

  void zeroPosition() {
    has_move_target_ = false;
    stepper_.setPosition(0);
  }

  int32_t desiredRate(int jog_direction) {
    if (has_move_target_) {
      const int64_t current_position = stepper_.positionSteps();
      if (current_position == move_target_position_) {
        has_move_target_ = false;
        return 0;
      }
      const uint64_t distance = current_position < move_target_position_
                                    ? static_cast<uint64_t>(move_target_position_ - current_position)
                                    : static_cast<uint64_t>(current_position - move_target_position_);
      int32_t braking_rate = static_cast<int32_t>(
          sqrt(2.0 * static_cast<double>(acceleration_) * static_cast<double>(distance)));
      if (braking_rate < 1) {
        braking_rate = 1;
      }
      const int32_t selected_rate = move_rate_ < braking_rate ? move_rate_ : braking_rate;
      return move_target_position_ > current_position ? selected_rate : -selected_rate;
    }
    if (has_external_rate_) {
      return external_rate_;
    }
    if (serial_rate_ != 0) {
      return serial_rate_;
    }
    if (jog_direction == 0) {
      return 0;
    }
    return jog_direction * default_rate_;
  }

  void update(uint32_t now_us, uint32_t dt_us, int jog_direction = 0,
              bool negative_limit_active = false,
              bool positive_limit_active = false) {
    int32_t desired_rate = desiredRate(jog_direction);
    if (negative_limit_active && desired_rate < 0) {
      stopForLimit(-1);
      desired_rate = 0;
    }
    if (positive_limit_active && desired_rate > 0) {
      stopForLimit(1);
      desired_rate = 0;
    }
    if (negative_limit_active && ramped_rate_ < 0) {
      stopForLimit(-1);
    }
    if (positive_limit_active && ramped_rate_ > 0) {
      stopForLimit(1);
    }

    if (dt_us > maximum_control_dt_us_) {
      dt_us = maximum_control_dt_us_;
    }
    const double maximum_rate_delta =
        (static_cast<double>(acceleration_) * dt_us) / 1000000.0;
    double ramp_target_rate = static_cast<double>(desired_rate);
    if (ramped_rate_ * desired_rate < 0) {
      ramp_target_rate = 0.0;
    }
    const double rate_error = ramp_target_rate - ramped_rate_;
    if (rate_error > maximum_rate_delta) {
      ramped_rate_ += maximum_rate_delta;
    } else if (rate_error < -maximum_rate_delta) {
      ramped_rate_ -= maximum_rate_delta;
    } else {
      ramped_rate_ = ramp_target_rate;
    }
    if (ramped_rate_ > -0.5 && ramped_rate_ < 0.5) {
      ramped_rate_ = 0.0;
    }

    const int32_t integer_rate = static_cast<int32_t>(
        ramped_rate_ >= 0.0 ? ramped_rate_ + 0.5 : ramped_rate_ - 0.5);
    stepper_.setRate(integer_rate);
    const int step_delta = stepper_.update(now_us);
    if (step_delta == 0 || !has_move_target_) {
      return;
    }
    const int64_t position = stepper_.positionSteps();
    if ((step_delta > 0 && position >= move_target_position_) ||
        (step_delta < 0 && position <= move_target_position_)) {
      stop();
    }
  }

  const char* name() const { return name_; }
  int32_t defaultRate() const { return default_rate_; }
  int32_t maximumRate() const { return maximum_rate_; }
  int32_t serialRate() const { return serial_rate_; }
  int32_t moveRate() const { return move_rate_; }
  double rampedRate() const { return ramped_rate_; }
  bool hasExternalRate() const { return has_external_rate_; }
  int32_t externalRate() const { return external_rate_; }
  bool hasMoveTarget() const { return has_move_target_; }
  int64_t moveTargetPosition() const { return move_target_position_; }
  int32_t currentRate() const { return stepper_.currentRate(); }
  int64_t positionSteps() const { return stepper_.positionSteps(); }

 private:
  void moveRelativeInternal(int64_t delta_steps, int32_t rate, bool queue) {
    if (delta_steps == 0) {
      if (!queue) {
        stop();
      }
      return;
    }
    int64_t absolute_rate = rate;
    if (absolute_rate < 0) {
      absolute_rate = -absolute_rate;
    }
    if (absolute_rate == 0) {
      absolute_rate = default_rate_;
    }
    if (absolute_rate > maximum_rate_) {
      absolute_rate = maximum_rate_;
    }

    serial_rate_ = 0;
    move_rate_ = static_cast<int32_t>(absolute_rate);
    if (queue && has_move_target_) {
      move_target_position_ += delta_steps;
    } else {
      move_target_position_ = stepper_.positionSteps() + delta_steps;
      has_move_target_ = true;
    }
  }

  void stopForLimit(int direction) {
    if (static_cast<int64_t>(serial_rate_) * direction > 0) {
      serial_rate_ = 0;
    }
    if (has_move_target_) {
      const int64_t distance = move_target_position_ - stepper_.positionSteps();
      if (distance * direction > 0) {
        has_move_target_ = false;
      }
    }
    if (ramped_rate_ * direction > 0 ||
        static_cast<int64_t>(stepper_.currentRate()) * direction > 0) {
      ramped_rate_ = 0.0;
      stepper_.setRate(0);
    }
  }

  const char* name_;
  StepDirStepper& stepper_;
  int32_t default_rate_;
  int32_t maximum_rate_;
  int32_t acceleration_;
  uint32_t maximum_control_dt_us_;
  bool has_external_rate_ = false;
  int32_t external_rate_ = 0;
  int32_t serial_rate_ = 0;
  bool has_move_target_ = false;
  int64_t move_target_position_ = 0;
  int32_t move_rate_;
  double ramped_rate_ = 0.0;
};

class ShuttleController {
 public:
  ShuttleController(AxisController& carriage_axis, AxisController& chuck_axis,
                    DebouncedSwitch& negative_endstop,
                    DebouncedSwitch& positive_endstop,
                    DebouncedSwitch& run_enable,
                    DebouncedSwitch& manual_index, int32_t carriage_rate,
                    int32_t chuck_index_steps, int32_t chuck_index_rate,
                    int chuck_index_direction)
      : carriage_axis_(carriage_axis),
        chuck_axis_(chuck_axis),
        negative_endstop_(negative_endstop),
        positive_endstop_(positive_endstop),
        run_enable_(run_enable),
        manual_index_(manual_index),
        carriage_rate_(carriage_rate),
        chuck_index_steps_(chuck_index_steps),
        chuck_index_rate_(chuck_index_rate),
        chuck_index_direction_(chuck_index_direction >= 0 ? 1 : -1) {}

  void resetFromInputs() {
    auto_enabled_ = false;
    current_direction_ = 1;
    run_switch_armed_ = !run_enable_.pressed();
    run_fault_latched_ = run_enable_.pressed();
    last_reversal_source_ = "startup";
    carriage_axis_.stop();
    chuck_axis_.stop();
  }

  const char* start() {
    if (!run_enable_.pressed()) {
      return "run-enable switch is in Stop";
    }
    if (run_fault_latched_) {
      return "cycle the run-enable switch through Stop to clear the fault";
    }
    if (!run_switch_armed_) {
      return "cycle the run-enable switch through Stop before starting";
    }
    if (negative_endstop_.pressed() && positive_endstop_.pressed()) {
      pauseForEndstopFault("both_endstops");
      return "both carriage endstops are active";
    }
    if (current_direction_ < 0 && negative_endstop_.pressed()) {
      current_direction_ = 1;
    } else if (current_direction_ > 0 && positive_endstop_.pressed()) {
      current_direction_ = -1;
    }

    carriage_axis_.stop();
    auto_enabled_ = true;
    run_switch_armed_ = false;
    carriage_axis_.setExternalRate(current_direction_ * carriage_rate_);
    return nullptr;
  }

  void pause() {
    auto_enabled_ = false;
    carriage_axis_.clearExternalRate();
  }

  const char* reverse() {
    const int new_direction = -current_direction_;
    if (new_direction < 0 && negative_endstop_.pressed()) {
      return "negative carriage endstop is active";
    }
    if (new_direction > 0 && positive_endstop_.pressed()) {
      return "positive carriage endstop is active";
    }
    current_direction_ = new_direction;
    last_reversal_source_ = "manual";
    if (auto_enabled_) {
      carriage_axis_.setExternalRate(current_direction_ * carriage_rate_);
    }
    return nullptr;
  }

  void indexChuck(int64_t steps, int32_t rate) {
    chuck_axis_.queueRelative(steps, rate);
  }

  void indexChuck() {
    indexChuck(static_cast<int64_t>(chuck_index_steps_) * chuck_index_direction_,
               chuck_index_rate_);
  }

  void stopAll() {
    auto_enabled_ = false;
    carriage_axis_.stop();
    chuck_axis_.stop();
  }

  void service() {
    const bool negative_edge = negative_endstop_.consumePressedEdge();
    const bool positive_edge = positive_endstop_.consumePressedEdge();
    const bool run_edge = run_enable_.consumePressedEdge();

    if (!run_enable_.pressed()) {
      run_switch_armed_ = true;
      run_fault_latched_ = false;
      stopFromRunSwitch();
    } else if (run_edge && run_switch_armed_ && !auto_enabled_) {
      const char* error = start();
      if (error != nullptr) {
        run_switch_armed_ = false;
      }
    }

    const bool manual_index_edge = manual_index_.consumePressedEdge();
    if (auto_enabled_) {
      if (negative_endstop_.pressed() && positive_endstop_.pressed()) {
        pauseForEndstopFault("both_endstops");
      } else if (current_direction_ < 0) {
        if (positive_edge) {
          pauseForEndstopFault("switch_14_positive_endstop");
        } else if (negative_edge) {
          handleReversal("switch_13_negative_endstop");
        }
      } else if (current_direction_ > 0) {
        if (negative_edge) {
          pauseForEndstopFault("switch_13_negative_endstop");
        } else if (positive_edge) {
          handleReversal("switch_14_positive_endstop");
        }
      }
    }

    if (manual_index_edge && runAllowsMotion()) {
      indexChuck();
    }
    if (auto_enabled_) {
      carriage_axis_.setExternalRate(current_direction_ * carriage_rate_);
    } else {
      carriage_axis_.clearExternalRate();
    }
  }

  bool autoEnabled() const { return auto_enabled_; }
  int currentDirection() const { return current_direction_; }
  bool runSwitchArmed() const { return run_switch_armed_; }
  bool runFaultLatched() const { return run_fault_latched_; }
  int32_t carriageRate() const { return carriage_rate_; }
  int32_t indexSteps() const { return chuck_index_steps_ * chuck_index_direction_; }
  int32_t indexRate() const { return chuck_index_rate_; }
  const char* lastReversalSource() const { return last_reversal_source_; }
  bool runAllowsMotion() const {
    return run_enable_.pressed() && !run_fault_latched_;
  }
  AxisController& carriageAxis() { return carriage_axis_; }
  AxisController& chuckAxis() { return chuck_axis_; }

 private:
  void handleReversal(const char* source_name) {
    current_direction_ *= -1;
    last_reversal_source_ = source_name;
    if (auto_enabled_) {
      carriage_axis_.setExternalRate(current_direction_ * carriage_rate_);
    }
    if (chuck_index_steps_ != 0) {
      indexChuck();
    }
  }

  void pauseForEndstopFault(const char* source_name) {
    auto_enabled_ = false;
    run_switch_armed_ = false;
    run_fault_latched_ = true;
    carriage_axis_.clearExternalRate();
    if (strcmp(source_name, "both_endstops") == 0) {
      last_reversal_source_ = "fault:both_endstops";
    } else if (strcmp(source_name, "switch_13_negative_endstop") == 0) {
      last_reversal_source_ = "fault:switch_13_negative_endstop";
    } else {
      last_reversal_source_ = "fault:switch_14_positive_endstop";
    }
  }

  void stopFromRunSwitch() {
    auto_enabled_ = false;
    carriage_axis_.stop();
    chuck_axis_.stop();
    last_reversal_source_ = "run_switch_stop";
  }

  AxisController& carriage_axis_;
  AxisController& chuck_axis_;
  DebouncedSwitch& negative_endstop_;
  DebouncedSwitch& positive_endstop_;
  DebouncedSwitch& run_enable_;
  DebouncedSwitch& manual_index_;
  int32_t carriage_rate_;
  int32_t chuck_index_steps_;
  int32_t chuck_index_rate_;
  int chuck_index_direction_;
  bool auto_enabled_ = false;
  int current_direction_ = 1;
  bool run_switch_armed_ = true;
  bool run_fault_latched_ = false;
  const char* last_reversal_source_ = "startup";
};

}  // namespace dual_stepper
