/*
 * Force Sensing Resistor (FSR) Reader
 *
 * Minimal example: reads an FSR through a voltage divider on
 * analog pin A0 and prints the value over the serial port
 * 10 times per second.
 *
 * Wiring (voltage divider):
 *
 *   5V ----[ FSR ]----+----[ 10k resistor ]---- GND
 *                     |
 *                     A0
 *
 * (On a Pro Micro the 5V pin is labeled VCC.)
 *
 * How it works: the FSR's resistance drops as you press harder
 * (~1 Mohm untouched, down to a few kohm under firm pressure).
 * The FSR and the fixed 10k resistor form a voltage divider, so
 * the voltage at A0 rises with pressure. analogRead() converts
 * that voltage (0-5V) to an integer 0-1023.
 *
 * View the output with:
 *   arduino-cli monitor -p <your-port> --config baudrate=115200
 */

const int FSR_PIN = A0;        // analog input pin
const int LED_PIN = 17;        // Pro Micro RX LED (active-LOW: LOW = lit).
                               // On Leonardo/Uno use 13 (active-HIGH) and
                               // swap LOW/HIGH in the digitalWrite below.
const unsigned long SAMPLE_INTERVAL_MS = 100;   // 10 Hz

unsigned long nextSampleTime = 0;

void setup() {
  pinMode(LED_PIN, OUTPUT);

  Serial.begin(115200);
  // On ATmega32U4 boards (Leonardo, Pro Micro) the USB serial port
  // takes a moment to connect. Wait up to 3 s so the first prints
  // aren't lost, but don't hang forever if no monitor is attached.
  unsigned long waitStart = millis();
  while (!Serial && (millis() - waitStart < 3000)) {
    ;
  }

  Serial.println("FSR reader ready");
  Serial.println("raw (0-1023)\tvoltage (V)");
}

void loop() {
  if (millis() >= nextSampleTime) {
    nextSampleTime = millis() + SAMPLE_INTERVAL_MS;

    int raw = analogRead(FSR_PIN);              // 0-1023
    float voltage = raw * (5.0 / 1023.0);       // convert to volts

    Serial.print(raw);
    Serial.print('\t');
    Serial.println(voltage, 2);

    // Light the LED when pressed (threshold is arbitrary; tune it).
    // The Pro Micro RX LED lights when the pin is LOW.
    digitalWrite(LED_PIN, raw > 300 ? LOW : HIGH);
  }
}
