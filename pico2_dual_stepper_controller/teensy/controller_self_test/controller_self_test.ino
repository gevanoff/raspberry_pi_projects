#include <Arduino.h>

#include <DualStepperCore.h>

using dual_stepper::AxisController;
using dual_stepper::DebouncedSwitch;
using dual_stepper::ShuttleController;
using dual_stepper::StepDirStepper;
using dual_stepper::StepperHardware;
using dual_stepper::SwitchMode;

namespace {

class FakeHardware final : public StepperHardware {
 public:
  uint32_t nowMicros() const override { return now_us; }
  void delayMicros(uint32_t duration_us) override { now_us += duration_us; }

  void writeStep(bool active) override {
    if (active && !step_active) {
      pulse_start_us = now_us;
      ++pulse_count;
    } else if (!active && step_active) {
      last_pulse_width_us = now_us - pulse_start_us;
    }
    step_active = active;
  }

  void writeDirection(bool forward) override { direction_forward = forward; }
  void writeEnabled(bool value) override {
    enabled = value;
    ++enable_write_count;
  }

  void advance(uint32_t duration_us) { now_us += duration_us; }

  uint32_t now_us = 0;
  uint32_t pulse_start_us = 0;
  uint32_t last_pulse_width_us = 0;
  uint32_t pulse_count = 0;
  uint32_t enable_write_count = 0;
  bool step_active = false;
  bool direction_forward = false;
  bool enabled = false;
};

int passed = 0;
int failed = 0;

void check(bool condition, const char* test_name) {
  if (condition) {
    ++passed;
    Serial.printf("PASS %s\r\n", test_name);
  } else {
    ++failed;
    Serial.printf("FAIL %s\r\n", test_name);
  }
}

void testSafeEnableInitialization() {
  FakeHardware hardware;
  StepDirStepper stepper(hardware, 20);
  stepper.begin();
  check(!hardware.enabled && !hardware.step_active && stepper.currentRate() == 0,
        "safe enable initialization");
}

void testRateChangePreservesIntervalFraction() {
  FakeHardware hardware;
  StepDirStepper stepper(hardware, 20);
  stepper.begin();
  stepper.setRate(10);
  hardware.advance(50000);
  stepper.setRate(20);
  hardware.advance(24999);
  const bool early = stepper.update(hardware.nowMicros()) == 0;
  hardware.advance(1);
  const bool stepped = stepper.update(hardware.nowMicros()) == 1;
  check(early && stepped && stepper.positionSteps() == 1 &&
            hardware.last_pulse_width_us == 20,
        "rate change preserves interval fraction");
}

void testLongStallSkipsCatchUpBurst() {
  FakeHardware hardware;
  StepDirStepper stepper(hardware, 20);
  stepper.begin();
  stepper.setRate(100);
  hardware.advance(100000);
  const int first = stepper.update(hardware.nowMicros());
  const int second = stepper.update(hardware.nowMicros());
  check(first == 1 && second == 0 && hardware.pulse_count == 1,
        "long stall skips catch-up burst");
}

void testMicrosWrap() {
  FakeHardware hardware;
  hardware.now_us = UINT32_MAX - 4999U;
  StepDirStepper stepper(hardware, 20);
  stepper.begin();
  stepper.setRate(100);
  hardware.advance(9999);
  const bool early = stepper.update(hardware.nowMicros()) == 0;
  hardware.advance(1);
  const bool stepped = stepper.update(hardware.nowMicros()) == 1;
  check(early && stepped, "step deadline survives micros wrap");
}

void testAxisAccelerationAndBraking() {
  FakeHardware acceleration_hardware;
  StepDirStepper acceleration_stepper(acceleration_hardware, 20);
  acceleration_stepper.begin();
  AxisController acceleration_axis("test", acceleration_stepper, 100, 100, 100,
                                   50000);
  acceleration_axis.setSerialRate(100);
  for (int i = 0; i < 50; ++i) {
    acceleration_hardware.advance(10000);
    acceleration_axis.update(acceleration_hardware.nowMicros(), 10000);
  }
  const bool accelerated_while_stepping =
      acceleration_stepper.positionSteps() > 0 &&
      acceleration_stepper.currentRate() < 100;

  FakeHardware braking_hardware;
  StepDirStepper braking_stepper(braking_hardware, 20);
  braking_stepper.begin();
  AxisController braking_axis("test", braking_stepper, 100, 100, 100, 50000);
  braking_axis.moveRelative(1000, 100);
  braking_stepper.setPosition(998);
  const bool braking = braking_axis.desiredRate(0) == 20;
  check(accelerated_while_stepping && braking,
        "axis accelerates while stepping and brakes near target");
}

void testFractionalAccelerationProgress() {
  FakeHardware hardware;
  StepDirStepper stepper(hardware, 20);
  stepper.begin();
  AxisController axis("test", stepper, 450, 650, 1200, 50000);
  axis.setSerialRate(450);
  for (int i = 0; i < 9; ++i) {
    hardware.advance(100);
    axis.update(hardware.nowMicros(), 100);
  }
  check(axis.rampedRate() > 1.0 && stepper.currentRate() >= 1,
        "fractional acceleration accumulates across fast loop iterations");
}

void testQueuedMovesAndExactStop() {
  FakeHardware hardware;
  StepDirStepper stepper(hardware, 20);
  stepper.begin();
  AxisController axis("test", stepper, 100, 100, 1000, 50000);
  axis.queueRelative(120, 80);
  axis.queueRelative(120, 80);
  const bool queued = axis.hasMoveTarget() && axis.moveTargetPosition() == 240;
  axis.stop();
  stepper.setPosition(0);
  axis.moveRelative(25, 100);
  for (int i = 0; i < 5000 && axis.hasMoveTarget(); ++i) {
    hardware.advance(1000);
    axis.update(hardware.nowMicros(), 1000);
  }
  check(queued && stepper.positionSteps() == 25 && !axis.hasMoveTarget() &&
            stepper.currentRate() == 0,
        "queued moves are retained and finite move stops exactly");
}

void testLimitImmediateStop() {
  FakeHardware hardware;
  StepDirStepper stepper(hardware, 20);
  stepper.begin();
  AxisController axis("test", stepper, 100, 100, 1000, 50000);
  axis.moveRelative(-100, 100);
  hardware.advance(50000);
  axis.update(hardware.nowMicros(), 50000);
  const bool was_moving = stepper.currentRate() < 0;
  hardware.advance(1000);
  axis.update(hardware.nowMicros(), 1000, 0, true, false);
  check(was_moving && stepper.currentRate() == 0 && !axis.hasMoveTarget(),
        "active limit immediately stops motion into limit");
}

void testDirectionChangeStopsFirst() {
  FakeHardware hardware;
  StepDirStepper stepper(hardware, 20);
  stepper.begin();
  AxisController axis("test", stepper, 100, 100, 1000, 50000);
  axis.setSerialRate(10);
  hardware.advance(50000);
  axis.update(hardware.nowMicros(), 50000);
  axis.setSerialRate(-100);
  hardware.advance(50000);
  axis.update(hardware.nowMicros(), 50000);
  const bool stopped = stepper.currentRate() == 0;
  hardware.advance(1000);
  axis.update(hardware.nowMicros(), 1000);
  check(stopped && stepper.currentRate() < 0,
        "direction reversal passes through stopped update");
}

void testAsymmetricDebounce() {
  DebouncedSwitch endstop(25, SwitchMode::kEndstop);
  endstop.reset(false, 0);
  endstop.update(true, 0);
  const bool asserted_immediately = endstop.pressed() && endstop.consumePressedEdge();
  endstop.update(false, 0);
  const bool release_held = endstop.pressed();
  endstop.update(false, 25);

  DebouncedSwitch run(25, SwitchMode::kRunEnable);
  run.reset(false, 0);
  run.update(true, 0);
  const bool go_debounced = !run.pressed();
  run.update(true, 25);
  const bool go_accepted = run.pressed();
  run.update(false, 25);
  const bool stop_immediate = !run.pressed();

  check(asserted_immediately && release_held && !endstop.pressed() &&
            go_debounced && go_accepted && stop_immediate,
        "endstop and run switch use asymmetric safety debounce");
}

struct ShuttleFixture {
  FakeHardware carriage_hardware;
  FakeHardware chuck_hardware;
  StepDirStepper carriage_stepper{carriage_hardware, 20};
  StepDirStepper chuck_stepper{chuck_hardware, 20};
  AxisController carriage{"motor_a", carriage_stepper, 450, 650, 1200, 50000};
  AxisController chuck{"motor_b", chuck_stepper, 180, 500, 1500, 50000};
  DebouncedSwitch negative{25, SwitchMode::kEndstop};
  DebouncedSwitch positive{25, SwitchMode::kEndstop};
  DebouncedSwitch run{25, SwitchMode::kRunEnable};
  DebouncedSwitch manual{25, SwitchMode::kManualIndex};
  ShuttleController shuttle{carriage, chuck, negative, positive, run, manual,
                            450, 1, 120, 220, 1};

  void reset(bool run_pressed = false, bool negative_pressed = false,
             bool positive_pressed = false) {
    carriage_stepper.begin();
    chuck_stepper.begin();
    negative.reset(negative_pressed, 0);
    positive.reset(positive_pressed, 0);
    run.reset(run_pressed, 0);
    manual.reset(false, 0);
    shuttle.resetFromInputs();
  }

  void setRun(bool pressed) {
    run.update(pressed, 0);
    run.update(pressed, 25);
  }
};

void testConfiguredNegativeStartDirection() {
  FakeHardware carriage_hardware;
  FakeHardware chuck_hardware;
  StepDirStepper carriage_stepper(carriage_hardware, 20);
  StepDirStepper chuck_stepper(chuck_hardware, 20);
  carriage_stepper.begin();
  chuck_stepper.begin();
  AxisController carriage("motor_a", carriage_stepper, 450, 650, 1200, 50000);
  AxisController chuck("motor_b", chuck_stepper, 180, 500, 1500, 50000);
  DebouncedSwitch negative(25, SwitchMode::kEndstop);
  DebouncedSwitch positive(25, SwitchMode::kEndstop);
  DebouncedSwitch run(25, SwitchMode::kRunEnable);
  DebouncedSwitch manual(25, SwitchMode::kManualIndex);
  negative.reset(false, 0);
  positive.reset(false, 0);
  run.reset(false, 0);
  manual.reset(false, 0);
  ShuttleController shuttle(carriage, chuck, negative, positive, run, manual,
                            450, -1, 120, 220, 1);
  shuttle.resetFromInputs();
  run.update(true, 0);
  run.update(true, 25);
  shuttle.service();
  check(shuttle.currentDirection() == -1 && carriage.externalRate() == -450,
        "configured negative carriage start direction is applied");
}

void testRunSwitchInterlock() {
  ShuttleFixture fixture;
  fixture.reset(false);
  const bool stopped_rejected = fixture.shuttle.start() != nullptr;
  fixture.setRun(true);
  fixture.shuttle.service();
  const bool started = fixture.shuttle.autoEnabled() &&
                       fixture.carriage.externalRate() == 450;
  fixture.run.update(false, 26);
  fixture.shuttle.service();
  const bool stopped = !fixture.shuttle.autoEnabled() &&
                       fixture.carriage.currentRate() == 0 &&
                       fixture.chuck.currentRate() == 0;
  check(stopped_rejected && started && stopped,
        "Stop-Go cycle gates motion and Stop halts both axes");
}

void testGoAtBootFaults() {
  ShuttleFixture fixture;
  fixture.reset(true);
  check(fixture.shuttle.runFaultLatched() &&
            !fixture.shuttle.runSwitchArmed() &&
            fixture.shuttle.start() != nullptr,
        "Go at boot is fault latched");
}

void testContradictoryEndstopsFault() {
  ShuttleFixture fixture;
  fixture.reset(false, true, true);
  fixture.run.reset(true, 0);
  const char* error = fixture.shuttle.start();
  check(error != nullptr && fixture.shuttle.runFaultLatched() &&
            !fixture.shuttle.autoEnabled() &&
            strcmp(fixture.shuttle.lastReversalSource(),
                   "fault:both_endstops") == 0,
        "contradictory endstops prevent start");
}

void testReversalQueuesIndex() {
  ShuttleFixture fixture;
  fixture.reset(false);
  fixture.run.reset(true, 0);
  const bool started = fixture.shuttle.start() == nullptr;
  fixture.positive.update(true, 1);
  fixture.shuttle.service();
  check(started && fixture.shuttle.currentDirection() == -1 &&
            fixture.carriage.externalRate() == -450 &&
            fixture.chuck.hasMoveTarget() &&
            fixture.chuck.moveTargetPosition() == 120,
        "endstop reversal queues one chuck index");
}

void testOppositeEndstopFault() {
  ShuttleFixture fixture;
  fixture.reset(false);
  fixture.run.reset(true, 0);
  fixture.negative.reset(true, 0);
  fixture.negative.update(false, 0);
  fixture.negative.update(false, 25);
  fixture.shuttle.start();
  fixture.negative.update(true, 26);
  fixture.shuttle.service();
  check(!fixture.shuttle.autoEnabled() && fixture.shuttle.runFaultLatched() &&
            strcmp(fixture.shuttle.lastReversalSource(),
                   "fault:switch_13_negative_endstop") == 0 &&
            !fixture.chuck.hasMoveTarget(),
        "opposite endstop edge faults without indexing");
}

void testManualIndexOnlyOnce() {
  ShuttleFixture fixture;
  fixture.reset(false);
  fixture.run.reset(true, 0);
  fixture.shuttle.start();
  fixture.manual.update(true, 0);
  fixture.manual.update(true, 25);
  fixture.shuttle.service();
  fixture.shuttle.service();
  check(fixture.chuck.hasMoveTarget() &&
            fixture.chuck.moveTargetPosition() == 120,
        "manual index queues once per close edge");
}

void runTests() {
  testSafeEnableInitialization();
  testRateChangePreservesIntervalFraction();
  testLongStallSkipsCatchUpBurst();
  testMicrosWrap();
  testAxisAccelerationAndBraking();
  testFractionalAccelerationProgress();
  testQueuedMovesAndExactStop();
  testLimitImmediateStop();
  testDirectionChangeStopsFirst();
  testAsymmetricDebounce();
  testConfiguredNegativeStartDirection();
  testRunSwitchInterlock();
  testGoAtBootFaults();
  testContradictoryEndstopsFault();
  testReversalQueuesIndex();
  testOppositeEndstopFault();
  testManualIndexOnlyOnce();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  const uint32_t started_ms = millis();
  while (!Serial && millis() - started_ms < 5000) {
  }
  Serial.print("SELFTEST BEGIN\r\n");
  runTests();
  Serial.printf("SELFTEST %s passed=%d failed=%d\r\n",
                failed == 0 ? "PASS" : "FAIL", passed, failed);
}

void loop() {}
