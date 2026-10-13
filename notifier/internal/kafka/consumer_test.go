package kafka

import (
	"maps"
	"testing"
)

func TestConfigFromEnv(t *testing.T) {
	config, ok := ConfigFromEnv([]string{
		"KAFKA_BOOTSTRAP_SERVERS=ns.servicebus.windows.net:9093",
		"KAFKA_SASL_USERNAME=$ConnectionString",
		"KAFKA_SASL_PASSWORD=Endpoint=sb://ns/;Key=a=b",
		"KAFKA_=ignored",
		"HOME=/root",
	})
	want := map[string]string{
		"bootstrap.servers": "ns.servicebus.windows.net:9093",
		"sasl.username":     "$ConnectionString",
		"sasl.password":     "Endpoint=sb://ns/;Key=a=b",
	}
	if !ok || !maps.Equal(config, want) {
		t.Errorf("ConfigFromEnv = %v, %v", config, ok)
	}
	if _, ok := ConfigFromEnv([]string{"KAFKA_CLIENT_ID=x"}); ok {
		t.Error("ok without KAFKA_BOOTSTRAP_SERVERS")
	}
}
