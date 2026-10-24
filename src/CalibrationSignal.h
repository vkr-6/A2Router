#pragma once
#include "ChannelMatrix.h"
#include <cstring>

namespace a2r {
inline constexpr double chirpDuration = 0.18;
inline double calibrationChirp(double time) noexcept {
    if (time < 0 || time >= chirpDuration) return 0;
    constexpr double pi = 3.14159265358979323846;
    const double phase = 2 * pi * (800 * time + 0.5 * (3800 - 800) / chirpDuration * time * time);
    return std::sin(phase) * (0.5 - 0.5 * std::cos(2 * pi * time / chirpDuration));
}
inline void writeCalibrationSample(uint8_t* target, const mux::PcmEncoding& encoding, double value) noexcept {
    value = std::clamp(value, -1.0, 1.0);
    if (encoding.floating) {
        const float sample = static_cast<float>(value);
        std::memcpy(target, &sample, sizeof(sample));
    } else {
        const int64_t scale = (int64_t(1) << (encoding.valid_bits - 1)) - 1;
        const int64_t sample = std::llround(value * static_cast<double>(scale)) *
            (int64_t(1) << (encoding.bits - encoding.valid_bits));
        const auto word = static_cast<uint32_t>(sample);
        for (unsigned byte = 0; byte < static_cast<unsigned>(encoding.bits) / 8u; ++byte)
            target[byte] = static_cast<uint8_t>(word >> (8 * byte));
    }
}
}
