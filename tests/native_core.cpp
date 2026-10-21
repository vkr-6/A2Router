#include "AudioRingBuffer.h"
#include "ClockDriftController.h"
#include "Logging.h"
#include <array>
#include <iostream>
#include <thread>
#include <stdexcept>

void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
int main() {
    try {
        mux::AudioRingBuffer ring(31);
        std::array<uint8_t, 24> original{}, output{};
        for (size_t i = 0; i < original.size(); ++i) original[i] = static_cast<uint8_t>(i * 7);
        for (int i = 0; i < 100; ++i) {
            require(ring.write(original.data(), original.size()), "write");
            require(!ring.write(original.data(), original.size()), "overflow must be atomic");
            require(ring.read(output.data(), output.size()) == original.size(), "read size");
            require(output == original, "PCM bytes changed across wraparound");
        }
        require(ring.write_silence(16), "silence");
        require(ring.skip(8) == 8, "consumer skip");
        require(ring.read(output.data(), 16) == 8, "partial read");
        for (int i = 0; i < 8; ++i) require(output[i] == 0, "nonzero silence");
        mux::AudioRingBuffer concurrent(4096);
        std::thread producer([&] {
            for (uint32_t i = 0; i < 100000; ++i)
                while (!concurrent.write(reinterpret_cast<uint8_t*>(&i), sizeof(i))) std::this_thread::yield();
        });
        bool ordered = true;
        for (uint32_t i = 0; i < 100000; ++i) {
            uint32_t got = 0;
            while (concurrent.read(reinterpret_cast<uint8_t*>(&got), sizeof(got)) == 0) std::this_thread::yield();
            if (got != i) ordered = false;
        }
        producer.join();
        require(ordered, "SPSC sequence corrupted");
        mux::DriftControlParams params;
        params.ema_alpha = 1.0f;
        mux::ClockDriftController drift(48000, params);
        require(drift.update(1000, 1000, 1000).applied_rate_hz == 48000, "neutral clock");
        auto high = drift.update(2000, 1000, 1000);
        require(high.rate_changed && high.applied_rate_hz > 48000 && high.applied_rate_hz <= 48120, "drain overflow");
        auto low = drift.update(0, 1000, 1000);
        require(low.applied_rate_hz < 48000 && low.applied_rate_hz >= 47880, "avoid starvation");
        require(drift.update(10, 10, 0).applied_rate_hz == low.applied_rate_hz, "zero range");
        std::cout << "PCM integrity, wraparound, SPSC concurrency and clock correction passed\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
