#include "AudioRingBuffer.h"
#include "ClockDriftController.h"
#include "Logging.h"
#include "ChannelMatrix.h"
#include "EndpointRename.h"
#include "CalibrationSignal.h"
#include <limits>
#include <cmath>
#include <array>
#include <iostream>
#include <thread>
#include <stdexcept>

void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
int main() {
    try {
        require(a2r::calibrationChirp(-1) == 0 && a2r::calibrationChirp(0) == 0 &&
            a2r::calibrationChirp(a2r::chirpDuration) == 0, "calibration chirp bounds");
        uint8_t encoded[4]{};
        const mux::PcmEncoding calibrationPcm{1, 32, 24, false};
        a2r::writeCalibrationSample(encoded, calibrationPcm, 0.025);
        require(std::abs(calibrationPcm.read(encoded) - 0.025) < 1e-6, "calibration PCM valid-bit encoding");
        for (int i = 0; i < 8640; ++i)
            require(std::abs(a2r::calibrationChirp(i / 48000.0)) <= 1, "calibration chirp amplitude");
        // A rejected property write must not trigger a second, equally denied
        // rollback write or obscure the original access-denied HRESULT.
        std::wstring name = L"Original";
        int writes = 0;
        auto readName = [&]() -> std::optional<std::wstring> { return name; };
        auto denied = a2r::renameVerified(L"New", readName,
            [&](const std::wstring&) -> long { ++writes; return -5; }, [] {});
        require(denied.state == a2r::RenameState::Rejected && denied.result == -5 && writes == 1,
            "rename denial must preserve original and avoid rollback write");
        int reads = 0;
        auto delayed = a2r::renameVerified(L"New",
            [&]() -> std::optional<std::wstring> { return ++reads >= 4 ? L"New" : L"Original"; },
            [&](const std::wstring&) -> long { ++writes; return 0; }, [] {});
        require(delayed.state == a2r::RenameState::Verified && writes == 2,
            "rename must tolerate delayed fresh-store observation");
        auto unreadable = a2r::renameVerified(L"New", []() -> std::optional<std::wstring> { return {}; },
            [&](const std::wstring&) -> long { ++writes; return 0; }, [] {});
        require(unreadable.state == a2r::RenameState::ReadFailed && writes == 2,
            "do not write when previous name is unreadable");
        name = L"Original";
        auto rollback = a2r::renameVerified(L"New", readName,
            [&](const std::wstring& value) -> long { name = value == L"New" ? L"Unexpected" : value; return 0; }, [] {});
        require(rollback.state == a2r::RenameState::Restored && name == L"Original", "rename rollback verification");
        const mux::PcmEncoding floats{2, 32, 32, true};
        const std::array<float, 4> samples{0.25f, -0.5f, 0.75f, 0.5f};
        std::array<float, 6> mapped{};
        mux::ChannelMatrix swap(floats, 2, {{0, 1, 1}, {1, 0, 1}});
        require(swap.process(reinterpret_cast<const uint8_t*>(samples.data()), mapped.data(), 2) == 0, "unexpected clipping");
        require(mapped[0] == -0.5f && mapped[1] == 0.25f && mapped[2] == 0.5f && mapped[3] == 0.75f, "channel swap");
        mux::ChannelMatrix duplicate(floats, 3, {{0, 0, 1}, {0, 1, 1}});
        duplicate.process(reinterpret_cast<const uint8_t*>(samples.data()), mapped.data(), 2);
        require(mapped[0] == 0.25f && mapped[1] == 0.25f && mapped[2] == 0 && mapped[5] == 0, "duplication/unmapped silence");
        mux::ChannelMatrix sum(floats, 1, {{0, 0, 1}, {1, 0, 1}});
        require(sum.process(reinterpret_cast<const uint8_t*>(samples.data()), mapped.data(), 2) == 1, "mix clipping count");
        require(mapped[0] == -0.25f && mapped[1] == 1.0f, "summing/clipping");
        mux::ChannelMatrix identity(floats, 2, {{0, 0, 1}, {1, 1, 1}});
        identity.process(reinterpret_cast<const uint8_t*>(samples.data()), mapped.data(), 2);
        require(std::equal(samples.begin(), samples.end(), mapped.begin()), "float identity integrity");
        const float surround[] = {0.1f, 0.2f, 0.3f, 0.4f, 0.5f, 0.6f};
        std::array<float, 8> multichannel{};
        mux::ChannelMatrix surroundMap({6, 32, 32, true}, 8,
            {{0, 0, 1}, {1, 1, 1}, {2, 2, 1}, {3, 3, 1}, {4, 4, 1}, {5, 5, 1}});
        surroundMap.process(reinterpret_cast<const uint8_t*>(surround), multichannel.data(), 1);
        require(std::equal(surround, surround + 6, multichannel.begin()) && multichannel[6] == 0 && multichannel[7] == 0,
            "multichannel order/preservation");
        mux::ChannelMatrix inverse(floats, 2, {{0, 0, -2}, {1, 1, -2}});
        require(inverse.process(reinterpret_cast<const uint8_t*>(samples.data()), mapped.data(), 2) == 1,
            "negative gain clipping count");
        require(mapped[0] == -0.5f && mapped[1] == 1 && mapped[2] == -1 && mapped[3] == -1,
            "gain/inversion/clipping");
        const uint8_t pcm16[] = {0, 0x80, 0xff, 0x7f};
        mux::ChannelMatrix decode16({2, 16, 16, false}, 2, {{0, 0, 1}, {1, 1, 1}});
        decode16.process(pcm16, mapped.data(), 1);
        require(mapped[0] == -1 && mapped[1] == 32767.0f / 32768.0f, "PCM16 decode");
        const uint8_t pcm24[] = {0, 0, 0x80, 0, 0, 0x40};
        mux::ChannelMatrix decode24({2, 24, 24, false}, 2, {{0, 0, 1}, {1, 1, 1}});
        decode24.process(pcm24, mapped.data(), 1);
        require(mapped[0] == -1 && mapped[1] == 0.5f, "PCM24 decode");
        const uint8_t pcm32[] = {0, 0, 0, 0x80, 0, 0, 0, 0x40};
        mux::ChannelMatrix decode32({2, 32, 24, false}, 2, {{0, 0, 1}, {1, 1, 1}});
        decode32.process(pcm32, mapped.data(), 1);
        require(mapped[0] == -1 && mapped[1] == 0.5f, "PCM32 valid-bit alignment");
        const float nonfinite[] = {std::numeric_limits<float>::quiet_NaN(), std::numeric_limits<float>::infinity()};
        identity.process(reinterpret_cast<const uint8_t*>(nonfinite), mapped.data(), 1);
        require(mapped[0] == 0 && mapped[1] == 0, "non-finite sample protection");
        bool invalid = false;
        try { mux::ChannelMatrix bad(floats, 2, {{2, 0, 1}}); } catch (const std::invalid_argument&) { invalid = true; }
        require(invalid, "invalid channel accepted");
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
