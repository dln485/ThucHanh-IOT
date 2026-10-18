#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <DHTesp.h>
#include "ca_cert.h"
#include <time.h>
#include <sys/time.h>

// WiFi cua Wokwi
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";

// EMQX Cloud
const char* MQTT_SERVER =
  "s72c1296.ala.asia-southeast1.emqxsl.com";
const int MQTT_PORT = 8883;
const char* MQTT_USERNAME = "ThucHanh2";   //
const char* MQTT_PASSWORD = "Ding@2005";  
const char* MQTT_TOPIC = "iot/thuchanh2/telemetry";

// Chan cam bien: giu nguyen mach cu
const int DHT_PIN = 15;
const int TRIG_PIN = 5;
const int ECHO_PIN = 18;
const int LED_PIN = 2;

const unsigned long SEND_INTERVAL_MS = 5000;

WiFiClientSecure wifiClient;
PubSubClient mqttClient(wifiClient);
DHTesp dht;

unsigned long lastSend = 0;
unsigned long sequenceNo = 0;

void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD, 6);

  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
}

// Dong bo gio that qua NTP (can thiet de do do tre end-to-end)
void syncTime() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  Serial.print("Syncing time");
  while (time(nullptr) < 1700000000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nTime synced");
}

// Thoi gian hien tai tinh bang mili giay (epoch UTC)
uint64_t getEpochMs() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return (uint64_t)tv.tv_sec * 1000ULL + tv.tv_usec / 1000;
}

void connectMQTT() {
  while (!mqttClient.connected()) {
    String clientId = "ESP32-ThucHanh2-" +
                      String((uint32_t)ESP.getEfuseMac(), HEX);

    Serial.print("Connecting EMQX...");

    if (mqttClient.connect(
          clientId.c_str(),
          MQTT_USERNAME,
          MQTT_PASSWORD)) {
      Serial.println(" connected");
    } else {
      Serial.printf(
        " failed, rc=%d. Retry in 3 seconds\n",
        mqttClient.state()
      );
      delay(3000);
    }
  }
}

float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  unsigned long duration =
    pulseIn(ECHO_PIN, HIGH, 30000);

  if (duration == 0) {
    return NAN;
  }

  return duration * 0.0343f / 2.0f;
}

void setup() {
  Serial.begin(115200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);

  dht.setup(DHT_PIN, DHTesp::DHT22);

  // Su dung CA de xac minh may chu TLS
  wifiClient.setCACert(ROOT_CA);

  mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
  mqttClient.setBufferSize(512);

  connectWiFi();
  syncTime();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  if (!mqttClient.connected()) {
    Serial.printf("MQTT disconnected, state=%d\n", mqttClient.state());
    connectMQTT();
  }

  mqttClient.loop();

  unsigned long now = millis();
  if (now - lastSend < SEND_INTERVAL_MS) {
    return;
  }
  lastSend = now;

  TempAndHumidity data = dht.getTempAndHumidity();
  float distance = readDistanceCm();

  if (!isfinite(data.temperature) ||
      !isfinite(data.humidity) ||
      !isfinite(distance)) {
    Serial.println("Invalid sensor data - skip publish");
    return;
  }

  sequenceNo++;
  uint64_t tsMs = getEpochMs();

  char payload[256];
  snprintf(
    payload, sizeof(payload),
    "{\"temperature\":%.2f,\"humidity\":%.2f,"
    "\"distance_cm\":%.2f,\"rssi\":%d,"
    "\"sequence\":%lu,\"uptime_s\":%lu,"
    "\"ts_ms\":%llu}",
    data.temperature,
    data.humidity,
    distance,
    WiFi.RSSI(),
    sequenceNo,
    millis() / 1000,
    (unsigned long long)tsMs
  );

  bool ok = mqttClient.publish(MQTT_TOPIC, payload);

  Serial.printf(
    "Topic: %s | %s | publish=%s\n",
    MQTT_TOPIC, payload, ok ? "OK" : "FAILED"
  );

  digitalWrite(LED_PIN, HIGH);
  delay(80);
  digitalWrite(LED_PIN, LOW);
}